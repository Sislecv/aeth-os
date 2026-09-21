#!/usr/bin/env python3
"""
Unit and Integration Tests for AgenticOS Terminal Companion (Task 6)
Verifies:
1. Zellij 65:35 Companion Layout (agentic.kdl) syntax and structure.
2. Shell Integration Hooks (shell-hooks.sh) for Bash and Zsh, including exit code
   monitoring, non-blocking IPC event delivery, and Alt+A / Alt+B / Alt+C triggers.
3. Agentic Terminal Wrapper (agentic-terminal) CLI options, dry-run, status probing,
   and attach/launch behavior.
"""

import json
import os
import re
import socket
import stat
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
KDL_PATH = REPO_ROOT / "config/includes.chroot/etc/zellij/agentic.kdl"
SHELL_HOOKS_PATH = REPO_ROOT / "config/includes.chroot/etc/agentic/shell-hooks.sh"
TERMINAL_PATH = REPO_ROOT / "config/includes.chroot/usr/local/bin/agentic-terminal"
AETH_TERMINAL_PATH = REPO_ROOT / "config/includes.chroot/usr/local/bin/aeth-terminal"


class TestZellijLayout(unittest.TestCase):
    """Test suite for Zellij 65:35 companion layout configuration (agentic.kdl)."""

    def setUp(self):
        self.assertTrue(KDL_PATH.exists(), f"Layout file not found at {KDL_PATH}")
        with open(KDL_PATH, "r", encoding="utf-8") as f:
            self.content = f.read()

    def test_kdl_file_exists_and_readable(self):
        self.assertTrue(KDL_PATH.is_file())
        self.assertGreater(len(self.content), 50)

    def test_kdl_syntax_bracket_balance(self):
        """Verify KDL curly brace balancing and string quotation closure."""
        open_braces = self.content.count("{")
        close_braces = self.content.count("}")
        self.assertEqual(
            open_braces, close_braces,
            f"Unbalanced braces in {KDL_PATH}: {open_braces} open vs {close_braces} close"
        )
        self.assertGreater(open_braces, 2, "Expected multiple structured blocks in layout")

    def test_kdl_pane_splits_proportions(self):
        """Verify vertical split with 65% shell pane and 35% companion pane."""
        self.assertIn('split_direction="vertical"', self.content)
        self.assertIn('size="65%"', self.content)
        self.assertIn('size="35%"', self.content)

    def test_kdl_left_pane_focus(self):
        """Verify left 65% pane has focus=true."""
        # Find block with 65% size
        match_65 = re.search(r'pane[^}]*size="65%"[^}]*', self.content)
        self.assertIsNotNone(match_65, "Expected pane with size 65%")
        self.assertIn("focus=true", match_65.group(0))

    def test_kdl_pi_agent_fallback(self):
        """Verify right 35% pane runs pi with graceful fallback to bash."""
        match_35 = re.search(r'pane[^}]*size="35%"[^}]*', self.content)
        self.assertIsNotNone(match_35, "Expected pane with size 35%")
        pane_block = match_35.group(0)
        self.assertIn("command=", pane_block)
        # Check command contains pi check and fallback
        self.assertIn("command -v pi", self.content)
        self.assertIn("exec pi", self.content)
        self.assertIn("bash", self.content)

    def test_kdl_status_bar_shortcuts(self):
        """Verify bottom status bar displays shortcut hints: [Alt+A], [Alt+B], [Alt+C], [F5]."""
        self.assertIn("[Alt+A: Send Command]", self.content)
        self.assertIn("[Alt+B: Send Logs]", self.content)
        self.assertIn("[Alt+C: Ghost Computer Use]", self.content)
        self.assertIn("[F5: Voice Input]", self.content)

    def test_kdl_tab_bar_plugin(self):
        """Verify top tab bar plugin is included."""
        self.assertIn('plugin location="zellij:tab-bar"', self.content)


class TestShellHooks(unittest.TestCase):
    """Test suite for shell integration hooks (shell-hooks.sh)."""

    def setUp(self):
        self.assertTrue(SHELL_HOOKS_PATH.exists(), f"Shell hooks file not found at {SHELL_HOOKS_PATH}")

    def test_bash_syntax_check(self):
        """Run 'bash -n' on shell-hooks.sh to verify syntax correctness."""
        res = subprocess.run(
            ["bash", "-n", str(SHELL_HOOKS_PATH)],
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0, f"Bash syntax check failed:\n{res.stderr}")

    def test_sourcing_in_bash(self):
        """Verify sourcing the script in clean Bash subshell succeeds without error."""
        cmd = f"source {SHELL_HOOKS_PATH}"
        res = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0, f"Sourcing shell-hooks.sh failed:\n{res.stderr}")
        self.assertEqual(res.stderr.strip(), "")

    def test_exported_functions(self):
        """Verify that shell-hooks defines all required interactive functions."""
        funcs = [
            "agentic_send_command",
            "agentic_send_logs",
            "agentic_call_computer_use",
            "agentic_status",
            "_agentic_get_sock",
            "_agentic_on_command_complete",
        ]
        test_script = f"source {SHELL_HOOKS_PATH} && " + " && ".join([f"type {f} >/dev/null" for f in funcs])
        res = subprocess.run(["bash", "-c", test_script], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Required functions not all defined:\n{res.stderr}")

    def test_bash_prompt_command_and_debug_trap(self):
        """Verify PROMPT_COMMAND hook and DEBUG trap configuration for Bash."""
        with open(SHELL_HOOKS_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("PROMPT_COMMAND", content)
        self.assertIn("_agentic_bash_prompt_command", content)
        self.assertIn("DEBUG", content)
        self.assertIn("BASH_VERSION", content)

    def test_zsh_hook_and_zle_support(self):
        """Verify support for Zsh precmd, preexec, add-zsh-hook, and ZLE keybindings."""
        with open(SHELL_HOOKS_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("ZSH_VERSION", content)
        self.assertIn("add-zsh-hook", content)
        self.assertIn("precmd", content)
        self.assertIn("preexec", content)
        self.assertIn("zle -N", content)
        self.assertIn("bindkey", content)

    def test_keybindings_configured(self):
        """Verify Alt+A, Alt+B, Alt+C keybindings in Readline and ZLE."""
        with open(SHELL_HOOKS_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        # Readline bindings
        self.assertIn(r"\ea", content)
        self.assertIn(r"\eb", content)
        self.assertIn(r"\ec", content)
        # Zsh bindings
        self.assertIn(r"^[a", content)
        self.assertIn(r"^[b", content)
        self.assertIn(r"^[c", content)

    def test_non_blocking_on_missing_socket(self):
        """Verify hook actions complete immediately (< 100ms) when socket does not exist."""
        script = f"""
        source {SHELL_HOOKS_PATH}
        agentic_send_command "test command"
        agentic_send_logs 10
        agentic_call_computer_use "test task"
        _agentic_on_command_complete 1 "false"
        """
        start = time.time()
        res = subprocess.run(
            ["bash", "-c", script],
            env={**os.environ, "AGENTIC_SOCK": "/tmp/nonexistent-agentic-test.sock"},
            capture_output=True,
            text=True
        )
        elapsed = time.time() - start
        self.assertEqual(res.returncode, 0)
        self.assertLess(elapsed, 0.2, f"Execution took too long: {elapsed:.3f}s")
        self.assertEqual(res.stderr.strip(), "")

    def test_socket_event_on_nonzero_exit(self):
        """Verify that a non-zero exit code emits command_failed event with diagnosis type."""
        with tempfile.TemporaryDirectory() as td:
            sock_path = os.path.join(td, "test-agentic.sock")
            received = []

            def srv():
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.bind(sock_path)
                s.listen(1)
                conn, _ = s.accept()
                data = conn.recv(4096)
                if data:
                    received.append(json.loads(data.decode("utf-8")))
                conn.close()
                s.close()

            t = threading.Thread(target=srv, daemon=True)
            t.start()

            script = f"""
            source {SHELL_HOOKS_PATH}
            _agentic_on_command_complete 127 "apt-get update"
            """
            res = subprocess.run(
                ["bash", "-c", script],
                env={**os.environ, "AGENTIC_SOCK": sock_path, "AGENTIC_SYNC_SEND": "1"},
                capture_output=True,
                text=True
            )
            self.assertEqual(res.returncode, 0)
            t.join(timeout=2)

            self.assertEqual(len(received), 1)
            payload = received[0]
            self.assertEqual(payload.get("event"), "command_failed")
            self.assertEqual(payload.get("type"), "error_diagnosis")
            self.assertEqual(payload.get("command"), "apt-get update")
            self.assertEqual(payload.get("exit_code"), 127)
            self.assertIn("timestamp", payload)
            self.assertIn("cwd", payload)

    def test_bash_debug_trap_does_not_capture_prompt_command(self):
        """Verify that a failing command in Bash reports the actual command and not _agentic_bash_prompt_command."""
        with tempfile.TemporaryDirectory() as td:
            sock_path = os.path.join(td, "test-agentic.sock")
            received = []

            def srv():
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.bind(sock_path)
                s.listen(1)
                conn, _ = s.accept()
                data = conn.recv(4096)
                if data:
                    received.append(json.loads(data.decode("utf-8")))
                conn.close()
                s.close()

            t = threading.Thread(target=srv, daemon=True)
            t.start()

            script = f"""
            source {SHELL_HOOKS_PATH}
            failed_custom_command_123 2>/dev/null
            _agentic_bash_prompt_command
            """
            res = subprocess.run(
                ["bash", "-c", script],
                env={**os.environ, "AGENTIC_SOCK": sock_path, "AGENTIC_SYNC_SEND": "1"},
                capture_output=True,
                text=True
            )
            self.assertEqual(res.returncode, 127)
            t.join(timeout=2)

            self.assertEqual(len(received), 1)
            payload = received[0]
            self.assertEqual(payload.get("event"), "command_failed")
            self.assertNotEqual(payload.get("command"), "_agentic_bash_prompt_command")
            self.assertIn("failed_custom_command_123", payload.get("command", ""))
            self.assertEqual(payload.get("exit_code"), 127)

    def test_send_command_alt_a_payload(self):
        """Verify Alt+A (agentic_send_command) sends user_command_submit event."""
        with tempfile.TemporaryDirectory() as td:
            sock_path = os.path.join(td, "test-agentic.sock")
            received = []

            def srv():
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.bind(sock_path)
                s.listen(1)
                conn, _ = s.accept()
                data = conn.recv(4096)
                if data:
                    received.append(json.loads(data.decode("utf-8")))
                conn.close()
                s.close()

            t = threading.Thread(target=srv, daemon=True)
            t.start()

            script = f"""
            source {SHELL_HOOKS_PATH}
            agentic_send_command "pytest -v"
            """
            res = subprocess.run(
                ["bash", "-c", script],
                env={**os.environ, "AGENTIC_SOCK": sock_path, "AGENTIC_SYNC_SEND": "1"},
                capture_output=True,
                text=True
            )
            self.assertEqual(res.returncode, 0)
            t.join(timeout=2)

            self.assertEqual(len(received), 1)
            payload = received[0]
            self.assertEqual(payload.get("event"), "user_command_submit")
            self.assertEqual(payload.get("action"), "send_command")
            self.assertEqual(payload.get("command"), "pytest -v")

    def test_send_logs_alt_b_payload(self):
        """Verify Alt+B (agentic_send_logs) sends terminal_logs event with lines parameter."""
        with tempfile.TemporaryDirectory() as td:
            sock_path = os.path.join(td, "test-agentic.sock")
            received = []

            def srv():
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.bind(sock_path)
                s.listen(1)
                conn, _ = s.accept()
                data = conn.recv(4096)
                if data:
                    received.append(json.loads(data.decode("utf-8")))
                conn.close()
                s.close()

            t = threading.Thread(target=srv, daemon=True)
            t.start()

            script = f"""
            source {SHELL_HOOKS_PATH}
            agentic_send_logs 30
            """
            res = subprocess.run(
                ["bash", "-c", script],
                env={**os.environ, "AGENTIC_SOCK": sock_path, "AGENTIC_SYNC_SEND": "1"},
                capture_output=True,
                text=True
            )
            self.assertEqual(res.returncode, 0)
            t.join(timeout=2)

            self.assertEqual(len(received), 1)
            payload = received[0]
            self.assertEqual(payload.get("event"), "terminal_logs")
            self.assertEqual(payload.get("action"), "send_logs")
            self.assertEqual(payload.get("lines"), 30)

    def test_call_computer_use_alt_c_payload(self):
        """Verify Alt+C (agentic_call_computer_use) sends ghost_computer_use event."""
        with tempfile.TemporaryDirectory() as td:
            sock_path = os.path.join(td, "test-agentic.sock")
            received = []

            def srv():
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.bind(sock_path)
                s.listen(1)
                conn, _ = s.accept()
                data = conn.recv(4096)
                if data:
                    received.append(json.loads(data.decode("utf-8")))
                conn.close()
                s.close()

            t = threading.Thread(target=srv, daemon=True)
            t.start()

            script = f"""
            source {SHELL_HOOKS_PATH}
            agentic_call_computer_use "Solve CAPTCHA challenge"
            """
            res = subprocess.run(
                ["bash", "-c", script],
                env={**os.environ, "AGENTIC_SOCK": sock_path, "AGENTIC_SYNC_SEND": "1"},
                capture_output=True,
                text=True
            )
            self.assertEqual(res.returncode, 0)
            t.join(timeout=2)

            self.assertEqual(len(received), 1)
            payload = received[0]
            self.assertEqual(payload.get("event"), "ghost_computer_use")
            self.assertEqual(payload.get("action"), "call_computer_use")
            self.assertEqual(payload.get("task"), "Solve CAPTCHA challenge")


class TestAgenticTerminal(unittest.TestCase):
    """Test suite for agentic-terminal launcher wrapper."""

    def setUp(self):
        self.assertTrue(TERMINAL_PATH.exists(), f"Binary not found at {TERMINAL_PATH}")

    def test_agentic_terminal_exists_and_executable(self):
        """Verify aeth-terminal and alias exist and have executable bit set."""
        self.assertTrue(AETH_TERMINAL_PATH.is_file(), f"Missing aeth-terminal: {AETH_TERMINAL_PATH}")
        self.assertTrue(os.access(AETH_TERMINAL_PATH, os.X_OK), "aeth-terminal must be executable")
        self.assertTrue(TERMINAL_PATH.is_symlink() or TERMINAL_PATH.is_file(), "agentic-terminal alias must exist")
        self.assertTrue(os.access(TERMINAL_PATH, os.X_OK), "agentic-terminal alias must be executable")

    def test_bash_syntax(self):
        """Verify bash -n passes cleanly on aeth-terminal."""
        res = subprocess.run(["bash", "-n", str(AETH_TERMINAL_PATH)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Syntax error in aeth-terminal:\n{res.stderr}")

    def test_help_flag(self):
        """Verify --help and -h flags display usage instructions and exit with 0."""
        for flag in ["--help", "-h"]:
            res = subprocess.run([str(TERMINAL_PATH), flag], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0)
            self.assertIn("Usage:", res.stdout)
            self.assertIn("terminal", res.stdout)
            self.assertIn("--dry-run", res.stdout)
            self.assertIn("--status", res.stdout)
            self.assertIn("[Alt+A:", res.stdout)

    def test_version_flag(self):
        """Verify --version and -v flags return version and exit with 0."""
        for flag in ["--version", "-v"]:
            res = subprocess.run([str(TERMINAL_PATH), flag], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0)
            self.assertIn("1.0.0", res.stdout)
            self.assertTrue("Aeth OS" in res.stdout or "AgenticOS" in res.stdout)

    def test_dry_run_flag(self):
        """Verify --dry-run returns code 0 and indicates planned invocation."""
        res = subprocess.run([str(TERMINAL_PATH), "--dry-run"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("[dry-run]", res.stdout)
        self.assertIn("agentic", res.stdout)
        self.assertIn("agentic.kdl", res.stdout)

    def test_dry_run_json_output(self):
        """Verify --dry-run --json returns valid JSON describing planned launch."""
        res = subprocess.run([str(TERMINAL_PATH), "--dry-run", "--json"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout.strip())
        self.assertTrue(data.get("dry_run"))
        self.assertEqual(data.get("session"), "agentic")
        self.assertIn("agentic.kdl", data.get("layout"))
        self.assertIn("command", data)

    def test_dry_run_custom_session_and_layout(self):
        """Verify custom --session and --layout flags are respected."""
        custom_layout = "/tmp/my-custom-layout.kdl"
        res = subprocess.run(
            [str(TERMINAL_PATH), "--session", "custom-session", "--layout", custom_layout, "--dry-run", "--json"],
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout.strip())
        self.assertEqual(data.get("session"), "custom-session")
        self.assertEqual(data.get("layout"), custom_layout)
        self.assertIn("custom-session", data.get("command"))

    def test_status_when_not_running(self):
        """Verify --status returns exit code 1 when session is not active."""
        res = subprocess.run([str(TERMINAL_PATH), "--status"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 1)
        self.assertIn("not running", res.stdout)

    def test_status_json_when_not_running(self):
        """Verify --status --json outputs valid JSON and exit code 1 when not active."""
        res = subprocess.run([str(TERMINAL_PATH), "--status", "--json"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 1)
        data = json.loads(res.stdout.strip())
        self.assertEqual(data.get("session"), "agentic")
        self.assertFalse(data.get("running"))
        self.assertEqual(data.get("status"), "stopped")

    def test_mock_zellij_session_detection_and_attach(self):
        """Test attach behavior when zellij reports active session."""
        with tempfile.TemporaryDirectory() as td:
            mock_zellij = os.path.join(td, "zellij")
            log_file = os.path.join(td, "zellij.log")
            with open(mock_zellij, "w", encoding="utf-8") as f:
                f.write(f"""#!/bin/sh
echo "$@" >> "{log_file}"
if [ "$1" = "list-sessions" ]; then
    echo "agentic [Created 10m ago] (ATTACHED)"
    exit 0
fi
exit 0
""")
            os.chmod(mock_zellij, 0o755)

            new_env = {**os.environ, "PATH": f"{td}:{os.environ.get('PATH', '')}"}

            # Test --status detects active session
            res_status = subprocess.run(
                [str(TERMINAL_PATH), "--status"],
                env=new_env,
                capture_output=True,
                text=True
            )
            self.assertEqual(res_status.returncode, 0)
            self.assertIn("is running", res_status.stdout)

            # Test --status --json reports running=true
            res_status_json = subprocess.run(
                [str(TERMINAL_PATH), "--status", "--json"],
                env=new_env,
                capture_output=True,
                text=True
            )
            self.assertEqual(res_status_json.returncode, 0)
            data = json.loads(res_status_json.stdout.strip())
            self.assertTrue(data.get("running"))
            self.assertEqual(data.get("status"), "running")

            # Test --dry-run plans 'attach' action
            res_dry = subprocess.run(
                [str(TERMINAL_PATH), "--dry-run", "--json"],
                env=new_env,
                capture_output=True,
                text=True
            )
            self.assertEqual(res_dry.returncode, 0)
            data_dry = json.loads(res_dry.stdout.strip())
            self.assertEqual(data_dry.get("action"), "attach")
            self.assertIn("attach agentic", data_dry.get("command"))

            # Test real invocation executes attach
            res_exec = subprocess.run(
                [str(TERMINAL_PATH)],
                env=new_env,
                capture_output=True,
                text=True
            )
            self.assertEqual(res_exec.returncode, 0)
            with open(log_file, "r") as f:
                invocations = f.read()
            self.assertIn("attach agentic", invocations)

    def test_mock_zellij_new_session_launch(self):
        """Test launch behavior when zellij has no existing session."""
        with tempfile.TemporaryDirectory() as td:
            mock_zellij = os.path.join(td, "zellij")
            log_file = os.path.join(td, "zellij.log")
            with open(mock_zellij, "w", encoding="utf-8") as f:
                f.write(f"""#!/bin/sh
echo "$@" >> "{log_file}"
if [ "$1" = "list-sessions" ]; then
    # No sessions running
    exit 1
fi
exit 0
""")
            os.chmod(mock_zellij, 0o755)

            new_env = {**os.environ, "PATH": f"{td}:{os.environ.get('PATH', '')}"}

            # Test --dry-run plans 'launch' action
            res_dry = subprocess.run(
                [str(TERMINAL_PATH), "--dry-run", "--json"],
                env=new_env,
                capture_output=True,
                text=True
            )
            self.assertEqual(res_dry.returncode, 0)
            data_dry = json.loads(res_dry.stdout.strip())
            self.assertEqual(data_dry.get("action"), "launch")
            self.assertIn("--session agentic", data_dry.get("command"))

            # Test real invocation executes session launch
            res_exec = subprocess.run(
                [str(TERMINAL_PATH)],
                env=new_env,
                capture_output=True,
                text=True
            )
            self.assertEqual(res_exec.returncode, 0)
            with open(log_file, "r") as f:
                invocations = f.read()
            self.assertIn("--session agentic --layout", invocations)

    def test_force_new_session(self):
        """Test --new forces new session launch even if session is listed."""
        with tempfile.TemporaryDirectory() as td:
            mock_zellij = os.path.join(td, "zellij")
            with open(mock_zellij, "w", encoding="utf-8") as f:
                f.write("""#!/bin/sh
if [ "$1" = "list-sessions" ]; then
    echo "agentic [Created 10m ago]"
    exit 0
fi
exit 0
""")
            os.chmod(mock_zellij, 0o755)

            new_env = {**os.environ, "PATH": f"{td}:{os.environ.get('PATH', '')}"}

            res = subprocess.run(
                [str(TERMINAL_PATH), "--new", "--dry-run", "--json"],
                env=new_env,
                capture_output=True,
                text=True
            )
            self.assertEqual(res.returncode, 0)
            data = json.loads(res.stdout.strip())
            self.assertEqual(data.get("action"), "launch")


if __name__ == "__main__":
    unittest.main()
