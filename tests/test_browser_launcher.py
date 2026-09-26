#!/usr/bin/env python3
"""
Unit tests for AgenticOS Browser Use Stack:
- 0060-install-agent-browser.hook.chroot (syntax, execution, offline fallback)
- agentic-browser-launcher (argument parsing, headless/headed flags, status checks, reveal/hide)
- agent-browser command chain simulation (open, snapshot -i, click @eN)
"""

import os
import sys
import json
import time
import socket
import unittest
import tempfile
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_SCRIPT = REPO_ROOT / "config" / "hooks" / "live" / "0060-install-agent-browser.hook.chroot"
LAUNCHER_SCRIPT = REPO_ROOT / "config" / "includes.chroot" / "usr" / "local" / "bin" / "agentic-browser-launcher"


class TestFilePermissionsAndSyntax(unittest.TestCase):
    """Checks scripts existence, permissions, and bash syntax correctness."""

    def test_hook_script_exists_and_executable(self):
        self.assertTrue(HOOK_SCRIPT.is_file(), f"Missing hook script: {HOOK_SCRIPT}")
        self.assertTrue(os.access(HOOK_SCRIPT, os.X_OK), "Hook script must be executable (chmod +x)")

    def test_launcher_script_exists_and_executable(self):
        self.assertTrue(LAUNCHER_SCRIPT.is_file(), f"Missing launcher script: {LAUNCHER_SCRIPT}")
        self.assertTrue(os.access(LAUNCHER_SCRIPT, os.X_OK), "Launcher script must be executable (chmod +x)")

    def test_bash_syntax_hook_script(self):
        res = subprocess.run(["bash", "-n", str(HOOK_SCRIPT)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Bash syntax error in {HOOK_SCRIPT}:\n{res.stderr}")

    def test_bash_syntax_launcher_script(self):
        res = subprocess.run(["bash", "-n", str(LAUNCHER_SCRIPT)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Bash syntax error in {LAUNCHER_SCRIPT}:\n{res.stderr}")

    def test_hook_script_content_specifications(self):
        content = HOOK_SCRIPT.read_text()
        self.assertIn("npm install -g agent-browser", content)
        self.assertIn("agent-browser install --with-deps", content)
        self.assertIn("setup_offline_fallback", content)
        self.assertIn("set -euo pipefail", content)


class TestLauncherArgumentParsing(unittest.TestCase):
    """Tests argument parsing, flags, and dry-run execution of agentic-browser-launcher."""

    def run_launcher(self, *args, env=None):
        cmd_env = os.environ.copy()
        if env:
            cmd_env.update(env)
        return subprocess.run(
            [str(LAUNCHER_SCRIPT)] + list(args),
            capture_output=True,
            text=True,
            env=cmd_env,
        )

    def test_help_flags(self):
        for flag in ["--help", "-h"]:
            res = self.run_launcher(flag)
            self.assertEqual(res.returncode, 0)
            self.assertIn("agentic-browser-launcher", res.stdout)
            self.assertIn("--headless", res.stdout)
            self.assertIn("--headed", res.stdout)
            self.assertIn("--reveal", res.stdout)
            self.assertIn("--status", res.stdout)
            self.assertIn("--stop", res.stdout)
            self.assertIn("--port", res.stdout)
            self.assertIn("--profile", res.stdout)

    def test_unknown_option(self):
        res = self.run_launcher("--unknown-flag")
        self.assertEqual(res.returncode, 1)
        self.assertIn("Unknown option", res.stderr)

    def test_dry_run_headless_default(self):
        res = self.run_launcher("--dry-run")
        self.assertEqual(res.returncode, 0)
        out = res.stdout.strip()
        self.assertIn("--headless=new", out)
        self.assertIn("--remote-debugging-port=9222", out)
        self.assertIn("--remote-debugging-address=127.0.0.1", out)
        self.assertIn("--user-data-dir=", out)
        self.assertIn("about:blank", out)

    def test_dry_run_headed_mode(self):
        res = self.run_launcher("--dry-run", "--headed")
        self.assertEqual(res.returncode, 0)
        out = res.stdout.strip()
        self.assertNotIn("--headless=new", out)
        self.assertNotIn("--disable-gpu", out)
        self.assertIn("--window-size=1280,800", out)
        self.assertIn("--remote-debugging-port=9222", out)

    def test_dry_run_custom_port_and_profile(self):
        res = self.run_launcher(
            "--dry-run",
            "--port", "9555",
            "--profile", "/tmp/custom-profile",
            "https://agentic-os.local"
        )
        self.assertEqual(res.returncode, 0)
        out = res.stdout.strip()
        self.assertIn("--remote-debugging-port=9555", out)
        self.assertIn("--user-data-dir=/tmp/custom-profile", out)
        self.assertIn("https://agentic-os.local", out)

    def test_dry_run_json_output(self):
        res = self.run_launcher("--dry-run", "--json", "--port", "9888")
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertEqual(data.get("status"), "dry_run")
        self.assertEqual(data.get("mode"), "headless")
        self.assertEqual(data.get("port"), 9888)
        self.assertIn("--headless=new", data.get("command", ""))


class MockCDPHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/json/version":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = {
                "Browser": "Chrome/128.0.6613.119",
                "Protocol-Version": "1.3",
                "User-Agent": "Mozilla/5.0 AgenticOS",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/mock"
            }
            self.wfile.write(json.dumps(resp).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress HTTP logging during tests


class TestLauncherStatusAndStop(unittest.TestCase):
    """Tests status checking and stopping of browser instances."""

    def run_launcher(self, *args, env=None):
        cmd_env = os.environ.copy()
        if env:
            cmd_env.update(env)
        return subprocess.run(
            [str(LAUNCHER_SCRIPT)] + list(args),
            capture_output=True,
            text=True,
            env=cmd_env,
        )

    def test_status_when_stopped(self):
        # Using a high unassigned port
        test_port = "29221"
        res = self.run_launcher("--port", test_port, "--status")
        self.assertEqual(res.returncode, 1, "Status check should exit 1 when browser is stopped")
        data = json.loads(res.stdout)
        self.assertEqual(data.get("status"), "stopped")
        self.assertFalse(data.get("running"))
        self.assertFalse(data.get("cdp_ready"))
        self.assertEqual(data.get("port"), 29221)

    def test_stop_when_already_stopped(self):
        test_port = "29222"
        res = self.run_launcher("--port", test_port, "--stop")
        self.assertEqual(res.returncode, 0)
        self.assertIn("No running Chromium instance found", res.stderr + res.stdout)

    def test_stop_json_when_already_stopped(self):
        test_port = "29223"
        res = self.run_launcher("--port", test_port, "--stop", "--json")
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertEqual(data.get("status"), "ok")
        self.assertFalse(data.get("running"))

    def test_status_when_cdp_port_active(self):
        """Starts a temporary mock CDP server and tests status detection."""
        # Find free port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            free_port = s.getsockname()[1]

        server = HTTPServer(("127.0.0.1", free_port), MockCDPHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            res = self.run_launcher("--port", str(free_port), "--status")
            self.assertEqual(res.returncode, 0, "Status check must return 0 when CDP port is active")
            data = json.loads(res.stdout)
            self.assertEqual(data.get("status"), "running")
            self.assertTrue(data.get("running"))
            self.assertTrue(data.get("cdp_ready"))
            self.assertEqual(data.get("port"), free_port)
        finally:
            server.shutdown()
            server.server_close()


class TestLauncherRevealAndGhostWorkspace(unittest.TestCase):
    """Tests --reveal and --hide integration with ghost-workspace-helper."""

    def test_reveal_fails_when_not_running(self):
        test_port = "29224"
        res = subprocess.run(
            [str(LAUNCHER_SCRIPT), "--port", test_port, "--reveal", "--json"],
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 1)
        data = json.loads(res.stdout)
        self.assertEqual(data.get("status"), "error")

    def test_reveal_invokes_ghost_helper(self):
        """Spawns a mock process, creates a mock ghost-workspace-helper, and verifies reveal behavior."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            helper_log = tmp_path / "helper_calls.log"

            # Create mock ghost-workspace-helper
            mock_helper = tmp_path / "ghost-workspace-helper"
            mock_helper.write_text(f"""#!/bin/sh
echo "$@" >> "{helper_log}"
exit 0
""")
            mock_helper.chmod(0o755)

            # Start a dummy background process
            dummy_proc = subprocess.Popen(["sleep", "30"])
            dummy_pid = dummy_proc.pid

            test_port = "29225"
            pid_file = Path(f"/tmp/agentic-browser-{test_port}.pid")
            pid_file.write_text(str(dummy_pid))
            xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
            xdg_pid_file = None
            if xdg_runtime and os.path.isdir(xdg_runtime):
                xdg_pid_file = Path(xdg_runtime) / f"agentic-browser-{test_port}.pid"
                xdg_pid_file.write_text(str(dummy_pid))

            custom_env = os.environ.copy()
            custom_env["PATH"] = f"{tmpdir}:{custom_env.get('PATH', '')}"

            try:
                res = subprocess.run(
                    [str(LAUNCHER_SCRIPT), "--port", test_port, "--reveal", "--json"],
                    capture_output=True,
                    text=True,
                    env=custom_env
                )
                self.assertEqual(res.returncode, 0)
                data = json.loads(res.stdout)
                self.assertEqual(data.get("status"), "ok")
                self.assertEqual(data.get("pid"), dummy_pid)
                self.assertEqual(data.get("target_workspace"), 0)
                self.assertTrue(data.get("helper_invoked"))

                # Verify mock helper recorded calls to move window to workspace 0 and switch to 0
                calls = helper_log.read_text()
                self.assertIn(f"move {dummy_pid} 0", calls)
                self.assertIn("switch 0", calls)

                # Test --hide moves back to workspace 1
                res_hide = subprocess.run(
                    [str(LAUNCHER_SCRIPT), "--port", test_port, "--hide", "--json"],
                    capture_output=True,
                    text=True,
                    env=custom_env
                )
                self.assertEqual(res_hide.returncode, 0)
                hide_data = json.loads(res_hide.stdout)
                self.assertEqual(hide_data.get("status"), "ok")
                self.assertEqual(hide_data.get("target_workspace"), 1)

                calls_after = helper_log.read_text()
                self.assertIn(f"move {dummy_pid} 1", calls_after)

            finally:
                dummy_proc.terminate()
                dummy_proc.wait()
                if pid_file.exists():
                    pid_file.unlink()
                if xdg_pid_file and xdg_pid_file.exists():
                    xdg_pid_file.unlink()


class TestAgentBrowserCommandChain(unittest.TestCase):
    """
    Simulates and validates agent-browser command chain interactions:
    1. agent-browser open <url>
    2. agent-browser snapshot -i (produces compact a11y tree with @eN refs)
    3. agent-browser click @eN (acts on referenced element)
    """

    def test_mock_command_chain_dispatch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            chain_log = tmp_path / "command_chain.log"

            # Create mock agent-browser script
            mock_ab = tmp_path / "agent-browser"
            mock_ab.write_text(f"""#!/bin/sh
echo "$@" >> "{chain_log}"
if [ "$1" = "open" ]; then
    echo "Navigated to $2"
    exit 0
elif [ "$1" = "snapshot" ] && [ "$2" = "-i" ]; then
    cat << 'EOF'
Page: AgenticOS Dashboard
URL: https://agentic-os.local/dashboard

@e1 [heading] "AgenticOS Control Center"
@e2 [button] "Authenticate"
@e3 [input type="text"] placeholder="Username"
@e4 [link] "Docs"
EOF
    exit 0
elif [ "$1" = "click" ]; then
    echo "Clicked element $2"
    exit 0
fi
exit 1
""")
            mock_ab.chmod(0o755)

            env = os.environ.copy()
            env["PATH"] = f"{tmpdir}:{env.get('PATH', '')}"

            # 1. Step: open
            open_res = subprocess.run(["agent-browser", "open", "https://agentic-os.local/dashboard"],
                                      capture_output=True, text=True, env=env)
            self.assertEqual(open_res.returncode, 0)
            self.assertIn("Navigated to", open_res.stdout)

            # 2. Step: snapshot -i
            snap_res = subprocess.run(["agent-browser", "snapshot", "-i"],
                                      capture_output=True, text=True, env=env)
            self.assertEqual(snap_res.returncode, 0)
            self.assertIn("@e1 [heading]", snap_res.stdout)
            self.assertIn("@e2 [button]", snap_res.stdout)
            self.assertIn("@e3 [input", snap_res.stdout)

            # 3. Step: click @e2
            click_res = subprocess.run(["agent-browser", "click", "@e2"],
                                       capture_output=True, text=True, env=env)
            self.assertEqual(click_res.returncode, 0)
            self.assertIn("Clicked element @e2", click_res.stdout)

            # Verify entire chain was executed in order
            logged = chain_log.read_text().splitlines()
            self.assertEqual(logged[0], "open https://agentic-os.local/dashboard")
            self.assertEqual(logged[1], "snapshot -i")
            self.assertEqual(logged[2], "click @e2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
