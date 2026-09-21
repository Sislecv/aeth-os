#!/usr/bin/env python3
"""
Unit and integration tests for AgenticOS Local Voice Engine (Task 8):
1. 0080-setup-blurt-voice.hook.chroot (syntax, execution permissions, content checks).
2. 03-blurt-voice dconf settings (keybindings F5, Super+F5, VAD 1.0s, auto-paste, dconf compile).
3. agentic-voice-agent CLI:
   - --help, --version, --status JSON schema and content
   - --dry-run with --cursor and --agent
   - --model path override
   - Text injection fallback logic
   - Unix socket dispatch simulation
   - Whisper output cleanup and parsing
4. blurt@agentic.os GNOME Shell Extension files and metadata JSON schema.
5. End-to-end simulated mock audio transcription pipeline.
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
HOOK_PATH = REPO_ROOT / "config/hooks/live/0080-setup-blurt-voice.hook.chroot"
DCONF_PATH = REPO_ROOT / "config/includes.chroot/etc/dconf/db/local.d/03-blurt-voice"
VOICE_AGENT_PATH = REPO_ROOT / "config/includes.chroot/usr/local/bin/agentic-voice-agent"


class TestHookScript(unittest.TestCase):
    """Verifies hook script syntax, permissions, and required capabilities."""

    def test_hook_exists_and_executable(self):
        self.assertTrue(HOOK_PATH.is_file(), f"Missing hook at {HOOK_PATH}")
        self.assertTrue(os.access(HOOK_PATH, os.X_OK), f"Hook must be executable: {HOOK_PATH}")

    def test_hook_bash_syntax(self):
        res = subprocess.run(["bash", "-n", str(HOOK_PATH)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Bash syntax error in hook:\n{res.stderr}")

    def test_hook_contains_required_sections(self):
        content = HOOK_PATH.read_text(encoding="utf-8")
        self.assertIn("whisper.cpp", content)
        self.assertIn("/usr/share/agentic/models/whisper", content)
        self.assertIn("ggml-base.bin", content)
        self.assertIn("blurt@agentic.os", content)
        self.assertIn("dconf update", content)
        self.assertIn("setup_whisper_binary", content)
        self.assertIn("setup_whisper_model", content)
        self.assertIn("deploy_gnome_extension", content)


class TestDconfConfiguration(unittest.TestCase):
    """Verifies 03-blurt-voice dconf settings and keybindings."""

    def setUp(self):
        self.assertTrue(DCONF_PATH.is_file(), f"Missing dconf config at {DCONF_PATH}")
        self.content = DCONF_PATH.read_text(encoding="utf-8")

    def test_keybinding_definitions(self):
        self.assertIn("custom-keybindings", self.content)
        self.assertIn("binding='F5'", self.content)
        self.assertIn("command='/usr/local/bin/agentic-voice-agent --cursor'", self.content)
        self.assertIn("binding='<Super>F5'", self.content)
        self.assertIn("command='/usr/local/bin/agentic-voice-agent --agent'", self.content)

    def test_blurt_extension_settings(self):
        self.assertIn("[org/gnome/shell/extensions/blurt]", self.content)
        self.assertIn("vad-silence-timeout=1.0", self.content)
        self.assertIn("auto-paste=true", self.content)
        self.assertIn("model-path='/usr/share/agentic/models/whisper/ggml-base.bin'", self.content)

    def test_dconf_compile_syntax(self):
        """Test compiling dconf database with 03-blurt-voice included."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_db = os.path.join(tmp_dir, "test_db")
            dconf_dir = DCONF_PATH.parent
            res = subprocess.run(
                ["dconf", "compile", tmp_db, str(dconf_dir)],
                capture_output=True,
                text=True
            )
            self.assertEqual(res.returncode, 0, f"dconf compilation failed:\n{res.stderr}")
            self.assertTrue(os.path.exists(tmp_db), "dconf output binary must be generated")


class TestGnomeExtensionDeployment(unittest.TestCase):
    """Verifies extension files defined in hook or filesystem match GNOME Shell specifications."""

    def test_extension_definition_in_hook(self):
        content = HOOK_PATH.read_text(encoding="utf-8")
        self.assertIn('"uuid": "blurt@agentic.os"', content)
        self.assertIn("blurt-recording-pulse", content)
        self.assertIn("blurt-processing-spinner", content)
        self.assertIn("St.Icon", content)
        self.assertIn("St.Label", content)

    def test_extension_metadata_schema(self):
        """Extract metadata.json from hook and parse JSON."""
        content = HOOK_PATH.read_text(encoding="utf-8")
        match = re.search(r'cat << \'EOF\' > "\$\{EXT_DIR\}/metadata\.json"\n(.*?)\nEOF', content, re.DOTALL)
        self.assertIsNotNone(match, "metadata.json block not found in hook")
        meta_json = match.group(1)
        data = json.loads(meta_json)
        self.assertEqual(data["uuid"], "blurt@agentic.os")
        self.assertIn("name", data)
        self.assertIn("shell-version", data)
        self.assertIsInstance(data["shell-version"], list)
        self.assertIn("45", data["shell-version"])


class TestVoiceAgentCLI(unittest.TestCase):
    """Verifies agentic-voice-agent command line interface and logic."""

    def test_script_exists_and_executable(self):
        self.assertTrue(VOICE_AGENT_PATH.is_file(), f"Missing {VOICE_AGENT_PATH}")
        self.assertTrue(os.access(VOICE_AGENT_PATH, os.X_OK), f"{VOICE_AGENT_PATH} must be executable")

    def test_help_option(self):
        res = subprocess.run([str(VOICE_AGENT_PATH), "--help"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("--cursor", res.stdout)
        self.assertIn("--agent", res.stdout)
        self.assertIn("--status", res.stdout)
        self.assertIn("--dry-run", res.stdout)
        self.assertIn("--model", res.stdout)

    def test_version_option(self):
        res = subprocess.run([str(VOICE_AGENT_PATH), "--version"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("1.0.0", res.stdout)

    def test_status_json_schema(self):
        res = subprocess.run([str(VOICE_AGENT_PATH), "--status"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertIn("status", data)
        self.assertIn("version", data)
        self.assertIn("audio_recorder", data)
        self.assertIn("whisper", data)
        self.assertIn("text_injection", data)
        self.assertIn("agent_socket", data)
        self.assertIn("vad_silence_timeout", data)
        self.assertEqual(data["vad_silence_timeout"], 1.0)
        self.assertIn("supported_backends", data["audio_recorder"])

    def test_dry_run_cursor_mode(self):
        res = subprocess.run([str(VOICE_AGENT_PATH), "--cursor", "--dry-run"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("[dry-run] Would record audio", res.stdout)
        self.assertIn("[dry-run] Would execute whisper-cpp", res.stdout)
        self.assertIn("[dry-run] Would inject text into active window", res.stdout)

    def test_dry_run_agent_mode(self):
        res = subprocess.run([str(VOICE_AGENT_PATH), "--agent", "--dry-run"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("[dry-run] Would record audio", res.stdout)
        self.assertIn("[dry-run] Would execute whisper-cpp", res.stdout)
        self.assertIn("[dry-run] Would dispatch voice prompt to Pi Agent", res.stdout)

    def test_custom_model_flag(self):
        custom_model = "/tmp/nonexistent-custom-model.bin"
        res = subprocess.run([str(VOICE_AGENT_PATH), "--status", "--model", custom_model], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertEqual(data["whisper"]["model_path"], custom_model)
        self.assertFalse(data["whisper"]["model_exists"])


class TestVoiceAgentIPCDispatch(unittest.TestCase):
    """Tests IPC socket event delivery when --agent is called."""

    def test_socket_dispatch_with_mock_receiver(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sock_path = os.path.join(tmpdir, "agentic.sock")
            received_messages = []
            server_ready = threading.Event()
            stop_server = threading.Event()

            def socket_server():
                server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                server.bind(sock_path)
                server.listen(1)
                server.settimeout(0.2)
                server_ready.set()

                while not stop_server.is_set():
                    try:
                        conn, _ = server.accept()
                        data = conn.recv(4096)
                        if data:
                            received_messages.append(data.decode("utf-8"))
                        conn.close()
                    except socket.timeout:
                        continue
                server.close()

            t = threading.Thread(target=socket_server)
            t.daemon = True
            t.start()
            server_ready.wait(timeout=2.0)

            try:
                # Invoke voice agent with --agent and --text to test direct dispatch
                env = os.environ.copy()
                env["AGENTIC_SOCK"] = sock_path
                res = subprocess.run(
                    [str(VOICE_AGENT_PATH), "--agent", "--text", "Create a python script to parse logs"],
                    capture_output=True,
                    text=True,
                    env=env
                )
                self.assertEqual(res.returncode, 0)
                time.sleep(0.3)

                self.assertGreater(len(received_messages), 0, "Socket server did not receive payload")
                payload = json.loads(received_messages[0].strip())
                self.assertEqual(payload.get("event"), "voice_prompt")
                self.assertEqual(payload.get("source"), "blurt_voice_agent")
                self.assertEqual(payload.get("text"), "Create a python script to parse logs")
            finally:
                stop_server.set()
                t.join(timeout=1.0)


class TestTranscriptionCleaningAndMockPipeline(unittest.TestCase):
    """Tests whisper output regex cleaning and end-to-end transcription handling."""

    def test_transcription_cleaning_timestamps_and_tokens(self):
        from importlib.machinery import SourceFileLoader
        import importlib.util

        loader = SourceFileLoader("agentic_voice_agent", str(VOICE_AGENT_PATH))
        spec = importlib.util.spec_from_loader("agentic_voice_agent", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)

        # Mock whisper-cpp output with timestamps and info headers
        mock_output = (
            "whisper_init: loading model from /usr/share/agentic/models/whisper/ggml-base.bin\n"
            "whisper_model_load: total params = 74.05 M\n"
            "main: processing 'test.wav' (16000 samples, 1.0 sec), 4 threads\n"
            "[00:00:00.000 --> 00:00:02.500]   Hello world from voice engine.\n"
            "[00:00:02.500 --> 00:00:04.000]   [_TT_1] AgenticOS is ready.\n"
            "[BLANK_AUDIO]\n"
        )

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f_wav, \
             tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f_model, \
             tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f_bin:

            f_wav_path = f_wav.name
            f_model_path = f_model.name
            f_bin_path = f_bin.name

            # Create mock executable that outputs whisper log
            f_bin.write(f'#!/bin/sh\ncat << "EOF"\n{mock_output}EOF\n')

        try:
            os.chmod(f_bin_path, stat.S_IRWXU)

            # Patch find_whisper_binary to return our mock script
            orig_finder = mod.find_whisper_binary
            mod.find_whisper_binary = lambda: f_bin_path

            result = mod.run_whisper_transcribe(f_wav_path, f_model_path)
            self.assertEqual(result, "Hello world from voice engine. AgenticOS is ready.")
        finally:
            mod.find_whisper_binary = orig_finder
            for p in [f_wav_path, f_model_path, f_bin_path]:
                if os.path.exists(p):
                    os.remove(p)


if __name__ == "__main__":
    unittest.main()
