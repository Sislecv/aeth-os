import * as fs from "node:fs";
import * as path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

/**
 * Resolves binary path checking environment variable, PATH, and standard AgenticOS locations.
 */
function resolveBinary(name: string, envVar?: string): string {
  if (envVar && process.env[envVar]) {
    return process.env[envVar]!;
  }
  const searchDirs = [
    "/usr/local/bin",
    "/usr/bin",
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
    name: "desktop_inspect_tree",
    label: "Inspect Desktop AT-SPI2 Tree",
    description: "Queries the AT-SPI2 accessibility tree of active windows on Workspace 2 (Ghost Workspace). Returns JSON tree of UI elements.",
    parameters: {
      type: "object",
      properties: {
        filter: {
          type: "string",
          description: "Optional keyword to filter element names or roles",
        },
        limit: {
          type: "number",
          description: "Maximum number of elements to return (default: unlimited)",
        },
      },
    },
    async execute(arg1?: any, arg2?: any) {
      const params = extractParams(arg1, arg2);
      const bin = resolveBinary("computer-use-gateway", "COMPUTER_USE_GATEWAY_BIN");
      const args = ["--dump-tree"];
      const proc = spawnSync(bin, args, { encoding: "utf-8", timeout: 15000 });

      if (proc.error) {
        return {
          content: [{ type: "text", text: `Error inspecting desktop tree: ${proc.error.message}` }],
          isError: true,
        };
      }
      if (proc.status !== 0) {
        return {
          content: [{ type: "text", text: `Failed to dump tree (exit ${proc.status}): ${proc.stderr || proc.stdout}` }],
          isError: true,
        };
      }

      let output = proc.stdout || "{}";
      if (params.filter || params.limit) {
        try {
          const parsed = JSON.parse(output);
          let nodes = parsed.nodes || parsed.children || (Array.isArray(parsed) ? parsed : [parsed]);
          if (params.filter) {
            const kw = String(params.filter).toLowerCase();
            nodes = nodes.filter((n: any) =>
              (n.name && String(n.name).toLowerCase().includes(kw)) ||
              (n.role && String(n.role).toLowerCase().includes(kw)) ||
              (n.id && String(n.id).toLowerCase().includes(kw))
            );
          }
          if (typeof params.limit === "number" && params.limit > 0) {
            nodes = nodes.slice(0, params.limit);
          }
          output = JSON.stringify({ ...parsed, nodes }, null, 2);
        } catch {
          // If not JSON, leave as raw string
        }
      }

      return {
        content: [{ type: "text", text: output }],
        details: { tool: "desktop_inspect_tree" },
      };
    },
  },

  {
    name: "desktop_click_element",
    label: "Click Desktop Coordinates or Element",
    description: "Clicks specified screen coordinates (e.g. 640,480) or an element by its accessibility ID on Workspace 2.",
    parameters: {
      type: "object",
      properties: {
        coordinates: {
          type: "string",
          description: "Coordinates in X,Y format (e.g. '640,480')",
        },
        x: {
          type: "number",
          description: "X coordinate (pixels)",
        },
        y: {
          type: "number",
          description: "Y coordinate (pixels)",
        },
        element_id: {
          type: "string",
          description: "Accessibility ID or widget name to click",
        },
      },
    },
    async execute(arg1?: any, arg2?: any) {
      const params = extractParams(arg1, arg2);
      const bin = resolveBinary("computer-use-gateway", "COMPUTER_USE_GATEWAY_BIN");
      const args: string[] = [];

      if (params.element_id) {
        args.push("--click-element", String(params.element_id));
      } else if (params.coordinates) {
        args.push("--click", String(params.coordinates));
      } else if (params.x !== undefined && params.y !== undefined) {
        args.push("--click", `${params.x},${params.y}`);
      } else {
        return {
          content: [{ type: "text", text: "Error: must specify either 'coordinates' (X,Y), 'x' and 'y', or 'element_id'." }],
          isError: true,
        };
      }

      const proc = spawnSync(bin, args, { encoding: "utf-8", timeout: 10000 });
      if (proc.error) {
        return {
          content: [{ type: "text", text: `Error executing click: ${proc.error.message}` }],
          isError: true,
        };
      }
      return {
        content: [{ type: "text", text: proc.stdout || proc.stderr || "Click command dispatched." }],
        details: { status: proc.status, args },
      };
    },
  },

  {
    name: "desktop_type_text",
    label: "Type Text or Send Hotkey",
    description: "Types text string or sends hotkey combinations (e.g. 'Return', 'ctrl+c') to the focused window on Workspace 2.",
    parameters: {
      type: "object",
      properties: {
        text: {
          type: "string",
          description: "Text string to type into the focused window",
        },
        hotkey: {
          type: "string",
          description: "Hotkey combination to trigger (e.g. 'Return', 'ctrl+c', 'Super+F11')",
        },
      },
    },
    async execute(arg1?: any, arg2?: any) {
      const params = extractParams(arg1, arg2);
      const bin = resolveBinary("computer-use-gateway", "COMPUTER_USE_GATEWAY_BIN");
      const args: string[] = [];

      if (params.text) {
        args.push("--type", String(params.text));
      }
      if (params.hotkey) {
        args.push("--hotkey", String(params.hotkey));
      }

      if (args.length === 0) {
        return {
          content: [{ type: "text", text: "Error: must specify 'text' to type or 'hotkey' to press." }],
          isError: true,
        };
      }

      const proc = spawnSync(bin, args, { encoding: "utf-8", timeout: 10000 });
      if (proc.error) {
        return {
          content: [{ type: "text", text: `Error executing type/hotkey: ${proc.error.message}` }],
          isError: true,
        };
      }
      return {
        content: [{ type: "text", text: proc.stdout || proc.stderr || "Type/hotkey executed." }],
        details: { status: proc.status, args },
      };
    },
  },

  {
    name: "desktop_screenshot",
    label: "Take Desktop Screenshot",
    description: "Captures a screenshot of Workspace 2 (Ghost Workspace) to a file for visual inspection.",
    parameters: {
      type: "object",
      properties: {
        path: {
          type: "string",
          description: "Output file path for the screenshot (default: /tmp/ghost-screenshot.png)",
        },
      },
    },
    async execute(arg1?: any, arg2?: any) {
      const params = extractParams(arg1, arg2);
      const bin = resolveBinary("computer-use-gateway", "COMPUTER_USE_GATEWAY_BIN");
      const outPath = params.path ? String(params.path) : "/tmp/ghost-screenshot.png";
      const args = ["--screenshot", outPath];

      const proc = spawnSync(bin, args, { encoding: "utf-8", timeout: 15000 });
      if (proc.error) {
        return {
          content: [{ type: "text", text: `Error capturing screenshot: ${proc.error.message}` }],
          isError: true,
        };
      }
      return {
        content: [{ type: "text", text: proc.stdout || `Screenshot captured successfully to ${outPath}` }],
        details: { path: outPath, status: proc.status },
      };
    },
  },

  {
    name: "desktop_ghost_switch",
    label: "Switch or Inspect Ghost Workspace",
    description: "Manages or switches to Workspace 2 (Ghost Workspace) for background agent task isolation.",
    parameters: {
      type: "object",
      properties: {
        action: {
          type: "string",
          description: "Action to perform: 'switch' (default), 'status', 'ensure', or 'list'",
        },
        workspace_index: {
          type: "number",
          description: "Target workspace index (0 for Workspace 1, 1 for Ghost Workspace 2, default: 1)",
        },
      },
    },
    async execute(arg1?: any, arg2?: any) {
      const params = extractParams(arg1, arg2);
      const bin = resolveBinary("ghost-workspace-helper", "GHOST_WORKSPACE_HELPER_BIN");
      const action = params.action || "status";
      const args = [action];
      if (action === "switch" || action === "move") {
        args.push(String(params.workspace_index ?? 1));
      }
      args.push("--json");

      const proc = spawnSync(bin, args, { encoding: "utf-8", timeout: 10000 });
      if (proc.error) {
        return {
          content: [{ type: "text", text: `Error running ghost-workspace-helper: ${proc.error.message}` }],
          isError: true,
        };
      }
      return {
        content: [{ type: "text", text: proc.stdout || proc.stderr || `ghost-workspace-helper ${action} executed.` }],
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
if (process.argv[1] && (process.argv[1] === fileURLToPath(import.meta.url) || process.argv[1].includes("skill-computer-use"))) {
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
