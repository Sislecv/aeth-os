---
name: skill-terminal-sync
description: Zellij terminal split-pane companion synchronization: reading left pane viewport logs and sending suggested commands.
---

# Terminal Sync Skill

Provides bi-directional companion integration between Pi Agent (right pane) and the user's interactive shell (left pane):
- `terminal_read_pane`: Read output lines from the user's terminal to analyze build output, error traces, or test results.
- `terminal_send_command`: Write suggested fix or next-step command into the user's terminal with optional immediate execution.
- `terminal_new_tab`: Create dedicated workspace tabs for background tasks.
