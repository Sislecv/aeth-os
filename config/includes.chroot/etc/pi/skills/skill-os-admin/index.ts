import * as fs from "node:fs";
import * as path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function resolveBinary(name: string, envVar?: string): string {
  if (envVar && process.env[envVar]) {
    return process.env[envVar]!;
  }
  const searchDirs = [
    "/usr/local/bin",
    "/usr/bin",
    "/usr/sbin",
    "/bin",
    "/sbin",
    path.resolve(process.cwd(), "config/includes.chroot/usr/local/bin"),
    path.resolve(__dirname, "../../../../usr/local/bin"),
  ];
  const pathDirs = (process.env.PATH || "").split(":");
  for (const dir of [...pathDirs, ...searchDirs]) {
    if (!dir) continue;
    const candidate = path.join(dir, name);
    try {
      if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) {
        return candidate;
      }
    } catch {}
  }
  return name;
}

function extractParams(arg1?: any, arg2?: any): Record<string, any> {
  if (arg2 !== undefined && typeof arg2 === "object" && arg2 !== null) {
    return arg2;
  }
  if (typeof arg1 === "object" && arg1 !== null) {
    return arg1;
  }
  return {};
}

export interface PiToolDefinition {
  name: string;
  label?: string;
  description: string;
  parameters: {
    type: "object";
    properties: Record<string, any>;
    required?: string[];
  };
  execute: (arg1?: any, arg2?: any) => Promise<any> | any;
}

export const tools: PiToolDefinition[] = [
  {
    name: "sys_doctor",
    label: "Check OS Health & Hardware Diagnostics",
    description: "Inspects system health: battery, physical RAM, zRAM swap, disk/USB wear, and GPU acceleration status.",
    parameters: {
      type: "object",
      properties: {},
    },
    async execute(_arg1?: any, _arg2?: any) {
      const piDoctorBin = resolveBinary("pi-doctor", "PI_DOCTOR_BIN");
      if (fs.existsSync(piDoctorBin)) {
        const proc = spawnSync(piDoctorBin, ["--json"], { encoding: "utf-8", timeout: 10000 });
        if (proc.status === 0 && proc.stdout) {
          return {
            content: [{ type: "text", text: proc.stdout }],
            details: { source: "pi-doctor" },
          };
        }
      }

      // Built-in system inspection fallback
      const health: Record<string, any> = {
        timestamp: new Date().toISOString(),
        system: {
          platform: process.platform,
          arch: process.arch,
          uptime_seconds: Math.floor(process.uptime()),
        },
      };

      // 1. Memory / RAM
      try {
        const meminfo = fs.readFileSync("/proc/meminfo", "utf-8");
        const totalMatch = meminfo.match(/MemTotal:\s+(\d+)\s+kB/);
        const availMatch = meminfo.match(/MemAvailable:\s+(\d+)\s+kB/);
        if (totalMatch && availMatch) {
          const totalMb = Math.round(parseInt(totalMatch[1], 10) / 1024);
          const availMb = Math.round(parseInt(availMatch[1], 10) / 1024);
          health.memory = {
            total_mb: totalMb,
            available_mb: availMb,
            used_percent: Math.round(((totalMb - availMb) / totalMb) * 100),
          };
        }
      } catch {
        health.memory = { error: "Unable to read /proc/meminfo" };
      }

      // 2. zRAM / Swap
      try {
        const swaps = fs.readFileSync("/proc/swaps", "utf-8");
        const hasZram = swaps.includes("/dev/zram");
        health.zram = {
          active: hasZram,
          raw: swaps.trim(),
        };
      } catch {
        health.zram = { active: false };
      }

      // 3. Battery status
      try {
        const psuDir = "/sys/class/power_supply";
        if (fs.existsSync(psuDir)) {
          const supplies = fs.readdirSync(psuDir);
          const batteries = supplies.filter((s) => s.startsWith("BAT"));
          if (batteries.length > 0) {
            const bat = batteries[0];
            const capacityFile = path.join(psuDir, bat, "capacity");
            const statusFile = path.join(psuDir, bat, "status");
            health.battery = {
              device: bat,
              capacity: fs.existsSync(capacityFile) ? fs.readFileSync(capacityFile, "utf-8").trim() + "%" : "unknown",
              status: fs.existsSync(statusFile) ? fs.readFileSync(statusFile, "utf-8").trim() : "unknown",
            };
          } else {
            health.battery = { status: "AC / Desktop (No Battery)" };
          }
        }
      } catch {
        health.battery = { status: "Not detectable" };
      }

      // 4. Disk & persistence mount
      try {
        const dfProc = spawnSync("df", ["-h", "/"], { encoding: "utf-8", timeout: 3000 });
        health.storage = {
          root_fs: dfProc.stdout ? dfProc.stdout.trim() : "unknown",
        };
      } catch {
        health.storage = { error: "Unable to run df" };
      }

      // 5. GPU acceleration
      try {
        const drmDir = "/sys/class/drm";
        if (fs.existsSync(drmDir)) {
          const cards = fs.readdirSync(drmDir).filter((e) => e.startsWith("card") && !e.includes("-"));
          health.gpu = {
            detected_cards: cards,
            acceleration: cards.length > 0 ? "available" : "software",
          };
        }
      } catch {
        health.gpu = { acceleration: "unknown" };
      }

      return {
        content: [{ type: "text", text: JSON.stringify(health, null, 2) }],
        details: health,
      };
    },
  },

  {
    name: "sys_wifi_status",
    label: "WiFi Network Status",
    description: "Inspects WiFi connection status and lists available wireless networks via NetworkManager (nmcli).",
    parameters: {
      type: "object",
      properties: {
        rescan: {
          type: "boolean",
          description: "Whether to force a fresh WiFi scan before reporting (default: false)",
        },
      },
    },
    async execute(arg1?: any, arg2?: any) {
      const params = extractParams(arg1, arg2);
      const nmcliBin = resolveBinary("nmcli", "NMCLI_BIN");

      if (params.rescan) {
        spawnSync(nmcliBin, ["device", "wifi", "rescan"], { encoding: "utf-8", timeout: 5000 });
      }

      const proc = spawnSync(nmcliBin, ["-t", "-f", "active,ssid,bssid,signal,security", "device", "wifi", "list"], {
        encoding: "utf-8",
        timeout: 10000,
      });

      if (proc.error || proc.status !== 0) {
        const genProc = spawnSync(nmcliBin, ["general", "status"], { encoding: "utf-8", timeout: 5000 });
        return {
          content: [{ type: "text", text: genProc.stdout || proc.stderr || "WiFi information currently unavailable." }],
          details: { status: proc.status },
        };
      }

      const lines = (proc.stdout || "").trim().split("\n").filter(Boolean);
      const networks = lines.map((line) => {
        const [active, ssid, bssid, signal, security] = line.split(":");
        return { active: active === "yes", ssid, bssid, signal: `${signal}%`, security };
      });

      return {
        content: [{ type: "text", text: JSON.stringify(networks, null, 2) }],
        details: { count: networks.length },
      };
    },
  },

  {
    name: "sys_wifi_connect",
    label: "Connect to WiFi Network",
    description: "Connects to a specified WiFi network using NetworkManager (nmcli).",
    parameters: {
      type: "object",
      properties: {
        ssid: {
          type: "string",
          description: "SSID / Network name to connect to",
        },
        password: {
          type: "string",
          description: "Optional WPA/WPA2/WPA3 password",
        },
      },
      required: ["ssid"],
    },
    async execute(arg1?: any, arg2?: any) {
      const params = extractParams(arg1, arg2);
      if (!params.ssid) {
        return {
          content: [{ type: "text", text: "Error: 'ssid' parameter is required." }],
          isError: true,
        };
      }

      const nmcliBin = resolveBinary("nmcli", "NMCLI_BIN");
      const args = ["device", "wifi", "connect", String(params.ssid)];
      if (params.password) {
        args.push("password", String(params.password));
      }

      const proc = spawnSync(nmcliBin, args, { encoding: "utf-8", timeout: 20000 });
      if (proc.error) {
        return {
          content: [{ type: "text", text: `Error connecting to WiFi: ${proc.error.message}` }],
          isError: true,
        };
      }

      return {
        content: [{ type: "text", text: proc.stdout || proc.stderr || `Connecting to WiFi network '${params.ssid}'...` }],
        details: { ssid: params.ssid, status: proc.status },
      };
    },
  },

  {
    name: "sys_package_info",
    label: "Inspect Debian/Ubuntu Package",
    description: "Queries details, version, and dependencies of a package via apt-cache or dpkg.",
    parameters: {
      type: "object",
      properties: {
        package_name: {
          type: "string",
          description: "Package name to query (e.g. 'htop', 'git', 'sqlite3')",
        },
      },
      required: ["package_name"],
    },
    async execute(arg1?: any, arg2?: any) {
      const params = extractParams(arg1, arg2);
      if (!params.package_name) {
        return {
          content: [{ type: "text", text: "Error: 'package_name' parameter is required." }],
          isError: true,
        };
      }

      const aptCacheBin = resolveBinary("apt-cache");
      const proc = spawnSync(aptCacheBin, ["show", String(params.package_name)], { encoding: "utf-8", timeout: 10000 });

      if (proc.error || proc.status !== 0) {
        const dpkgBin = resolveBinary("dpkg");
        const dpkgProc = spawnSync(dpkgBin, ["-s", String(params.package_name)], { encoding: "utf-8", timeout: 5000 });
        return {
          content: [{ type: "text", text: dpkgProc.stdout || proc.stderr || `Package '${params.package_name}' not found.` }],
          details: { package: params.package_name, status: dpkgProc.status },
        };
      }

      return {
        content: [{ type: "text", text: proc.stdout }],
        details: { package: params.package_name },
      };
    },
  },

  {
    name: "sys_package_install",
    label: "Install System Packages",
    description: "Installs packages using apt-get with automatic non-interactive confirmation.",
    parameters: {
      type: "object",
      properties: {
        packages: {
          type: "string",
          description: "Space-separated or comma-separated package names (e.g. 'ripgrep fzf' or 'tree')",
        },
        dry_run: {
          type: "boolean",
          description: "Simulate installation without modifying the system (default: false)",
        },
      },
      required: ["packages"],
    },
    async execute(arg1?: any, arg2?: any) {
      const params = extractParams(arg1, arg2);
      if (!params.packages) {
        return {
          content: [{ type: "text", text: "Error: 'packages' parameter is required." }],
          isError: true,
        };
      }

      const pkgList = Array.isArray(params.packages)
        ? params.packages
        : String(params.packages).split(/[,\s]+/).filter(Boolean);

      const aptGetBin = resolveBinary("apt-get");
      const args = ["install", "-y"];
      if (params.dry_run) {
        args.push("-s");
      }
      args.push(...pkgList);

      const proc = spawnSync(aptGetBin, args, {
        encoding: "utf-8",
        timeout: 60000,
        env: { ...process.env, DEBIAN_FRONTEND: "noninteractive" },
      });

      if (proc.error) {
        return {
          content: [{ type: "text", text: `Error executing apt-get install: ${proc.error.message}` }],
          isError: true,
        };
      }

      return {
        content: [{ type: "text", text: proc.stdout || proc.stderr || "Package installation completed." }],
        details: { packages: pkgList, dry_run: !!params.dry_run, status: proc.status },
      };
    },
  },

  {
    name: "sys_zen_mode",
    label: "Toggle Zen Focus Mode",
    description: "Toggles or checks Zen focus mode (silencing notification banners, hiding panel) via agentic-zen-toggle.",
    parameters: {
      type: "object",
      properties: {
        action: {
          type: "string",
          description: "Action: 'toggle' (default), 'on', 'off', or 'status'",
        },
      },
    },
    async execute(arg1?: any, arg2?: any) {
      const params = extractParams(arg1, arg2);
      const zenBin = resolveBinary("agentic-zen-toggle", "AGENTIC_ZEN_TOGGLE_BIN");
      const action = params.action ? `--${params.action.replace(/^--/, "")}` : "--toggle";

      const proc = spawnSync(zenBin, [action], { encoding: "utf-8", timeout: 10000 });
      if (proc.error) {
        return {
          content: [{ type: "text", text: `Error running agentic-zen-toggle: ${proc.error.message}` }],
          isError: true,
        };
      }

      return {
        content: [{ type: "text", text: proc.stdout || proc.stderr || `Zen mode action ${action} executed.` }],
        details: { action, status: proc.status },
      };
    },
  },
];

export default function register(pi: any) {
  if (pi && typeof pi.registerTool === "function") {
    for (const tool of tools) {
      pi.registerTool(tool);
    }
  }
}

// CLI runner when executed directly via Node.js
if (process.argv[1] && (process.argv[1] === fileURLToPath(import.meta.url) || process.argv[1].includes("skill-os-admin"))) {
  const toolName = process.argv[2];
  if (toolName) {
    const tool = tools.find((t) => t.name === toolName);
    if (!tool) {
      console.error(`Unknown tool: ${toolName}`);
      process.exit(1);
    }
    const params = process.argv[3] ? JSON.parse(process.argv[3]) : {};
    Promise.resolve(tool.execute(params)).then((res) => {
      console.log(JSON.stringify(res, null, 2));
    }).catch((err) => {
      console.error(err);
      process.exit(1);
    });
  }
}
