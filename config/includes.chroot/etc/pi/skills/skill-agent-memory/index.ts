import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function getDatabasePath(): string {
  if (process.env.AGENTIC_MEMORY_DB) {
    return process.env.AGENTIC_MEMORY_DB;
  }
  const home = process.env.HOME || "/root";
  return path.join(home, ".config", "agentic", "memory.db");
}

let _dbInstance: DatabaseSync | null = null;

function getDb(): DatabaseSync {
  if (_dbInstance) {
    return _dbInstance;
  }
  const dbPath = getDatabasePath();
  const dir = path.dirname(dbPath);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true, mode: 0o755 });
  }

  const db = new DatabaseSync(dbPath);
  db.exec(`
    CREATE TABLE IF NOT EXISTS memories (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      key TEXT UNIQUE NOT NULL,
      value TEXT NOT NULL,
      tags TEXT DEFAULT '',
      category TEXT DEFAULT 'general',
      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_memories_key ON memories(key);
    CREATE INDEX IF NOT EXISTS idx_memories_tags ON memories(tags);
    CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
  `);
  _dbInstance = db;
  return db;
}

function normalizeTags(tags?: any): string {
  if (!tags) return "";
  if (Array.isArray(tags)) return tags.join(",").toLowerCase();
  return String(tags).toLowerCase();
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
    name: "memory_store",
    label: "Store Memory Entry",
    description: "Saves or updates a persistent memory entry with key, content value, tags, and category into SQLite long-term storage.",
    parameters: {
      type: "object",
      properties: {
        key: {
          type: "string",
          description: "Unique identifier or topic key for this memory (e.g. 'project_wifi_config', 'repo_build_cmd')",
        },
        value: {
          type: "string",
          description: "Detailed content or insight to remember across sessions",
        },
        tags: {
          type: "string",
          description: "Comma-separated tags or keywords (e.g. 'wifi,network' or 'dev,build')",
        },
        category: {
          type: "string",
          description: "Category classification (e.g. 'preference', 'snippet', 'bug_fix', default: 'general')",
        },
      },
      required: ["key", "value"],
    },
    async execute(arg1?: any, arg2?: any) {
      const params = extractParams(arg1, arg2);
      if (!params.key || params.value === undefined) {
        return {
          content: [{ type: "text", text: "Error: 'key' and 'value' parameters are required." }],
          isError: true,
        };
      }

      const key = String(params.key).trim();
      const value = String(params.value);
      const tags = normalizeTags(params.tags);
      const category = (params.category ? String(params.category).trim() : "general").toLowerCase();
      const now = new Date().toISOString();

      try {
        const db = getDb();
        const stmt = db.prepare(`
          INSERT INTO memories (key, value, tags, category, created_at, updated_at)
          VALUES (?, ?, ?, ?, ?, ?)
          ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            tags = excluded.tags,
            category = excluded.category,
            updated_at = excluded.updated_at
        `);
        stmt.run(key, value, tags, category, now, now);

        return {
          content: [{ type: "text", text: `Memory successfully stored for key '${key}' [category: ${category}, tags: ${tags || 'none'}].` }],
          details: { key, category, tags, updatedAt: now },
        };
      } catch (err: any) {
        return {
          content: [{ type: "text", text: `Failed to store memory: ${err.message}` }],
          isError: true,
        };
      }
    },
  },

  {
    name: "memory_query",
    label: "Query Memories by Keyword / Tag",
    description: "Searches persistent memories matching keyword, semantic tags, or category across cross-session memory.",
    parameters: {
      type: "object",
      properties: {
        query: {
          type: "string",
          description: "Search keyword matching in key, value, or tags",
        },
        category: {
          type: "string",
          description: "Optional category filter",
        },
        limit: {
          type: "number",
          description: "Maximum number of results to return (default: 10)",
        },
      },
      required: ["query"],
    },
    async execute(arg1?: any, arg2?: any) {
      const params = extractParams(arg1, arg2);
      if (!params.query) {
        return {
          content: [{ type: "text", text: "Error: 'query' parameter is required." }],
          isError: true,
        };
      }

      const queryPattern = `%${String(params.query).trim().toLowerCase()}%`;
      const limit = typeof params.limit === "number" && params.limit > 0 ? params.limit : 10;
      const category = params.category ? String(params.category).trim().toLowerCase() : null;

      try {
        const db = getDb();
        let rows: any[];
        if (category) {
          const stmt = db.prepare(`
            SELECT key, value, tags, category, updated_at
            FROM memories
            WHERE category = ? AND (LOWER(key) LIKE ? OR LOWER(value) LIKE ? OR LOWER(tags) LIKE ?)
            ORDER BY updated_at DESC
            LIMIT ?
          `);
          rows = stmt.all(category, queryPattern, queryPattern, queryPattern, limit);
        } else {
          const stmt = db.prepare(`
            SELECT key, value, tags, category, updated_at
            FROM memories
            WHERE LOWER(key) LIKE ? OR LOWER(value) LIKE ? OR LOWER(tags) LIKE ?
            ORDER BY updated_at DESC
            LIMIT ?
          `);
          rows = stmt.all(queryPattern, queryPattern, queryPattern, limit);
        }

        return {
          content: [{ type: "text", text: JSON.stringify(rows, null, 2) }],
          details: { count: rows.length, query: params.query },
        };
      } catch (err: any) {
        return {
          content: [{ type: "text", text: `Failed to query memory: ${err.message}` }],
          isError: true,
        };
      }
    },
  },

  {
    name: "memory_list",
    label: "List Saved Memories",
    description: "Lists stored memories, optionally filtered by tag or category.",
    parameters: {
      type: "object",
      properties: {
        category: {
          type: "string",
          description: "Optional category filter (e.g. 'preference', 'snippet')",
        },
        tag: {
          type: "string",
          description: "Optional tag filter keyword",
        },
        limit: {
          type: "number",
          description: "Maximum entries to return (default: 20)",
        },
      },
    },
    async execute(arg1?: any, arg2?: any) {
      const params = extractParams(arg1, arg2);
      const limit = typeof params.limit === "number" && params.limit > 0 ? params.limit : 20;
      const category = params.category ? String(params.category).trim().toLowerCase() : null;
      const tagPattern = params.tag ? `%${String(params.tag).trim().toLowerCase()}%` : null;

      try {
        const db = getDb();
        let rows: any[];

        if (category && tagPattern) {
          const stmt = db.prepare(`
            SELECT key, value, tags, category, updated_at
            FROM memories
            WHERE category = ? AND LOWER(tags) LIKE ?
            ORDER BY updated_at DESC
            LIMIT ?
          `);
          rows = stmt.all(category, tagPattern, limit);
        } else if (category) {
          const stmt = db.prepare(`
            SELECT key, value, tags, category, updated_at
            FROM memories
            WHERE category = ?
            ORDER BY updated_at DESC
            LIMIT ?
          `);
          rows = stmt.all(category, limit);
        } else if (tagPattern) {
          const stmt = db.prepare(`
            SELECT key, value, tags, category, updated_at
            FROM memories
            WHERE LOWER(tags) LIKE ?
            ORDER BY updated_at DESC
            LIMIT ?
          `);
          rows = stmt.all(tagPattern, limit);
        } else {
          const stmt = db.prepare(`
            SELECT key, value, tags, category, updated_at
            FROM memories
            ORDER BY updated_at DESC
            LIMIT ?
          `);
          rows = stmt.all(limit);
        }

        return {
          content: [{ type: "text", text: JSON.stringify(rows, null, 2) }],
          details: { count: rows.length },
        };
      } catch (err: any) {
        return {
          content: [{ type: "text", text: `Failed to list memory: ${err.message}` }],
          isError: true,
        };
      }
    },
  },

  {
    name: "memory_delete",
    label: "Delete Memory Entry",
    description: "Removes a memory entry by its key.",
    parameters: {
      type: "object",
      properties: {
        key: {
          type: "string",
          description: "Key of the memory entry to delete",
        },
      },
      required: ["key"],
    },
    async execute(arg1?: any, arg2?: any) {
      const params = extractParams(arg1, arg2);
      if (!params.key) {
        return {
          content: [{ type: "text", text: "Error: 'key' parameter is required." }],
          isError: true,
        };
      }

      const key = String(params.key).trim();
      try {
        const db = getDb();
        const stmt = db.prepare("DELETE FROM memories WHERE key = ?");
        const res = stmt.run(key);

        return {
          content: [{ type: "text", text: `Memory key '${key}' deleted (rows affected: ${res.changes}).` }],
          details: { key, changes: res.changes },
        };
      } catch (err: any) {
        return {
          content: [{ type: "text", text: `Failed to delete memory: ${err.message}` }],
          isError: true,
        };
      }
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
if (process.argv[1] && (process.argv[1] === fileURLToPath(import.meta.url) || process.argv[1].includes("skill-agent-memory"))) {
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
