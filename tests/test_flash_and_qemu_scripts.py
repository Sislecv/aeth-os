#!/usr/bin/env python3
"""Unit tests for AgenticOS USB Flash and QEMU Test Tooling (Task 10)."""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_QEMU_SCRIPT = REPO_ROOT / "scripts" / "test-qemu.sh"
FLASH_USB_SCRIPT = REPO_ROOT / "scripts" / "flash-usb.sh"


class TestScriptFileIntegrity(unittest.TestCase):
    """Verifies existence, permissions, and syntax of tooling scripts."""

    def test_scripts_exist(self):
        self.assertTrue(TEST_QEMU_SCRIPT.is_file(), f"Missing {TEST_QEMU_SCRIPT}")
        self.assertTrue(FLASH_USB_SCRIPT.is_file(), f"Missing {FLASH_USB_SCRIPT}")

    def test_scripts_executable(self):
        self.assertTrue(
            os.access(TEST_QEMU_SCRIPT, os.X_OK),
            f"{TEST_QEMU_SCRIPT} must be executable (chmod +x)",
        )
        self.assertTrue(
            os.access(FLASH_USB_SCRIPT, os.X_OK),
            f"{FLASH_USB_SCRIPT} must be executable (chmod +x)",
        )

    def test_scripts_shebang(self):
        for script in (TEST_QEMU_SCRIPT, FLASH_USB_SCRIPT):
            with open(script, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
            self.assertEqual(first_line, "#!/usr/bin/env bash", f"Unexpected shebang in {script}")

    def test_bash_syntax_check(self):
        for script in (TEST_QEMU_SCRIPT, FLASH_USB_SCRIPT):
            res = subprocess.run(
                ["bash", "-n", str(script)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                res.returncode,
                0,
                f"Syntax validation (bash -n) failed for {script}: {res.stderr}",
            )


class TestTestQemuScript(unittest.TestCase):
    """Tests command-line parsing and QEMU command generation."""

    def test_help_flag(self):
        for flag in ["-h", "--help"]:
            res = subprocess.run(
                [str(TEST_QEMU_SCRIPT), flag],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0)
            self.assertIn("AgenticOS QEMU Live Test Runner", res.stdout)
            self.assertIn("--mem", res.stdout)
            self.assertIn("--uefi", res.stdout)
            self.assertIn("--dry-run", res.stdout)

    def test_unknown_argument(self):
        res = subprocess.run(
            [str(TEST_QEMU_SCRIPT), "--non-existent-flag"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Error: Unknown option", res.stderr)

    def test_dry_run_defaults(self):
        res = subprocess.run(
            [str(TEST_QEMU_SCRIPT), "--dry-run"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0)
        out = res.stdout
        self.assertIn("[DRY-RUN] AgenticOS QEMU Test Runner Preview", out)
        self.assertIn("qemu-system-x86_64", out)
        self.assertIn("-m 4096M", out)
        self.assertIn("-smp 2", out)
        self.assertIn("-vga virtio", out)
        self.assertIn("-device virtio-tablet-pci", out)
        self.assertIn("-net nic,model=virtio", out)
        self.assertIn("-net user", out)
        self.assertIn("-boot d", out)

    def test_dry_run_custom_memory(self):
        res = subprocess.run(
            [str(TEST_QEMU_SCRIPT), "--dry-run", "--mem", "8192M"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("-m 8192M", res.stdout)

        # Test integer normalization (e.g. 2048 -> 2048M)
        res_int = subprocess.run(
            [str(TEST_QEMU_SCRIPT), "--dry-run", "-m", "2048"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_int.returncode, 0)
        self.assertIn("-m 2048M", res_int.stdout)

    def test_dry_run_custom_cpus(self):
        res = subprocess.run(
            [str(TEST_QEMU_SCRIPT), "--dry-run", "-c", "4"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("-smp 4", res.stdout)

    def test_dry_run_uefi_and_bios_modes(self):
        # UEFI mode
        res_uefi = subprocess.run(
            [str(TEST_QEMU_SCRIPT), "--dry-run", "--uefi"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_uefi.returncode, 0)
        self.assertIn("Boot Mode:    uefi", res_uefi.stdout)
        self.assertIn("-bios", res_uefi.stdout)

        # Legacy BIOS mode
        res_bios = subprocess.run(
            [str(TEST_QEMU_SCRIPT), "--dry-run", "--bios"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_bios.returncode, 0)
        self.assertIn("Boot Mode:    bios", res_bios.stdout)
        self.assertNotIn("-bios", res_bios.stdout)

    def test_dry_run_kvm_flags(self):
        # Force KVM
        res_kvm = subprocess.run(
            [str(TEST_QEMU_SCRIPT), "--dry-run", "--kvm"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_kvm.returncode, 0)
        self.assertIn("-enable-kvm -cpu host", res_kvm.stdout)

        # Disable KVM (TCG software emulation)
        res_nokvm = subprocess.run(
            [str(TEST_QEMU_SCRIPT), "--dry-run", "--no-kvm"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_nokvm.returncode, 0)
        self.assertNotIn("-enable-kvm", res_nokvm.stdout)
        self.assertIn("-cpu qemu64", res_nokvm.stdout)

    def test_dry_run_snapshot_and_dual_monitor(self):
        res = subprocess.run(
            [str(TEST_QEMU_SCRIPT), "--dry-run", "--snapshot", "--dual-monitor"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("-snapshot", res.stdout)
        self.assertIn("-device secondary-vga", res.stdout)

    def test_dry_run_custom_iso(self):
        res = subprocess.run(
            [str(TEST_QEMU_SCRIPT), "--dry-run", "--iso", "/tmp/custom-os.iso"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("-cdrom /tmp/custom-os.iso", res.stdout)

        # Positional ISO path
        res_pos = subprocess.run(
            [str(TEST_QEMU_SCRIPT), "--dry-run", "/opt/positional.iso"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_pos.returncode, 0)
        self.assertIn("-cdrom /opt/positional.iso", res_pos.stdout)

    def test_missing_iso_without_dry_run_fails(self):
        # When no ISO exists and no --dry-run is given
        res = subprocess.run(
            [str(TEST_QEMU_SCRIPT), "--iso", "/nonexistent/path/never_there.iso"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Error: Specified ISO image not found", res.stderr)


class TestFlashUsbScript(unittest.TestCase):
    """Tests argument parsing, safety checks, and dry-run command generation."""

    def test_help_flag(self):
        for flag in ["-h", "--help"]:
            res = subprocess.run(
                [str(FLASH_USB_SCRIPT), flag],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0)
            self.assertIn("AgenticOS USB Flash & Persistence Tool", res.stdout)
            self.assertIn("--target", res.stdout)
            self.assertIn("--dry-run", res.stdout)
            self.assertIn("--yes", res.stdout)

    def test_missing_target_argument(self):
        res = subprocess.run(
            [str(FLASH_USB_SCRIPT)],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Error: Target block device is required", res.stderr)

    def test_safety_blocks_non_block_regular_file(self):
        with tempfile.NamedTemporaryFile() as tmp:
            res = subprocess.run(
                [str(FLASH_USB_SCRIPT), tmp.name],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("not a valid block device", res.stderr)

    def test_safety_blocks_character_device(self):
        res = subprocess.run(
            [str(FLASH_USB_SCRIPT), "/dev/null"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("not a valid block device", res.stderr)

    def test_safety_blocks_active_system_disks(self):
        # Discover actual mounted system disk(s) (e.g. sda, sdb)
        lsblk_res = subprocess.run(
            ["lsblk", "-rn", "-o", "PKNAME,NAME,MOUNTPOINTS"],
            capture_output=True,
            text=True,
        )
        critical_devices = set()
        for line in lsblk_res.stdout.splitlines():
            parts = line.split(maxsplit=2)
            if len(parts) >= 3 and any(
                crit in parts[2]
                for crit in ["/root", "/home", "/etc", "/var", "/boot"]
            ):
                pkname = parts[0]
                name = parts[1]
                base = pkname if pkname else name
                critical_devices.add(f"/dev/{base}")
                critical_devices.add(f"/dev/{name}")

        self.assertTrue(len(critical_devices) > 0, "Expected at least one active system disk")

        for dev in sorted(critical_devices):
            res = subprocess.run(
                [str(FLASH_USB_SCRIPT), dev],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(res.returncode, 0, f"Expected {dev} to be blocked by safety checks")
            self.assertTrue(
                "Refusing to overwrite active system disk" in res.stderr
                or "critical system mount" in res.stderr
                or "Refusing to overwrite" in res.stderr,
                f"Expected safety refusal message for {dev}, got: {res.stderr}",
            )

    def test_dry_run_command_generation_loop_device(self):
        # /dev/loop0 is an unmounted block device on Linux container environments
        loop_dev = "/dev/loop0"
        if not os.path.exists(loop_dev):
            loop_dev = "/dev/sdX"

        res = subprocess.run(
            [str(FLASH_USB_SCRIPT), "--dry-run", loop_dev],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0)
        out = res.stdout

        # Verify key planned operations are present in execution plan
        self.assertIn("[DRY-RUN] AgenticOS USB Flash Execution Plan", out)
        self.assertIn("wipefs --all --force", out)
        self.assertIn("parted -s", out)
        self.assertIn("mklabel gpt", out)
        self.assertIn('mkpart "EFI-LIVE" fat32 1MiB 513MiB', out)
        self.assertIn("set 1 esp on", out)
        self.assertIn("set 1 boot on", out)
        self.assertIn('mkpart "AgenticOS-Live" 513MiB 4609MiB', out)
        self.assertIn('mkpart "persistence" ext4 4609MiB 100%', out)
        self.assertIn("mkfs.vfat -F 32 -n \"EFI-LIVE\"", out)
        self.assertIn("dd if=", out)
        self.assertIn("mkfs.ext4 -F -L persistence", out)
        self.assertIn("lazy_itable_init=0,lazy_journal_init=0", out)
        self.assertIn("tune2fs -o journal_data_writeback", out)
        self.assertIn('echo "/ union" >', out)
        self.assertIn("persistence.conf", out)

    def test_dry_run_custom_iso_and_label(self):
        res = subprocess.run(
            [
                str(FLASH_USB_SCRIPT),
                "--dry-run",
                "/dev/sdX",
                "--iso",
                "/tmp/agentic-custom.iso",
                "--label",
                "custom_persist",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0)
        out = res.stdout
        self.assertIn("Source ISO Image:    /tmp/agentic-custom.iso", out)
        self.assertIn("Persistence Label:   custom_persist", out)
        self.assertIn('mkpart "custom_persist" ext4 4609MiB 100%', out)
        self.assertIn("dd if=/tmp/agentic-custom.iso of=/dev/sdX2", out)
        self.assertIn("mkfs.ext4 -F -L custom_persist", out)

    def test_dry_run_partition_naming_nvme(self):
        res = subprocess.run(
            [str(FLASH_USB_SCRIPT), "--dry-run", "/dev/nvme0n1"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0)
        out = res.stdout
        self.assertIn("/dev/nvme0n1p1", out)
        self.assertIn("/dev/nvme0n1p2", out)
        self.assertIn("/dev/nvme0n1p3", out)

    def test_real_run_requires_root_or_fails(self):
        # Non-root user running real execution without sudo must fail
        if os.geteuid() != 0:
            res = subprocess.run(
                [str(FLASH_USB_SCRIPT), "--yes", "/dev/loop0"],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("Root privileges required", res.stderr)


if __name__ == "__main__":
    unittest.main()
