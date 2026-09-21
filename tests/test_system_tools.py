#!/usr/bin/env python3
"""
Unit tests for AgenticOS System Tools & Live User Hook (Task 9):
- 0099-setup-agentic-user.hook.chroot (syntax, permissions, sudoers, zram, wear mitigations)
- pi-doctor (diagnostics, CLI flags, text dashboard, JSON schema, mock probes)
- pi-net (WiFi & networking CLI, subcommands, flags, mock nmcli parsing, fallbacks)
"""

import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_SCRIPT = REPO_ROOT / "config" / "hooks" / "live" / "0099-setup-agentic-user.hook.chroot"
PI_DOCTOR = REPO_ROOT / "config" / "includes.chroot" / "usr" / "local" / "bin" / "pi-doctor"
PI_NET = REPO_ROOT / "config" / "includes.chroot" / "usr" / "local" / "bin" / "pi-net"


def load_module_from_file(module_name: str, file_path: Path):
    """Dynamically import a Python script without .py extension."""
    from importlib.machinery import SourceFileLoader

    loader = SourceFileLoader(module_name, str(file_path))
    spec = importlib.util.spec_from_loader(module_name, loader)
    if spec is None:
        raise ImportError(f"Cannot load module spec from {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    loader.exec_module(module)
    return module


# Load pi_doctor and pi_net modules for in-depth unit testing
pi_doctor_mod = load_module_from_file("pi_doctor", PI_DOCTOR)
pi_net_mod = load_module_from_file("pi_net", PI_NET)


# ==============================================================================
# 1. File Permissions and Syntax Verification
# ==============================================================================
class TestSystemToolsPermissionsAndSyntax(unittest.TestCase):
    """Verify that all scripts exist, are executable, and pass syntax checks."""

    def test_hook_script_exists_and_executable(self):
        self.assertTrue(HOOK_SCRIPT.is_file(), f"Missing hook script: {HOOK_SCRIPT}")
        self.assertTrue(os.access(HOOK_SCRIPT, os.X_OK), "Hook script must be executable (chmod +x)")

    def test_pi_doctor_exists_and_executable(self):
        self.assertTrue(PI_DOCTOR.is_file(), f"Missing pi-doctor script: {PI_DOCTOR}")
        self.assertTrue(os.access(PI_DOCTOR, os.X_OK), "pi-doctor must be executable (chmod +x)")

    def test_pi_net_exists_and_executable(self):
        self.assertTrue(PI_NET.is_file(), f"Missing pi-net script: {PI_NET}")
        self.assertTrue(os.access(PI_NET, os.X_OK), "pi-net must be executable (chmod +x)")

    def test_bash_syntax_hook_script(self):
        res = subprocess.run(["bash", "-n", str(HOOK_SCRIPT)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Bash syntax error in {HOOK_SCRIPT}:\n{res.stderr}")

    def test_python_syntax_pi_doctor(self):
        res = subprocess.run([sys.executable, "-m", "py_compile", str(PI_DOCTOR)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Python compilation error in {PI_DOCTOR}:\n{res.stderr}")

    def test_python_syntax_pi_net(self):
        res = subprocess.run([sys.executable, "-m", "py_compile", str(PI_NET)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Python compilation error in {PI_NET}:\n{res.stderr}")


# ==============================================================================
# 2. Live User Hook Specifications & Configuration Checks
# ==============================================================================
class TestLiveUserSetupHook(unittest.TestCase):
    """Verify configuration entries, sudoers syntax, zram, and write wear mitigations in hook."""

    def setUp(self):
        self.hook_content = HOOK_SCRIPT.read_text(encoding="utf-8")

    def test_sudoers_configuration_and_visudo(self):
        """Verify passwordless sudo line and visudo syntax check."""
        self.assertIn("user ALL=(ALL) NOPASSWD: ALL", self.hook_content)
        self.assertIn("0440", self.hook_content)

        # Extract sudoers line and validate using visudo if available
        sudo_line = "user ALL=(ALL) NOPASSWD: ALL\n"
        with tempfile.NamedTemporaryFile("w+", delete=False) as tf:
            tf.write(sudo_line)
            tf_path = tf.name

        try:
            visudo = shutil.which("visudo")
            if visudo:
                res = subprocess.run([visudo, "-c", "-f", tf_path], capture_output=True, text=True)
                self.assertEqual(res.returncode, 0, f"visudo verification failed: {res.stderr}")
        finally:
            if os.path.exists(tf_path):
                os.unlink(tf_path)

    def test_system_groups_specifications(self):
        """Ensure all required hardware and permission groups are included."""
        required_groups = ["sudo", "input", "video", "audio", "plugdev", "netdev", "dialout"]
        for grp in required_groups:
            self.assertIn(grp, self.hook_content)
        # Check live-config configuration
        self.assertIn('LIVE_USER_DEFAULT_GROUPS="sudo,input,video,audio,plugdev,netdev,dialout"', self.hook_content)

    def test_zramswap_configuration_keys(self):
        """Ensure zramswap is configured with zstd, 50% RAM, and priority 100."""
        self.assertIn("ALGO=zstd", self.hook_content)
        self.assertIn("PERCENT=50", self.hook_content)
        self.assertIn("PRIORITY=100", self.hook_content)
        self.assertIn("zramswap.service", self.hook_content)

    def test_agentic_state_directory_setup(self):
        """Ensure /var/lib/agentic directory is created with proper permissions."""
        self.assertIn("/var/lib/agentic", self.hook_content)
        self.assertTrue(
            "1777" in self.hook_content or "0777" in self.hook_content or "777" in self.hook_content,
            "Must set permissive/sticky directory mode for /var/lib/agentic",
        )

    def test_usb_flash_wear_optimizations(self):
        """Ensure volatile journald and sysctl write-wear mitigations are configured."""
        self.assertIn("Storage=volatile", self.hook_content)
        self.assertIn("RuntimeMaxUse=64M", self.hook_content)
        self.assertIn("SystemMaxUse=64M", self.hook_content)
        self.assertIn("vm.dirty_writeback_centisecs = 6000", self.hook_content)
        self.assertIn("vm.dirty_expire_centisecs = 6000", self.hook_content)
        self.assertIn("vm.swappiness = 100", self.hook_content)


# ==============================================================================
# 3. pi-doctor Diagnostic Tool Tests
# ==============================================================================
class TestPiDoctorCLI(unittest.TestCase):
    """Test pi-doctor CLI arguments, human report, and JSON schema."""

    def test_help_and_version(self):
        res_help = subprocess.run([str(PI_DOCTOR), "--help"], capture_output=True, text=True)
        self.assertEqual(res_help.returncode, 0)
        self.assertIn("AgenticOS System Health", res_help.stdout)

        res_ver = subprocess.run([str(PI_DOCTOR), "--version"], capture_output=True, text=True)
        self.assertEqual(res_ver.returncode, 0)
        self.assertIn("pi-doctor 1.0.0", res_ver.stdout)

    def test_human_report_sections(self):
        res = subprocess.run([str(PI_DOCTOR), "--quick"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        stdout = res.stdout
        self.assertIn("[CPU & Processing]", stdout)
        self.assertIn("[Memory & Swap / zRAM]", stdout)
        self.assertIn("[GPU & Video Acceleration]", stdout)
        self.assertIn("[Power & Battery]", stdout)
        self.assertIn("[Storage & Persistence Health]", stdout)
        self.assertIn("[Agentic Environment & Runtime]", stdout)

    def test_json_schema_validation(self):
        res = subprocess.run([str(PI_DOCTOR), "--json", "--quick"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)

        # Top-level keys
        for key in ("version", "timestamp", "system", "cpu", "memory", "gpu", "power", "storage", "agentic"):
            self.assertIn(key, data)

        # System
        sys_info = data["system"]
        self.assertIn("platform", sys_info)
        self.assertIn("arch", sys_info)
        self.assertIn("uptime_seconds", sys_info)

        # CPU
        cpu = data["cpu"]
        self.assertIn("model", cpu)
        self.assertIn("arch", cpu)
        self.assertIn("cores_logical", cpu)
        self.assertIn("load_average", cpu)
        self.assertEqual(len(cpu["load_average"]), 3)

        # Memory & zRAM
        mem = data["memory"]
        self.assertIn("ram_total_mb", mem)
        self.assertIn("ram_used_mb", mem)
        self.assertIn("ram_free_mb", mem)
        self.assertIn("zram", mem)
        zram = mem["zram"]
        self.assertIn("active", zram)
        self.assertIn("disksize_mb", zram)
        self.assertIn("compression_ratio", zram)

        # GPU
        gpu = data["gpu"]
        self.assertIn("devices", gpu)
        self.assertIn("drivers", gpu)
        self.assertIn("acceleration", gpu)
        self.assertIn("vulkan", gpu["acceleration"])
        self.assertIn("vaapi", gpu["acceleration"])

        # Power
        power = data["power"]
        self.assertIn("battery_present", power)
        self.assertIn("source", power)

        # Storage
        storage = data["storage"]
        self.assertIn("root_usage", storage)
        self.assertIn("persistence", storage)
        self.assertIn("write_wear_optimizations", storage)
        opt = storage["write_wear_optimizations"]
        self.assertIn("noatime", opt)
        self.assertIn("commit_60", opt)
        self.assertIn("tmpfs_tmp", opt)
        self.assertIn("journal_volatile", opt)

        # Agentic
        agn = data["agentic"]
        self.assertIn("ipc_socket", agn)
        self.assertIn("ghost_workspace", agn)
        self.assertIn("ollama", agn)
        self.assertIn("pi_agent", agn)
        self.assertIn("path", agn["ipc_socket"])
        self.assertIn("running", agn["ghost_workspace"])
        self.assertIn("installed", agn["pi_agent"])


class TestPiDoctorProbesMocked(unittest.TestCase):
    """Test detailed probe functions using mock filesystem and environment."""

    def test_mock_zram_diagnostics(self):
        """Verify zram detection with mock sysfs entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            zram0 = os.path.join(tmpdir, "zram0")
            os.makedirs(zram0, exist_ok=True)
            with open(os.path.join(zram0, "comp_algorithm"), "w") as f:
                f.write("lzo [zstd] lz4")
            with open(os.path.join(zram0, "disksize"), "w") as f:
                f.write(str(4 * 1024 * 1024 * 1024))  # 4 GB
            with open(os.path.join(zram0, "mm_stat"), "w") as f:
                # orig_data_size compr_data_size ...
                orig = 1500 * 1024 * 1024
                compr = 500 * 1024 * 1024
                f.write(f"{orig} {compr} 524288000 0 524288000 0 0\n")

            with patch("glob.glob", return_value=[zram0]):
                mem_info = pi_doctor_mod.get_memory_info()
                zram = mem_info["zram"]
                self.assertEqual(zram["device"], "zram0")
                self.assertEqual(zram["algorithm"], "zstd")
                self.assertEqual(zram["disksize_mb"], 4096)
                self.assertEqual(zram["orig_data_mb"], 1500.0)
                self.assertEqual(zram["compr_data_mb"], 500.0)
                self.assertEqual(zram["compression_ratio"], 3.0)

    def test_mock_battery_power(self):
        """Verify battery capacity and status parsing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bat0 = os.path.join(tmpdir, "BAT0")
            os.makedirs(bat0, exist_ok=True)
            with open(os.path.join(bat0, "type"), "w") as f:
                f.write("Battery\n")
            with open(os.path.join(bat0, "capacity"), "w") as f:
                f.write("78\n")
            with open(os.path.join(bat0, "status"), "w") as f:
                f.write("Charging\n")
            with open(os.path.join(bat0, "health"), "w") as f:
                f.write("Good\n")

            with patch("glob.glob", return_value=[bat0]):
                power = pi_doctor_mod.get_power_info()
                self.assertTrue(power["battery_present"])
                self.assertEqual(power["battery_percent"], 78)
                self.assertEqual(power["battery_status"], "Charging")
                self.assertEqual(power["battery_health"], "Good")

    def test_mock_agentic_socket_detection(self):
        """Verify IPC socket detection when Unix domain socket exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sock_path = os.path.join(tmpdir, "agentic.sock")
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.bind(sock_path)
            s.listen(1)

            try:
                with patch.dict(os.environ, {"AGENTIC_SOCKET_PATH": sock_path}):
                    res = pi_doctor_mod.get_agentic_info(quick=True)
                    self.assertEqual(res["ipc_socket"]["path"], sock_path)
                    self.assertTrue(res["ipc_socket"]["active"])
            finally:
                s.close()
                if os.path.exists(sock_path):
                    os.unlink(sock_path)


# ==============================================================================
# 4. pi-net WiFi & Networking Tool Tests
# ==============================================================================
class TestPiNetCLI(unittest.TestCase):
    """Test pi-net CLI flags, subcommands, output formatting, and mock nmcli interactions."""

    def test_help_and_version(self):
        res_help = subprocess.run([str(PI_NET), "--help"], capture_output=True, text=True)
        self.assertEqual(res_help.returncode, 0)
        self.assertIn("WiFi & Networking CLI", res_help.stdout)

        res_ver = subprocess.run([str(PI_NET), "--version"], capture_output=True, text=True)
        self.assertEqual(res_ver.returncode, 0)
        self.assertIn("pi-net 1.0.0", res_ver.stdout)

    def test_status_text_and_json(self):
        # Text status
        res = subprocess.run([str(PI_NET), "status"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("AgenticOS Network Status", res.stdout)
        self.assertIn("[Network Interfaces]", res.stdout)

        # JSON status
        res_json = subprocess.run([str(PI_NET), "status", "--json"], capture_output=True, text=True)
        self.assertEqual(res_json.returncode, 0)
        data = json.loads(res_json.stdout)
        self.assertIn("status", data)
        self.assertIn("backend", data)
        self.assertIn("interfaces", data)
        self.assertIn("wifi", data)
        self.assertIn("radio", data)
        self.assertIsInstance(data["interfaces"], list)

    def test_scan_command_json(self):
        res_json = subprocess.run([str(PI_NET), "scan", "--json"], capture_output=True, text=True)
        self.assertEqual(res_json.returncode, 0)
        data = json.loads(res_json.stdout)
        self.assertIsInstance(data, list)


class TestPiNetMockedNMCLI(unittest.TestCase):
    """Test pi-net command execution and nmcli output parsing with mocks."""

    def test_mock_scan_parsing(self):
        """Verify parsing of nmcli dev wifi list output."""
        mock_stdout = (
            "*:Agentic-HQ:00\\:11\\:22\\:33\\:44\\:55:Infra:6:2437 MHz:54 Mbit/s:92:____:WPA2\n"
            " :Cafe-Guest:AA\\:BB\\:CC\\:DD\\:EE\\:FF:Infra:1:2412 MHz:54 Mbit/s:65:____:WPA2\n"
            " :Free-Public:11\\:22\\:33\\:44\\:55\\:66:Infra:11:2462 MHz:54 Mbit/s:40:____:\n"
        )

        with patch.object(pi_net_mod, "shutil") as mock_shutil:
            mock_shutil.which.return_value = "/usr/bin/nmcli"
            with patch.object(pi_net_mod, "run_nmcli", return_value=(0, mock_stdout, "")):
                networks = pi_net_mod.scan_wifi_networks(rescan=False)
                self.assertEqual(len(networks), 3)

                # Network 1 (Active)
                self.assertTrue(networks[0]["in_use"])
                self.assertEqual(networks[0]["ssid"], "Agentic-HQ")
                self.assertEqual(networks[0]["bssid"], "00:11:22:33:44:55")
                self.assertEqual(networks[0]["signal"], 92)
                self.assertEqual(networks[0]["security"], "WPA2")

                # Network 2
                self.assertFalse(networks[1]["in_use"])
                self.assertEqual(networks[1]["ssid"], "Cafe-Guest")
                self.assertEqual(networks[1]["bssid"], "AA:BB:CC:DD:EE:FF")
                self.assertEqual(networks[1]["signal"], 65)

                # Network 3 (Open security)
                self.assertFalse(networks[2]["in_use"])
                self.assertEqual(networks[2]["ssid"], "Free-Public")
                self.assertEqual(networks[2]["security"], "OPEN")

    def test_mock_status_connected_parsing(self):
        """Verify parsing of full device and wifi connection state."""
        dev_stdout = (
            "wlan0:wifi:connected:Agentic-WiFi\n"
            "eth0:ethernet:unavailable:--\n"
            "lo:loopback:unmanaged:--\n"
        )
        wifi_stdout = "*:Agentic-WiFi:00\\:11\\:22\\:33\\:44\\:55:88:WPA2:wlan0\n"
        show_stdout = (
            "IP4.ADDRESS[1]:192.168.1.150/24\n"
            "IP4.GATEWAY:192.168.1.1\n"
            "IP4.DNS[1]:1.1.1.1\n"
            "IP4.DNS[2]:8.8.8.8\n"
        )

        def mock_nmcli_dispatch(args, timeout=15):
            if "radio" in args:
                return 0, "enabled\n", ""
            elif "device" in args and "-f" in args and "DEVICE,TYPE,STATE,CONNECTION" in args:
                return 0, dev_stdout, ""
            elif "wifi" in args and "IN-USE,SSID,BSSID,SIGNAL,SECURITY,DEVICE" in args:
                return 0, wifi_stdout, ""
            elif "show" in args:
                return 0, show_stdout, ""
            return 0, "", ""

        with patch.object(pi_net_mod, "shutil") as mock_shutil:
            mock_shutil.which.return_value = "/usr/bin/nmcli"
            with patch.object(pi_net_mod, "run_nmcli", side_effect=mock_nmcli_dispatch):
                status = pi_net_mod.get_network_status()
                self.assertEqual(status["status"], "connected")
                self.assertTrue(status["radio"]["wifi_enabled"])
                self.assertTrue(status["wifi"]["connected"])
                self.assertEqual(status["wifi"]["ssid"], "Agentic-WiFi")
                self.assertEqual(status["wifi"]["ip"], "192.168.1.150")
                self.assertEqual(status["wifi"]["gateway"], "192.168.1.1")
                self.assertEqual(status["wifi"]["dns"], ["1.1.1.1", "8.8.8.8"])

    def test_mock_connect_success_and_failure(self):
        """Verify connect command arguments and handling."""
        with patch.object(pi_net_mod, "shutil") as mock_shutil:
            mock_shutil.which.return_value = "/usr/bin/nmcli"

            # 1. Success case with password
            with patch.object(pi_net_mod, "run_nmcli", return_value=(0, "Device 'wlan0' successfully activated", "")):
                res = pi_net_mod.connect_wifi("TestSSID", password="secretpassword")
                self.assertEqual(res["status"], "success")
                self.assertIn("successfully activated", res["message"])

            # 2. Failure case
            with patch.object(pi_net_mod, "run_nmcli", return_value=(1, "", "Error: Secrets were required, but not provided")):
                res_err = pi_net_mod.connect_wifi("TestSSID", password="wrongpassword")
                self.assertEqual(res_err["status"], "error")
                self.assertIn("Secrets were required", res_err["message"])

    def test_mock_disconnect_device_and_connection(self):
        """Verify disconnect command logic."""
        with patch.object(pi_net_mod, "shutil") as mock_shutil:
            mock_shutil.which.return_value = "/usr/bin/nmcli"

            # Disconnect specific interface
            with patch.object(pi_net_mod, "run_nmcli", return_value=(0, "Device 'wlan0' successfully disconnected.", "")):
                res = pi_net_mod.disconnect_network("wlan0")
                self.assertEqual(res["status"], "success")
                self.assertEqual(res["target"], "wlan0")

    def test_mock_radio_toggle(self):
        """Verify turning wifi radio on and off."""
        with patch.object(pi_net_mod, "shutil") as mock_shutil:
            mock_shutil.which.return_value = "/usr/bin/nmcli"

            with patch.object(pi_net_mod, "run_nmcli", return_value=(0, "", "")):
                res_on = pi_net_mod.toggle_radio(True)
                self.assertEqual(res_on["status"], "success")
                self.assertEqual(res_on["wifi_radio"], "on")

                res_off = pi_net_mod.toggle_radio(False)
                self.assertEqual(res_off["status"], "success")
                self.assertEqual(res_off["wifi_radio"], "off")


if __name__ == "__main__":
    unittest.main()
