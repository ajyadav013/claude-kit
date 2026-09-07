"""Safe native-host plugin lifecycle smokes with fully isolated user state."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CODEX_PLUGIN_RELATIVE = Path("providers/codex/claude-kit")
CODEX_PLUGIN_ROOT = REPO_ROOT / CODEX_PLUGIN_RELATIVE
PLUGIN_DIRECTORIES = (
    "agents",
    "skills",
    "rules",
    "hooks",
    "commands",
    ".claude-plugin",
    "providers",
)
PLUGIN_FILES = ("AGENTS.md", ".agents/plugins/marketplace.json")
PLUGIN_ID = "claude-kit@claude-kit"


def _json(relative: str) -> dict:
    return json.loads((REPO_ROOT / relative).read_text(encoding="utf-8"))


def _stage_plugin(tmp_path: Path) -> Path:
    plugin_root = tmp_path / "plugin"
    plugin_root.mkdir()
    for relative in PLUGIN_DIRECTORIES:
        shutil.copytree(REPO_ROOT / relative, plugin_root / relative)
    for relative in PLUGIN_FILES:
        destination = plugin_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, destination)
    return plugin_root


def _isolated_host_env(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    claude_config = tmp_path / "claude-config"
    codex_home = tmp_path / "codex-home"
    xdg_config = tmp_path / "xdg-config"
    for directory in (home, claude_config, codex_home, xdg_config):
        directory.mkdir()

    environment = os.environ.copy()
    for key in (
        "ANTHROPIC_API_KEY",
        "CLAUDE_CONFIG_DIR",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_PLUGIN_ROOT",
        "CLAUDE_PLUGIN_DATA",
        "CODEX_API_KEY",
        "CODEX_HOME",
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "OPENAI_API_KEY",
        "PLUGIN_ROOT",
        "PLUGIN_DATA",
        "XDG_CONFIG_HOME",
    ):
        environment.pop(key, None)
    environment.update(
        {
            "HOME": str(home),
            "CLAUDE_CONFIG_DIR": str(claude_config),
            "CODEX_HOME": str(codex_home),
            "XDG_CONFIG_HOME": str(xdg_config),
            "NO_COLOR": "1",
        }
    )
    return environment


def _run_host(
    command: list[str], *, cwd: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"host command failed ({result.returncode}): {' '.join(command)}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result


def _require_host(executable_name: str, required_help: tuple[str, ...]) -> str:
    executable = shutil.which(executable_name)
    if executable is None:
        pytest.skip(f"{executable_name} host CLI is not installed")
    result = subprocess.run(
        [executable, "plugin", "--help"],
        stdin=subprocess.DEVNULL,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    help_text = result.stdout + result.stderr
    if result.returncode != 0 or not all(item in help_text for item in required_help):
        pytest.skip(
            f"installed {executable_name} CLI lacks the plugin lifecycle commands"
        )
    return executable


def _require_official_plugin_validator() -> Path:
    configured = os.environ.get("CODEX_PLUGIN_VALIDATOR")
    if configured:
        validator = Path(configured).expanduser()
        assert validator.is_file(), (
            f"CODEX_PLUGIN_VALIDATOR does not name a file: {validator}"
        )
        return validator

    validator = (
        Path.home() / ".codex/skills/.system/plugin-creator/scripts/validate_plugin.py"
    )
    if not validator.is_file():
        pytest.skip("official Codex plugin-creator validator is not installed")
    return validator


def _validate_codex_plugin(
    plugin_root: Path,
    *,
    validator: Path,
    cwd: Path,
    env: dict[str, str],
) -> None:
    result = _run_host(
        [sys.executable, str(validator), str(plugin_root)],
        cwd=cwd,
        env=env,
    )
    assert "Plugin validation passed" in result.stdout


def _codex_app_server_inventory(
    codex: str,
    *,
    cwd: Path,
    env: dict[str, str],
    marketplace_file: Path,
) -> dict[int, dict[str, Any]]:
    """Read native skill/hook inventories over Codex's public app-server protocol."""
    process = subprocess.Popen(
        [codex, "app-server", "--stdio"],
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    messages: queue.Queue[Any] = queue.Queue()
    stderr_lines: list[str] = []

    def read_stdout() -> None:
        try:
            for line in process.stdout:
                messages.put(json.loads(line))
        except BaseException as exc:  # pragma: no cover - diagnostic path
            messages.put(exc)
        finally:
            messages.put(None)

    def read_stderr() -> None:
        stderr_lines.extend(process.stderr.readlines())

    stdout_thread = threading.Thread(target=read_stdout, daemon=True)
    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    def send(document: dict[str, Any]) -> None:
        process.stdin.write(json.dumps(document, separators=(",", ":")) + "\n")
        process.stdin.flush()

    def receive(request_id: int) -> dict[str, Any]:
        while True:
            try:
                message = messages.get(timeout=30)
            except queue.Empty:
                pytest.fail(
                    f"Codex app-server timed out waiting for request {request_id}; "
                    f"stderr={''.join(stderr_lines)}"
                )
            if message is None:
                pytest.fail(
                    f"Codex app-server closed before request {request_id}; "
                    f"stderr={''.join(stderr_lines)}"
                )
            if isinstance(message, BaseException):
                raise AssertionError(
                    "failed to decode Codex app-server output"
                ) from message
            if message.get("id") != request_id:
                continue
            assert "error" not in message, message
            return message["result"]

    responses: dict[int, dict[str, Any]] = {}
    try:
        send(
            {
                "method": "initialize",
                "id": 1,
                "params": {
                    "clientInfo": {"name": "claude-kit-conformance", "version": "1"},
                    "capabilities": {"experimentalApi": True},
                },
            }
        )
        responses[1] = receive(1)
        send({"method": "initialized"})
        send(
            {
                "method": "skills/list",
                "id": 2,
                "params": {"cwds": [str(cwd)], "forceReload": True},
            }
        )
        responses[2] = receive(2)
        send({"method": "hooks/list", "id": 3, "params": {"cwds": [str(cwd)]}})
        responses[3] = receive(3)
        send(
            {
                "method": "plugin/read",
                "id": 4,
                "params": {
                    "pluginName": "claude-kit",
                    "marketplacePath": str(marketplace_file.resolve()),
                    "remoteMarketplaceName": None,
                },
            }
        )
        responses[4] = receive(4)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive cleanup
            process.kill()
            process.wait(timeout=5)
        stdout_thread.join(timeout=1)
        stderr_thread.join(timeout=1)
    return responses


def test_provider_manifests_define_one_safe_local_selector() -> None:
    """Keep deterministic coverage when neither native host CLI is installed."""

    claude_manifest = _json(".claude-plugin/plugin.json")
    claude_marketplace = _json(".claude-plugin/marketplace.json")
    codex_manifest = _json("providers/codex/claude-kit/.codex-plugin/plugin.json")
    codex_marketplace = _json(".agents/plugins/marketplace.json")

    claude_entry = claude_marketplace["plugins"]
    codex_entry = codex_marketplace["plugins"]
    assert len(claude_entry) == len(codex_entry) == 1
    assert claude_entry[0]["name"] == codex_entry[0]["name"] == "claude-kit"
    assert claude_entry[0]["source"] == "./"
    assert codex_entry[0]["source"] == {
        "source": "local",
        "path": "./providers/codex/claude-kit",
    }
    assert codex_entry[0]["policy"] == {
        "installation": "AVAILABLE",
        "authentication": "ON_USE",
    }
    assert claude_manifest["version"] == claude_entry[0]["version"]
    assert claude_manifest["version"] == codex_manifest["version"]
    assert codex_manifest["skills"] == "./skills/"
    assert not (REPO_ROOT / ".codex-plugin/plugin.json").exists()


def test_claude_native_plugin_validate_install_list_remove(tmp_path: Path) -> None:
    """Exercise the complete non-credentialed Claude plugin lifecycle when available."""

    claude = _require_host(
        "claude", ("validate", "install", "list", "uninstall", "marketplace")
    )
    plugin_root = _stage_plugin(tmp_path)
    environment = _isolated_host_env(tmp_path)

    _run_host(
        [claude, "plugin", "validate", str(plugin_root), "--strict"],
        cwd=tmp_path,
        env=environment,
    )
    _run_host(
        [claude, "plugin", "marketplace", "add", str(plugin_root)],
        cwd=tmp_path,
        env=environment,
    )
    marketplaces = json.loads(
        _run_host(
            [claude, "plugin", "marketplace", "list", "--json"],
            cwd=tmp_path,
            env=environment,
        ).stdout
    )
    assert [entry["name"] for entry in marketplaces] == ["claude-kit"]

    available = json.loads(
        _run_host(
            [claude, "plugin", "list", "--available", "--json"],
            cwd=tmp_path,
            env=environment,
        ).stdout
    )
    assert [entry["pluginId"] for entry in available["available"]] == [PLUGIN_ID]
    _run_host(
        [claude, "plugin", "install", PLUGIN_ID, "--scope", "user"],
        cwd=tmp_path,
        env=environment,
    )
    installed = json.loads(
        _run_host(
            [claude, "plugin", "list", "--json"],
            cwd=tmp_path,
            env=environment,
        ).stdout
    )
    assert [entry["id"] for entry in installed] == [PLUGIN_ID]
    assert (
        Path(installed[0]["installPath"])
        .resolve()
        .is_relative_to(Path(environment["CLAUDE_CONFIG_DIR"]).resolve())
    )

    _run_host(
        [
            claude,
            "plugin",
            "uninstall",
            PLUGIN_ID,
            "--scope",
            "user",
        ],
        cwd=tmp_path,
        env=environment,
    )
    assert (
        json.loads(
            _run_host(
                [claude, "plugin", "list", "--json"],
                cwd=tmp_path,
                env=environment,
            ).stdout
        )
        == []
    )
    _run_host(
        [claude, "plugin", "marketplace", "remove", "claude-kit"],
        cwd=tmp_path,
        env=environment,
    )
    remaining_marketplaces = json.loads(
        _run_host(
            [claude, "plugin", "marketplace", "list", "--json"],
            cwd=tmp_path,
            env=environment,
        ).stdout
    )
    assert "claude-kit" not in {entry["name"] for entry in remaining_marketplaces}


def test_codex_native_plugin_add_content_list_remove(tmp_path: Path) -> None:
    """Exercise the full non-credentialed Codex plugin lifecycle."""

    codex = _require_host("codex", ("add", "list", "remove", "marketplace"))
    validator = _require_official_plugin_validator()
    marketplace_root = _stage_plugin(tmp_path)
    staged_plugin_root = marketplace_root / CODEX_PLUGIN_RELATIVE
    environment = _isolated_host_env(tmp_path)
    _validate_codex_plugin(
        CODEX_PLUGIN_ROOT,
        validator=validator,
        cwd=tmp_path,
        env=environment,
    )
    _validate_codex_plugin(
        staged_plugin_root,
        validator=validator,
        cwd=tmp_path,
        env=environment,
    )

    added = json.loads(
        _run_host(
            [
                codex,
                "plugin",
                "marketplace",
                "add",
                str(marketplace_root),
                "--json",
            ],
            cwd=tmp_path,
            env=environment,
        ).stdout
    )
    assert added["marketplaceName"] == "claude-kit"
    assert Path(added["installedRoot"]).resolve() == marketplace_root.resolve()

    marketplaces = json.loads(
        _run_host(
            [codex, "plugin", "marketplace", "list", "--json"],
            cwd=tmp_path,
            env=environment,
        ).stdout
    )
    assert [entry["name"] for entry in marketplaces["marketplaces"]] == ["claude-kit"]
    available = json.loads(
        _run_host(
            [codex, "plugin", "list", "--available", "--json"],
            cwd=tmp_path,
            env=environment,
        ).stdout
    )
    assert [entry["pluginId"] for entry in available["available"]] == [PLUGIN_ID]
    assert available["available"][0]["installPolicy"] == "AVAILABLE"
    assert available["available"][0]["authPolicy"] == "ON_USE"

    added_plugin = json.loads(
        _run_host(
            [codex, "plugin", "add", PLUGIN_ID, "--json"],
            cwd=tmp_path,
            env=environment,
        ).stdout
    )
    assert added_plugin["pluginId"] == PLUGIN_ID
    assert added_plugin["authPolicy"] == "ON_USE"
    installed_path = Path(added_plugin["installedPath"]).resolve()
    assert installed_path.is_relative_to(Path(environment["CODEX_HOME"]).resolve())
    for relative in (
        ".codex-plugin/plugin.json",
        "hooks/hooks.json",
        "skills/sdlc/SKILL.md",
    ):
        assert (installed_path / relative).is_file(), relative
    assert not (installed_path / "AGENTS.md").exists()
    assert not (installed_path / ".claude-plugin").exists()
    _validate_codex_plugin(
        installed_path,
        validator=validator,
        cwd=tmp_path,
        env=environment,
    )

    inventory = _codex_app_server_inventory(
        codex,
        cwd=tmp_path,
        env=environment,
        marketplace_file=marketplace_root / ".agents/plugins/marketplace.json",
    )
    skill_entry = next(
        entry
        for entry in inventory[2]["data"]
        if Path(entry["cwd"]).resolve() == tmp_path.resolve()
    )
    assert skill_entry["errors"] == []
    installed_skills = [
        skill
        for skill in skill_entry["skills"]
        if Path(skill["path"]).resolve().is_relative_to(installed_path)
    ]
    expected_skill_names = {
        f"claude-kit:{path.parent.name}"
        for path in staged_plugin_root.glob("skills/*/SKILL.md")
    }
    assert len(expected_skill_names) == 127
    assert {skill["name"] for skill in installed_skills} == expected_skill_names
    assert len(installed_skills) == len(expected_skill_names)
    assert all(skill["enabled"] for skill in installed_skills)

    hook_document = json.loads(
        (staged_plugin_root / "hooks/hooks.json").read_text(encoding="utf-8")
    )
    expected_hook_count = sum(
        len(group["hooks"])
        for groups in hook_document["hooks"].values()
        for group in groups
    )
    assert expected_hook_count == 16
    hook_entry = next(
        entry
        for entry in inventory[3]["data"]
        if Path(entry["cwd"]).resolve() == tmp_path.resolve()
    )
    assert hook_entry["errors"] == []
    installed_hooks = [
        hook for hook in hook_entry["hooks"] if hook.get("pluginId") == PLUGIN_ID
    ]
    assert len(installed_hooks) == expected_hook_count
    assert all(hook["enabled"] for hook in installed_hooks)
    assert all(hook["source"] == "plugin" for hook in installed_hooks)

    plugin_detail = inventory[4]["plugin"]
    assert {skill["name"] for skill in plugin_detail["skills"]} == (
        expected_skill_names
    )
    assert len(plugin_detail["hooks"]) == expected_hook_count

    installed = json.loads(
        _run_host(
            [codex, "plugin", "list", "--json"],
            cwd=tmp_path,
            env=environment,
        ).stdout
    )
    assert [entry["pluginId"] for entry in installed["installed"]] == [PLUGIN_ID]
    assert installed["installed"][0]["installed"] is True
    assert installed["installed"][0]["authPolicy"] == "ON_USE"

    removed_plugin = json.loads(
        _run_host(
            [codex, "plugin", "remove", PLUGIN_ID, "--json"],
            cwd=tmp_path,
            env=environment,
        ).stdout
    )
    assert removed_plugin["pluginId"] == PLUGIN_ID
    after_remove = json.loads(
        _run_host(
            [codex, "plugin", "list", "--json"],
            cwd=tmp_path,
            env=environment,
        ).stdout
    )
    assert after_remove["installed"] == []

    removed = json.loads(
        _run_host(
            [
                codex,
                "plugin",
                "marketplace",
                "remove",
                "claude-kit",
                "--json",
            ],
            cwd=tmp_path,
            env=environment,
        ).stdout
    )
    assert removed == {"marketplaceName": "claude-kit", "installedRoot": None}
    remaining_marketplaces = json.loads(
        _run_host(
            [codex, "plugin", "marketplace", "list", "--json"],
            cwd=tmp_path,
            env=environment,
        ).stdout
    )
    assert "claude-kit" not in {
        entry["name"] for entry in remaining_marketplaces["marketplaces"]
    }
