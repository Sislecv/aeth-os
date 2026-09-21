---
name: skill-agent-memory
description: Persistent cross-session and cross-reboot memory backed by SQLite, preserving preferences, troubleshooting knowledge, and project state.
---

# Agent Memory Skill

Provides persistent long-term storage across reboot and machine migration:
- `memory_store`: Save key-value entries with classification category and tags.
- `memory_query`: Search stored entries by keyword or tag.
- `memory_list`: View active memory entries.
- `memory_delete`: Remove obsolete memory records.
