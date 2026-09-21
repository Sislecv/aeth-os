#!/usr/bin/env python3
"""
Unit and Integration Tests for AgenticOS Pi Agent & 5 Core System Skills (Task 7)
Verifies:
1. 0070-install-pi-agent.hook.chroot syntax, permissions, and offline fallback resilience.
2. User model configuration template config.json syntax, schema, and direct provider mappings
   (OpenAI, Anthropic, Ollama http://localhost:11434, DeepSeek).
3. 5 Pi Core System Skills structure, SKILL.md metadata, and export of standard Pi tool declarations
   (tools array with name, description, parameters schema, execute handler).
4. Subprocess mock and integration execution of tool invocations across all 5 skills.
"""

import os
import sys
import json
import stat
import shutil
import tempfile
import unittest
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_SCRIPT = REPO_ROOT / "config" / "hooks" / "live" / "0070-install-pi-agent.hook.chroot"
CONFIG_TEMPLATE = REPO_ROOT / "config" / "includes.chroot" / "etc" / "skel" / ".config" / "pi" / "config.json"
SKILLS_DIR = REPO_ROOT / "config" / "includes.chroot" / "etc" / "pi" / "skills"

EXPECTED_SKILLS = {
    "skill-computer-use": [
        "desktop_inspect_tree",
        "desktop_click_element",
        "desktop_type_text",
        "desktop_screenshot",
        "desktop_ghost_switch",
    ],
    "skill-browser-use": [
        "browser_open",
        "browser_snapshot",
        "browser_click",
        "browser_fill",
        "browser_read_markdown",
        "browser_reveal",
    ],
    "skill-agent-memory": [
        "memory_store",
        "memory_query",
        "memory_list",
        "memory_delete",
    ],
    "skill-os-admin": [
        "sys_doctor",
        "sys_wifi_status",
        "sys_wifi_connect",
        "sys_package_info",
        "sys_package_install",
        "sys_zen_mode",
    ],
    "skill-terminal-sync": [
        "terminal_read_pane",
        "terminal_send_command",
        "terminal_new_tab",
    ],
}


class TestPiAgentHook(unittest.TestCase):
    """Verifies hook script permissions, syntax, and fallback mechanisms."""

    def test_hook_script_exists_and_executable(self):
        self.assertTrue(HOOK_SCRIPT.is_file(), f"Hook script not found at {HOOK_SCRIPT}")
        self.assertTrue(os.access(HOOK_SCRIPT, os.X_OK), "Hook script must have executable permission (chmod +x)")

    def test_hook_script_bash_syntax(self):
        proc = subprocess.run(["bash", "-n", str(HOOK_SCRIPT)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, f"Bash syntax check failed:\n{proc.stderr}")

    def test_hook_script_content_specifications(self):
        content = HOOK_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("@earendil-works/pi-coding-agent", content)
        self.assertIn("npm install -g @earendil-works/pi-coding-agent", content)
        self.assertIn("setup_offline_fallback", content)
        self.assertIn("/etc/pi/skills", content)
        self.assertIn("0755", content)
        self.assertIn("/etc/skel/.config/pi", content)
        self.assertIn("config.json", content)
        self.assertIn("ln -sf /etc/pi/skills /etc/skel/.config/pi/skills", content)

    def test_offline_fallback_wrapper_behavior(self):
        """Tests that the fallback bootstrap script executes gracefully without crashing."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_bin = Path(tmp_dir) / "pi"
            # Extract offline bootstrap script from hook
            hook_content = HOOK_SCRIPT.read_text(encoding="utf-8")
            start_marker = "cat << 'EOF' > \"${target_bin}\"\n"
            end_marker = "\nEOF\n"
            self.assertIn(start_marker, hook_content)
            self.assertIn(end_marker, hook_content)
            script_body = hook_content.split(start_marker)[1].split(end_marker)[0]
            test_bin.write_text(script_body, encoding="utf-8")
            test_bin.chmod(0o755)

            # Simulate offline network by mocking curl to fail
            mock_curl = Path(tmp_dir) / "curl"
            mock_curl.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            mock_curl.chmod(0o755)

            # Test running fallback wrapper under offline conditions
            env = {
                **os.environ,
                "PATH": f"{tmp_dir}:{os.environ.get('PATH', '')}",
                "SHELL": "/bin/sh",
            }
            proc = subprocess.run(
                [str(test_bin)],
                capture_output=True,
                text=True,
                input="echo 'fallback shell active'\nexit 0\n",
                env=env,
                timeout=5,
            )
            # Should output notice and enter fallback shell
            combined = proc.stdout + proc.stderr
            self.assertTrue(
                "Pi Agent" in combined or "fallback" in combined or proc.returncode == 0,
                f"Fallback wrapper unexpected output: {combined}",
            )


class TestPiModelConfigTemplate(unittest.TestCase):
    """Verifies direct user model configuration template config.json."""

    def setUp(self):
        self.assertTrue(CONFIG_TEMPLATE.is_file(), f"Missing config template: {CONFIG_TEMPLATE}")
        with open(CONFIG_TEMPLATE, "r", encoding="utf-8") as f:
            self.config = json.load(f)

    def test_valid_json_structure(self):
        self.assertIsInstance(self.config, dict)
        self.assertIn("defaultProvider", self.config)
        self.assertIn("defaultModel", self.config)
        self.assertIn("providers", self.config)

    def test_providers_coverage(self):
        providers = self.config["providers"]
        # Required models in task description: OpenAI, Anthropic, Ollama, DeepSeek
        self.assertIn("ollama", providers)
        self.assertIn("deepseek", providers)
        self.assertIn("anthropic", providers)
        self.assertIn("openai", providers)

    def test_ollama_configuration(self):
        ollama = self.config["providers"]["ollama"]
        self.assertIn("http://localhost:11434", ollama.get("baseUrl", ""))
        self.assertTrue(len(ollama.get("models", [])) > 0)
        model_ids = [m["id"] for m in ollama["models"]]
        self.assertIn("qwen2.5-coder:7b", model_ids)

    def test_deepseek_configuration(self):
        deepseek = self.config["providers"]["deepseek"]
        self.assertIn("deepseek.com", deepseek.get("baseUrl", ""))
        model_ids = [m["id"] for m in deepseek.get("models", [])]
        self.assertTrue(any("deepseek" in mid for mid in model_ids))

    def test_skills_and_extensions_paths(self):
        skills = self.config.get("skills", [])
        extensions = self.config.get("extensions", [])
        self.assertIn("/etc/pi/skills/*", skills)
        self.assertIn("/etc/pi/skills/*/index.ts", extensions)


class TestPiSkillsDeclarations(unittest.TestCase):
    """Tests that all 5 skill directories exist and export standard Pi tool declarations."""

    @classmethod
    def setUpClass(cls):
        # Verify node is installed
        proc = subprocess.run(["node", "-v"], capture_output=True, text=True)
        if proc.returncode != 0:
            raise unittest.SkipTest("Node.js runtime is required for Pi skills tests")

    def inspect_skill_tools(self, skill_name: str):
        skill_dir = SKILLS_DIR / skill_name
        self.assertTrue(skill_dir.is_dir(), f"Missing skill directory: {skill_dir}")

        index_file = skill_dir / "index.ts"
        self.assertTrue(index_file.is_file(), f"Missing index.ts in {skill_dir}")

        pkg_file = skill_dir / "package.json"
        self.assertTrue(pkg_file.is_file(), f"Missing package.json in {skill_dir}")

        skill_md = skill_dir / "SKILL.md"
        self.assertTrue(skill_md.is_file(), f"Missing SKILL.md in {skill_dir}")

        # Introspect exported tools via Node.js
        node_script = f"""
        import {{ tools }} from "{index_file}";
        if (!Array.isArray(tools)) {{
            console.error("Exported 'tools' is not an array");
            process.exit(1);
        }}
        const summary = tools.map(t => ({{
            name: t.name,
            description: t.description,
            parameters: t.parameters,
            hasExecute: typeof t.execute === 'function'
        }}));
        console.log(JSON.stringify(summary));
        """
        proc = subprocess.run(["node", "--input-type=module", "-e", node_script], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, f"Failed to introspect {skill_name}:\n{proc.stderr}")

        tool_defs = json.loads(proc.stdout.strip())
        return tool_defs

    def test_all_five_skills_exported_tools(self):
        for skill_name, expected_tools in EXPECTED_SKILLS.items():
            with self.subTest(skill=skill_name):
                tool_defs = self.inspect_skill_tools(skill_name)
                found_names = [t["name"] for t in tool_defs]

                for expected in expected_tools:
                    self.assertIn(expected, found_names, f"Skill {skill_name} missing tool '{expected}'")

                for t in tool_defs:
                    self.assertTrue(t["hasExecute"], f"Tool {t['name']} must have an execute function")
                    self.assertIsInstance(t["description"], str)
                    self.assertGreater(len(t["description"]), 10)
                    self.assertIsInstance(t["parameters"], dict)
                    self.assertEqual(t["parameters"].get("type"), "object")


class TestPiSkillsExecution(unittest.TestCase):
    """Executes tools via Node CLI to test mock and operational responses."""

    def run_skill_tool(self, skill_name: str, tool_name: str, params: dict, env=None):
        script_path = SKILLS_DIR / skill_name / "index.ts"
        cmd = ["node", str(script_path), tool_name, json.dumps(params)]
        test_env = os.environ.copy()
        if env:
            test_env.update(env)
        proc = subprocess.run(cmd, capture_output=True, text=True, env=test_env, timeout=15)
        self.assertEqual(proc.returncode, 0, f"Error running {tool_name}:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}")
        return json.loads(proc.stdout.strip())

    def test_skill_agent_memory_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_db = str(Path(tmp_dir) / "test_memory.db")
            env = {"AGENTIC_MEMORY_DB": test_db}

            # 1. memory_store
            res = self.run_skill_tool(
                "skill-agent-memory",
                "memory_store",
                {"key": "test_pref", "value": "Use dark mode and Vim keybindings", "tags": "ui,editor", "category": "preferences"},
                env=env,
            )
            self.assertIn("Memory successfully stored", res["content"][0]["text"])

            # 2. memory_query
            res = self.run_skill_tool(
                "skill-agent-memory",
                "memory_query",
                {"query": "Vim"},
                env=env,
            )
            entries = json.loads(res["content"][0]["text"])
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["key"], "test_pref")
            self.assertIn("dark mode", entries[0]["value"])

            # 3. memory_list
            res = self.run_skill_tool(
                "skill-agent-memory",
                "memory_list",
                {"category": "preferences"},
                env=env,
            )
            entries = json.loads(res["content"][0]["text"])
            self.assertEqual(len(entries), 1)

            # 4. memory_delete
            res = self.run_skill_tool(
                "skill-agent-memory",
                "memory_delete",
                {"key": "test_pref"},
                env=env,
            )
            self.assertIn("deleted", res["content"][0]["text"])

            # 5. verify empty
            res = self.run_skill_tool(
                "skill-agent-memory",
                "memory_query",
                {"query": "Vim"},
                env=env,
            )
            entries = json.loads(res["content"][0]["text"])
            self.assertEqual(len(entries), 0)

    def test_skill_computer_use_ghost_switch(self):
        res = self.run_skill_tool("skill-computer-use", "desktop_ghost_switch", {"action": "status"})
        self.assertIn("content", res)
        self.assertTrue(len(res["content"]) > 0)
        self.assertEqual(res["details"]["action"], "status")

    def test_skill_computer_use_click_validation(self):
        res = self.run_skill_tool("skill-computer-use", "desktop_click_element", {})
        self.assertTrue(res.get("isError"))
        self.assertIn("must specify", res["content"][0]["text"])

    def test_skill_computer_use_type_validation(self):
        res = self.run_skill_tool("skill-computer-use", "desktop_type_text", {})
        self.assertTrue(res.get("isError"))
        self.assertIn("must specify 'text'", res["content"][0]["text"])

    def test_skill_browser_use_reveal(self):
        res = self.run_skill_tool("skill-browser-use", "browser_reveal", {"action": "reveal"})
        self.assertIn("content", res)
        self.assertEqual(res["details"]["action"], "--reveal")

    def test_skill_browser_use_missing_args(self):
        res = self.run_skill_tool("skill-browser-use", "browser_open", {})
        self.assertTrue(res.get("isError"))
        self.assertIn("required", res["content"][0]["text"])

        res = self.run_skill_tool("skill-browser-use", "browser_click", {})
        self.assertTrue(res.get("isError"))

        res = self.run_skill_tool("skill-browser-use", "browser_fill", {"target": "@e1"})
        self.assertTrue(res.get("isError"))

    def test_skill_os_admin_sys_doctor(self):
        res = self.run_skill_tool("skill-os-admin", "sys_doctor", {})
        self.assertIn("content", res)
        payload = json.loads(res["content"][0]["text"])
        self.assertIn("system", payload)
        self.assertIn("memory", payload)

    def test_skill_os_admin_zen_mode(self):
        res = self.run_skill_tool("skill-os-admin", "sys_zen_mode", {"action": "status"})
        self.assertIn("content", res)

    def test_skill_os_admin_package_info(self):
        # Inspect a core package that exists on any Debian/Linux system
        res = self.run_skill_tool("skill-os-admin", "sys_package_info", {"package_name": "bash"})
        self.assertIn("content", res)
        self.assertIn("bash", res["content"][0]["text"].lower())

    def test_skill_terminal_sync_send_command(self):
        res = self.run_skill_tool(
            "skill-terminal-sync",
            "terminal_send_command",
            {"command": "git status", "execute": False},
        )
        self.assertIn("content", res)
        self.assertEqual(res["details"]["command"], "git status")
        self.assertFalse(res["details"]["execute"])

    def test_skill_terminal_sync_read_pane(self):
        res = self.run_skill_tool("skill-terminal-sync", "terminal_read_pane", {"lines": 10})
        self.assertIn("content", res)
        self.assertEqual(res["details"]["lines"], 10)


if __name__ == "__main__":
    unittest.main()
