#!/usr/bin/env python3
"""
Unit tests for AgenticOS Computer Use Gateway and Ghost Workspace Helper.
Covers CLI --help, --dump-tree, --status, --click, --type, --screenshot,
JSON schemas, Python module APIs, HTTP / JSON-RPC 2.0, Unix Socket,
and ghost-workspace-helper script validation.
"""

import os
import sys
import json
import time
import socket
import unittest
import tempfile
import subprocess
import importlib.util
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GATEWAY_SCRIPT = REPO_ROOT / "config" / "includes.chroot" / "usr" / "local" / "bin" / "computer-use-gateway"
GHOST_HELPER = REPO_ROOT / "config" / "includes.chroot" / "usr" / "local" / "bin" / "ghost-workspace-helper"
SYSTEMD_SERVICE = REPO_ROOT / "config" / "includes.chroot" / "etc" / "systemd" / "user" / "computer-use-gateway.service"

from importlib.machinery import SourceFileLoader

# Load gateway dynamically as python module (supports extensionless executable)
loader = SourceFileLoader("computer_use_gateway", str(GATEWAY_SCRIPT))
spec = importlib.util.spec_from_loader("computer_use_gateway", loader)
gateway_mod = importlib.util.module_from_spec(spec)
loader.exec_module(gateway_mod)


class TestFilePermissions(unittest.TestCase):
    """Verifies all target files exist, have valid permissions and shell syntax."""

    def test_scripts_exist_and_executable(self):
        self.assertTrue(GATEWAY_SCRIPT.is_file(), f"Missing {GATEWAY_SCRIPT}")
        self.assertTrue(os.access(GATEWAY_SCRIPT, os.X_OK), "computer-use-gateway must be executable")

        self.assertTrue(GHOST_HELPER.is_file(), f"Missing {GHOST_HELPER}")
        self.assertTrue(os.access(GHOST_HELPER, os.X_OK), "ghost-workspace-helper must be executable")

        self.assertTrue(SYSTEMD_SERVICE.is_file(), f"Missing {SYSTEMD_SERVICE}")

    def test_ghost_helper_bash_syntax(self):
        res = subprocess.run(["bash", "-n", str(GHOST_HELPER)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Bash syntax error in {GHOST_HELPER}:\n{res.stderr}")

    def test_systemd_service_contents(self):
        content = SYSTEMD_SERVICE.read_text()
        self.assertIn("ExecStart=/usr/local/bin/computer-use-gateway --serve", content)
        self.assertIn("WantedBy=graphical-session.target", content)
        self.assertIn("Restart=on-failure", content)


class TestGatewayCLI(unittest.TestCase):
    """Tests command-line interface execution and outputs."""

    def test_cli_help(self):
        res = subprocess.run([sys.executable, str(GATEWAY_SCRIPT), "--help"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("--dump-tree", res.stdout)
        self.assertIn("--click", res.stdout)
        self.assertIn("--type", res.stdout)
        self.assertIn("--screenshot", res.stdout)
        self.assertIn("--status", res.stdout)
        self.assertIn("--serve", res.stdout)

    def test_cli_status(self):
        res = subprocess.run([sys.executable, str(GATEWAY_SCRIPT), "--status"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertEqual(data.get("status"), "running")
        self.assertIn("version", data)
        self.assertIn("environment", data)
        self.assertIn("backends", data)
        self.assertIn("default_socket", data)
        self.assertIn("default_http_port", data)

    def test_cli_dump_tree(self):
        res = subprocess.run([sys.executable, str(GATEWAY_SCRIPT), "--dump-tree"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        tree = json.loads(res.stdout)
        self.assertIn("id", tree)
        self.assertIn("role", tree)
        self.assertIn("bounding_box", tree)

    def test_cli_click_coords(self):
        res = subprocess.run([sys.executable, str(GATEWAY_SCRIPT), "--click", "640,480"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertEqual(data.get("status"), "ok")
        self.assertEqual(data.get("coords"), [640, 480])

    def test_cli_click_element(self):
        res = subprocess.run([sys.executable, str(GATEWAY_SCRIPT), "--click-element", "btn_search"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertEqual(data.get("status"), "ok")
        self.assertEqual(data.get("element_id"), "btn_search")
        self.assertIn("coords", data)

    def test_cli_type_and_hotkey(self):
        res = subprocess.run(
            [sys.executable, str(GATEWAY_SCRIPT), "--type", "test string", "--hotkey", "Return"],
            capture_output=True, text=True
        )
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertEqual(data.get("status"), "ok")
        self.assertEqual(data.get("text"), "test string")
        self.assertEqual(data.get("hotkey"), "Return")

    def test_cli_screenshot(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            res = subprocess.run(
                [sys.executable, str(GATEWAY_SCRIPT), "--screenshot", tmp_path],
                capture_output=True, text=True
            )
            self.assertEqual(res.returncode, 0)
            data = json.loads(res.stdout)
            self.assertEqual(data.get("status"), "ok")
            self.assertTrue(os.path.exists(tmp_path))
            self.assertGreater(os.path.getsize(tmp_path), 0)

            # Validate PNG magic bytes: \x89PNG\r\n\x1a\n
            with open(tmp_path, "rb") as f:
                header = f.read(8)
            self.assertEqual(header, b"\x89PNG\r\n\x1a\n")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


class TestTreeJSONSchema(unittest.TestCase):
    """Validates the schema of accessibility trees returned by the gateway."""

    def _validate_node_schema(self, node: dict, depth: int = 0):
        self.assertIsInstance(node, dict, "Each tree node must be a dict")
        self.assertIn("id", node, "Node missing 'id'")
        self.assertIsInstance(node["id"], str, "'id' must be a string")

        self.assertIn("role", node, "Node missing 'role'")
        self.assertIsInstance(node["role"], str, "'role' must be a string")

        self.assertIn("name", node, "Node missing 'name'")
        self.assertIsInstance(node["name"], str, "'name' must be a string")

        self.assertIn("states", node, "Node missing 'states'")
        self.assertIsInstance(node["states"], list, "'states' must be a list")

        self.assertIn("bounding_box", node, "Node missing 'bounding_box'")
        bbox = node["bounding_box"]
        self.assertIsInstance(bbox, list, "'bounding_box' must be a list")
        self.assertEqual(len(bbox), 4, "'bounding_box' must contain [x, y, w, h]")
        for val in bbox:
            self.assertIsInstance(val, int, f"Bbox values must be ints, got {type(val)}")
        self.assertGreaterEqual(bbox[2], 0, "Bbox width must be non-negative")
        self.assertGreaterEqual(bbox[3], 0, "Bbox height must be non-negative")

        if "children" in node:
            self.assertIsInstance(node["children"], list, "'children' must be a list")
            for child in node["children"]:
                self._validate_node_schema(child, depth + 1)

    def test_tree_schema_conformance(self):
        tree = gateway_mod.dump_tree()
        self._validate_node_schema(tree)

    def test_element_lookup_and_center_calculation(self):
        tree = gateway_mod.dump_tree()
        btn = gateway_mod.find_node_by_id(tree, "btn_search")
        self.assertIsNotNone(btn)
        self.assertEqual(btn.get("role"), "push_button")
        self.assertEqual(btn.get("name"), "Search")

        # Click element API test
        click_res = gateway_mod.click_element("btn_search")
        self.assertEqual(click_res["status"], "ok")
        self.assertEqual(click_res["element_id"], "btn_search")
        x, y, w, h = btn["bounding_box"]
        expected_coords = [x + w // 2, y + h // 2]
        self.assertEqual(click_res["coords"], expected_coords)


class TestPythonAPI(unittest.TestCase):
    """Directly tests Python module functions."""

    def test_click_coords_mock_fallback(self):
        res = gateway_mod.click_coords(100, 200, button="right", double=True)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["coords"], [100, 200])
        self.assertEqual(res["button"], "right")
        self.assertTrue(res["double"])

    def test_type_text(self):
        res = gateway_mod.type_text("Hello World", hotkey="Ctrl+C")
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["text"], "Hello World")
        self.assertEqual(res["hotkey"], "Ctrl+C")

    def test_screenshot_generation(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            out_file = tmp.name

        try:
            res = gateway_mod.capture_screenshot(out_file)
            self.assertEqual(res["status"], "ok")
            self.assertTrue(os.path.exists(out_file))
            self.assertEqual(res["size"], [1920, 1080])
            self.assertGreater(res["file_bytes"], 100)
        finally:
            if os.path.exists(out_file):
                os.remove(out_file)

    def test_dispatch_request(self):
        res_tree = gateway_mod.dispatch_request("inspect_tree")
        self.assertIn("id", res_tree)

        res_click = gateway_mod.dispatch_request("click", {"x": 300, "y": 400})
        self.assertEqual(res_click["status"], "ok")
        self.assertEqual(res_click["coords"], [300, 400])

        res_unknown = gateway_mod.dispatch_request("invalid_method")
        self.assertEqual(res_unknown["status"], "error")


class TestNetworkDaemon(unittest.TestCase):
    """Tests running HTTP server, JSON-RPC 2.0, and Unix Domain Socket endpoints."""

    @classmethod
    def setUpClass(cls):
        cls.test_port = 19890
        cls.tmp_sock_dir = tempfile.mkdtemp()
        cls.test_sock = os.path.join(cls.tmp_sock_dir, "test-gateway.sock")
        cls.daemon = gateway_mod.GatewayDaemon(host="127.0.0.1", port=cls.test_port, socket_path=cls.test_sock)
        cls.daemon.start()
        # Allow daemon threads to spin up
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls):
        cls.daemon.stop()
        if os.path.exists(cls.test_sock):
            try:
                os.unlink(cls.test_sock)
            except OSError:
                pass
        if os.path.exists(cls.tmp_sock_dir):
            try:
                os.rmdir(cls.tmp_sock_dir)
            except OSError:
                pass

    def test_http_get_status(self):
        url = f"http://127.0.0.1:{self.test_port}/status"
        with urllib.request.urlopen(url) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode())
            self.assertEqual(data.get("status"), "running")

    def test_http_get_tree(self):
        url = f"http://127.0.0.1:{self.test_port}/tree"
        with urllib.request.urlopen(url) as resp:
            self.assertEqual(resp.status, 200)
            tree = json.loads(resp.read().decode())
            self.assertIn("id", tree)

    def test_http_json_rpc_inspect_tree(self):
        url = f"http://127.0.0.1:{self.test_port}/rpc"
        payload = json.dumps({
            "jsonrpc": "2.0",
            "id": "req-1",
            "method": "inspect_tree",
            "params": {}
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode())
            self.assertEqual(data.get("id"), "req-1")
            self.assertIn("result", data)
            self.assertEqual(data["result"].get("id"), "desktop_root")

    def test_http_json_rpc_click_and_type(self):
        url = f"http://127.0.0.1:{self.test_port}/rpc"

        # Test click_coords
        payload_click = json.dumps({
            "jsonrpc": "2.0",
            "id": 10,
            "method": "click_coords",
            "params": {"x": 250, "y": 350}
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload_click, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            self.assertEqual(data["result"]["coords"], [250, 350])

        # Test type_text
        payload_type = json.dumps({
            "jsonrpc": "2.0",
            "id": 11,
            "method": "type_text",
            "params": {"text": "RPC typing test"}
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload_type, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            self.assertEqual(data["result"]["text"], "RPC typing test")

    def test_unix_domain_socket_rpc(self):
        self.assertTrue(os.path.exists(self.test_sock), "Unix domain socket file must exist")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(self.test_sock)
            req = json.dumps({
                "jsonrpc": "2.0",
                "id": "sock-99",
                "method": "get_status",
                "params": {}
            })
            s.sendall((req + "\n").encode("utf-8"))
            raw = s.recv(4096).decode("utf-8")
            data = json.loads(raw)
            self.assertEqual(data.get("id"), "sock-99")
            self.assertEqual(data["result"].get("status"), "running")


class TestGhostWorkspaceHelper(unittest.TestCase):
    """Tests ghost-workspace-helper script execution."""

    def test_help(self):
        res = subprocess.run([str(GHOST_HELPER), "--help"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("ensure", res.stdout)
        self.assertIn("launch", res.stdout)
        self.assertIn("move", res.stdout)
        self.assertIn("switch", res.stdout)
        self.assertIn("list", res.stdout)
        self.assertIn("status", res.stdout)

    def test_status_json(self):
        res = subprocess.run([str(GHOST_HELPER), "status", "--json"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertEqual(data.get("status"), "ok")
        self.assertIn("num_workspaces", data)
        self.assertEqual(data.get("ghost_workspace_index"), 1)

    def test_ensure_json(self):
        res = subprocess.run([str(GHOST_HELPER), "ensure", "--json"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertEqual(data.get("status"), "ok")
        self.assertEqual(data.get("ghost_workspace_index"), 1)
        self.assertEqual(data.get("focus_mode"), "strict")

    def test_move_json(self):
        res = subprocess.run([str(GHOST_HELPER), "move", "99999", "1", "--json"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertEqual(data.get("status"), "ok")
        self.assertEqual(data.get("target"), "99999")
        self.assertEqual(data.get("target_workspace"), 1)

    def test_list_json(self):
        res = subprocess.run([str(GHOST_HELPER), "list", "--json"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertEqual(data.get("status"), "ok")
        self.assertEqual(data.get("ghost_workspace_index"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
