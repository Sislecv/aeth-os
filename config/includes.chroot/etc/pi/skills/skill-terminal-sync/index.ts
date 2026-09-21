import * as fs from "node:fs";
import * as path from "node:path";
import * as os from "node:os";
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
    "/bin",
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
    name: "terminal_read_pane",
    label: "Read Left Shell Viewport",
    description: "Reads recent terminal output lines from the user's left shell pane in Zellij companion split.",
    parameters: {
      type: "object",
      properties: {
        lines: {
          type: "number",
          description: "Number of recent lines to retrieve (default: 50)",
        },
      },
    },
    async execute(arg1?: any, arg2?: any) {
      const params = extractParams(arg1, arg2);
      const linesCount = typeof params.lines === "number" && params.lines > 0 ? params.lines : 50;
      const zellijBin = resolveBinary("zellij", "ZELLIJ_BIN");

      // Attempt Zellij dump-screen
      const tmpFile = path.join(os.tmpdir(), `agentic-screen-dump-${Date.now()}-${Math.random().toString(36).slice(2)}.txt`);
      try {
        // Move focus to left pane, dump screen, return focus to right pane
        spawnSync(zellijBin, ["action", "move-focus", "left"], { encoding: "utf-8", timeout: 3000 });
        const dumpProc = spawnSync(zellijBin, ["action", "dump-screen", tmpFile], { encoding: "utf-8", timeout: 3000 });
        spawnSync(zellijBin, ["action", "move-focus", "right"], { encoding: "utf-8", timeout: 3000 });

        if (fs.existsSync(tmpFile)) {
          const raw = fs.readFileSync(tmpFile, "utf-8");
          fs.unlinkSync(tmpFile);
          const allLines = raw.split("\n");
          const sliced = allLines.slice(-linesCount).join("\n");
          return {
            content: [{ type: "text", text: sliced || "(Pane screen is currently empty)" }],
            details: { lines: linesCount, source: "zellij" },
          };
        }

        if (dumpProc.error || dumpProc.status !== 0) {
          // Fallback: inspect bash history if not inside active Zellij session
          const histFile = path.join(process.env.HOME || "/root", ".bash_history");
          if (fs.existsSync(histFile)) {
            const hist = fs.readFileSync(histFile, "utf-8").split("\n").filter(Boolean);
            const sliced = hist.slice(-linesCount).join("\n");
            return {
              content: [{ type: "text", text: `(Zellij dump unavailable, showing recent command history):\n${sliced}` }],
              details: { lines: linesCount, source: "history_fallback" },
            };
          }
        }
      } catch (err: any) {
        if (fs.existsSync(tmpFile)) {
          try { fs.unlinkSync(tmpFile); } catch {}
        }
      }

      return {
        content: [{ type: "text", text: "No active Zellij terminal session detected or unable to dump pane screen." }],
        details: { lines: linesCount, status: "not_connected" },
      };
    },
  },

  {
    name: "terminal_send_command",
    label: "Send Command to Left Shell Pane",
    description: "Types a suggested command into the user's left shell pane in Zellij, with optional immediate execution.",
    parameters: {
      type: "object",
      properties: {
        command: {
          type: "string",
          description: "Shell command string to write to the user's terminal",
        },
        execute: {
          type: "boolean",
          description: "If true, sends Enter (newline) to execute the command immediately; if false, pre-fills the prompt for user review (default: false)",
        },
      },
      required: ["command"],
    },
    async execute(arg1?: any, arg2?: any) {
      const params = extractParams(arg1, arg2);
      if (!params.command) {
        return {
          content: [{ type: "text", text: "Error: 'command' parameter is required." }],
          isError: true,
        };
      }

      const zellijBin = resolveBinary("zellij", "ZELLIJ_BIN");
      const shouldExec = !!params.execute;

      // Focus left pane, write command characters, optional newline, return focus to right pane
      spawnSync(zellijBin, ["action", "move-focus", "left"], { encoding: "utf-8", timeout: 3000 });
      const writeProc = spawnSync(zellijBin, ["action", "write-chars", String(params.command)], { encoding: "utf-8", timeout: 3000 });
      if (shouldExec) {
        spawnSync(zellijBin, ["action", "write", "10"], { encoding: "utf-8", timeout: 2000 });
      }
      spawnSync(zellijBin, ["action", "move-focus", "right"], { encoding: "utf-8", timeout: 3000 });

      if (writeProc.error) {
        return {
          content: [{ type: "text", text: `Command suggested: \`${params.command}\` (Zellij connection error: ${writeProc.error.message})` }],
          details: { command: params.command, execute: shouldExec, error: writeProc.error.message },
        };
      }

      return {
        content: [{
          type: "text",
          text: shouldExec
            ? `Dispatched and executed command in left pane: \`${params.command}\``
            : `Pasted command into left pane for user confirmation: \`${params.command}\``,
        }],
        details: { command: params.command, execute: shouldExec, status: writeProc.status },
      };
    },
  },

  {
    name: "terminal_new_tab",
    label: "Open New Zellij Tab",
    description: "Creates a new named tab in the active Zellij companion workspace.",
    parameters: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "Name for the new tab (e.g. 'Build', 'Logs')",
        },
        layout: {
          type: "string",
          description: "Optional layout file or template name",
        },
      },
    },
    async execute(arg1?: any, arg2?: any) {
      const params = extractParams(arg1, arg2);
      const zellijBin = resolveBinary("zellij", "ZELLIJ_BIN");
      const args = ["action", "new-tab"];

      if (params.name) {
        args.push("--name", String(params.name));
      }
      if (params.layout) {
        args.push("--layout", String(params.layout));
      }

      const proc = spawnSync(zellijBin, args, { encoding: "utf-8", timeout: 5000 });
      if (proc.error) {
        return {
          content: [{ type: "text", text: `Error creating tab: ${proc.error.message}` }],
          isError: true,
        };
      }

      return {
        content: [{ type: "text", text: proc.stdout || proc.stderr || `Created new tab${params.name ? ` '${params.name}'` : ''}.` }],
        details: { name: params.name, layout: params.layout, status: proc.status },
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
if (process.argv[1] && (process.argv[1] === fileURLToPath(import.meta.url) || process.argv[1].includes("skill-terminal-sync"))) {
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
