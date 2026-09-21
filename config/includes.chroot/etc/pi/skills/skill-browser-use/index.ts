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
    name: "browser_open",
    label: "Open Browser and Navigate",
    description: "Launches dedicated Chromium (headless or headed in Ghost Workspace) and navigates to the specified URL.",
    parameters: {
      type: "object",
      properties: {
        url: {
          type: "string",
          description: "Target URL to open (e.g. 'https://github.com')",
        },
        headed: {
          type: "boolean",
          description: "If true, runs in visible Ghost Workspace (Workspace 2); if false, runs headless (default: false)",
        },
        port: {
          type: "number",
          description: "Remote debugging CDP port (default: 9222)",
        },
      },
      required: ["url"],
    },
    async execute(arg1?: any, arg2?: any) {
      const params = extractParams(arg1, arg2);
      if (!params.url) {
        return {
          content: [{ type: "text", text: "Error: 'url' parameter is required." }],
          isError: true,
        };
      }

      const launcherBin = resolveBinary("agentic-browser-launcher", "AGENTIC_BROWSER_LAUNCHER_BIN");
      const agentBrowserBin = resolveBinary("agent-browser", "AGENT_BROWSER_BIN");

      // 1. Check if browser is running via launcher status
      const statusProc = spawnSync(launcherBin, ["--status"], { encoding: "utf-8", timeout: 5000 });
      const isRunning = statusProc.status === 0;

      if (!isRunning) {
        const launchArgs = [params.headed ? "--headed" : "--headless"];
        if (params.port) {
          launchArgs.push("--port", String(params.port));
        }
        launchArgs.push(params.url);
        const launchProc = spawnSync(launcherBin, launchArgs, { encoding: "utf-8", timeout: 10000 });
        if (launchProc.error) {
          return {
            content: [{ type: "text", text: `Error launching browser: ${launchProc.error.message}` }],
            isError: true,
          };
        }
      }

      // 2. Instruct agent-browser to navigate to URL
      const navProc = spawnSync(agentBrowserBin, ["open", params.url], { encoding: "utf-8", timeout: 15000 });
      let output = navProc.stdout || navProc.stderr || `Navigated to ${params.url}`;
      if (navProc.error) {
        output = `Browser launched with URL ${params.url} (agent-browser: ${navProc.error.message})`;
      }

      return {
        content: [{ type: "text", text: output }],
        details: { url: params.url, headed: !!params.headed },
      };
    },
  },

  {
    name: "browser_snapshot",
    label: "Capture Page Accessibility Snapshot",
    description: "Takes an interactive accessibility snapshot of the current web page, returning @eN numbered interactive elements.",
    parameters: {
      type: "object",
      properties: {
        interactive: {
          type: "boolean",
          description: "If true, filters to only interactive elements (@e1, @e2, etc.) (default: true)",
        },
      },
    },
    async execute(arg1?: any, arg2?: any) {
      const params = extractParams(arg1, arg2);
      const agentBrowserBin = resolveBinary("agent-browser", "AGENT_BROWSER_BIN");
      const args = ["snapshot"];
      if (params.interactive !== false) {
        args.push("-i");
      }

      const proc = spawnSync(agentBrowserBin, args, { encoding: "utf-8", timeout: 15000 });
      if (proc.error) {
        return {
          content: [{ type: "text", text: `Error taking snapshot: ${proc.error.message}` }],
          isError: true,
        };
      }
      return {
        content: [{ type: "text", text: proc.stdout || proc.stderr || "No snapshot content returned." }],
        details: { interactive: params.interactive !== false, status: proc.status },
      };
    },
  },

  {
    name: "browser_click",
    label: "Click Browser Element",
    description: "Clicks an interactive element by reference (@eN) or selector on the active web page.",
    parameters: {
      type: "object",
      properties: {
        target: {
          type: "string",
          description: "Element reference (e.g. '@e1', '@e2') or CSS/XPath selector",
        },
      },
      required: ["target"],
    },
    async execute(arg1?: any, arg2?: any) {
      const params = extractParams(arg1, arg2);
      if (!params.target) {
        return {
          content: [{ type: "text", text: "Error: 'target' parameter is required (e.g. '@e1')." }],
          isError: true,
        };
      }

      const agentBrowserBin = resolveBinary("agent-browser", "AGENT_BROWSER_BIN");
      const proc = spawnSync(agentBrowserBin, ["click", String(params.target)], { encoding: "utf-8", timeout: 15000 });
      if (proc.error) {
        return {
          content: [{ type: "text", text: `Error clicking element ${params.target}: ${proc.error.message}` }],
          isError: true,
        };
      }
      return {
        content: [{ type: "text", text: proc.stdout || proc.stderr || `Clicked ${params.target}` }],
        details: { target: params.target, status: proc.status },
      };
    },
  },

  {
    name: "browser_fill",
    label: "Fill Input Element",
    description: "Fills an input, textarea, or contenteditable field with specified text.",
    parameters: {
      type: "object",
      properties: {
        target: {
          type: "string",
          description: "Element reference (e.g. '@e1') or selector",
        },
        text: {
          type: "string",
          description: "Text value to type into the element",
        },
      },
      required: ["target", "text"],
    },
    async execute(arg1?: any, arg2?: any) {
      const params = extractParams(arg1, arg2);
      if (!params.target || params.text === undefined) {
        return {
          content: [{ type: "text", text: "Error: 'target' and 'text' parameters are required." }],
          isError: true,
        };
      }

      const agentBrowserBin = resolveBinary("agent-browser", "AGENT_BROWSER_BIN");
      const proc = spawnSync(agentBrowserBin, ["fill", String(params.target), String(params.text)], { encoding: "utf-8", timeout: 15000 });
      if (proc.error) {
        return {
          content: [{ type: "text", text: `Error filling element ${params.target}: ${proc.error.message}` }],
          isError: true,
        };
      }
      return {
        content: [{ type: "text", text: proc.stdout || proc.stderr || `Filled ${params.target}` }],
        details: { target: params.target, status: proc.status },
      };
    },
  },

  {
    name: "browser_read_markdown",
    label: "Read Page as Markdown",
    description: "Converts current web page DOM into clean, structured Markdown for analysis.",
    parameters: {
      type: "object",
      properties: {
        selector: {
          type: "string",
          description: "Optional CSS selector to scope content extraction (default: 'body')",
        },
      },
    },
    async execute(arg1?: any, arg2?: any) {
      const params = extractParams(arg1, arg2);
      const agentBrowserBin = resolveBinary("agent-browser", "AGENT_BROWSER_BIN");
      const args = ["markdown"];
      if (params.selector) {
        args.push("--selector", String(params.selector));
      }

      const proc = spawnSync(agentBrowserBin, args, { encoding: "utf-8", timeout: 20000 });
      if (proc.error) {
        return {
          content: [{ type: "text", text: `Error reading page markdown: ${proc.error.message}` }],
          isError: true,
        };
      }
      return {
        content: [{ type: "text", text: proc.stdout || proc.stderr || "# Page Content\n(Empty content)" }],
        details: { selector: params.selector || "body", status: proc.status },
      };
    },
  },

  {
    name: "browser_reveal",
    label: "Reveal / Hide Browser Window",
    description: "Brings the headed browser window to Workspace 1 (User Workspace) for manual user login/CAPTCHA, or hides it back to Ghost Workspace 2.",
    parameters: {
      type: "object",
      properties: {
        action: {
          type: "string",
          description: "Action to perform: 'reveal' (Workspace 1) or 'hide' (Workspace 2) (default: 'reveal')",
        },
      },
    },
    async execute(arg1?: any, arg2?: any) {
      const params = extractParams(arg1, arg2);
      const launcherBin = resolveBinary("agentic-browser-launcher", "AGENTIC_BROWSER_LAUNCHER_BIN");
      const action = params.action === "hide" ? "--hide" : "--reveal";

      const proc = spawnSync(launcherBin, [action], { encoding: "utf-8", timeout: 10000 });
      if (proc.error) {
        return {
          content: [{ type: "text", text: `Error managing browser window: ${proc.error.message}` }],
          isError: true,
        };
      }
      return {
        content: [{ type: "text", text: proc.stdout || proc.stderr || `Browser window action ${action} executed.` }],
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
if (process.argv[1] && (process.argv[1] === fileURLToPath(import.meta.url) || process.argv[1].includes("skill-browser-use"))) {
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
