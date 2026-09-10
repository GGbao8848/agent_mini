"""Execution policy tests (R24).

The execution envelope used to be implicit: ``sandbox`` was a switch and the
container's network mode was hard-coded to ``host`` inside the argv builder.
These tests pin the policy as the single, honest description of what a
``run_code`` call may touch — and that the argv builder actually follows it.
"""

from __future__ import annotations

from pathlib import Path

from agent_core.builtins.code import build_sandbox_command
from agent_core.config.settings import Settings
from agent_core.execution import ExecutionMode, NetworkMode, build_execution_policy


def settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


# ------------------------------------------------------------------ host


def test_host_policy_declares_no_isolation() -> None:
    policy = build_execution_policy(settings(sandbox="host"))
    assert policy.mode is ExecutionMode.HOST
    assert policy.filesystem.isolated is False
    assert policy.env.host_secrets_visible is True
    assert policy.network.mode is NetworkMode.HOST
    # The policy must not claim enforcement it does not have.
    assert policy.network.enforced is False


def test_host_summary_is_honest() -> None:
    policy = build_execution_policy(settings(sandbox="host"))
    summary = policy.summary()
    assert "宿主机全部文件" in summary["能访问哪些文件"]
    assert "含密钥" in summary["能继承哪些环境变量"]


# ---------------------------------------------------------------- podman


def test_podman_policy_is_isolated_with_limits() -> None:
    policy = build_execution_policy(
        settings(sandbox="podman", sandbox_memory_mb=1024, sandbox_cpus=1.5, sandbox_pids_limit=64)
    )
    assert policy.mode is ExecutionMode.PODMAN
    assert policy.filesystem.isolated is True
    assert policy.env.host_secrets_visible is False
    assert policy.resources.memory_mb == 1024
    assert policy.resources.cpus == 1.5
    assert policy.resources.pids_limit == 64


def test_podman_default_network_is_host_and_documented() -> None:
    policy = build_execution_policy(settings(sandbox="podman"))
    assert policy.network.mode is NetworkMode.HOST
    # host networking cannot filter destinations — say so.
    assert policy.network.enforced is False
    assert "无法按地址过滤" in policy.network.note


def test_podman_network_mode_is_configurable() -> None:
    private = build_execution_policy(settings(sandbox="podman", sandbox_network="private"))
    assert private.network.mode is NetworkMode.PRIVATE
    none = build_execution_policy(settings(sandbox="podman", sandbox_network="none"))
    assert none.network.mode is NetworkMode.NONE
    assert none.network.enforced is True  # nothing can reach anything


def test_podman_env_allowlist_extends_defaults() -> None:
    policy = build_execution_policy(
        settings(sandbox="podman", sandbox_env_allow="MY_TOKEN, OTHER")
    )
    assert "MY_TOKEN" in policy.env.forwarded
    assert "OTHER" in policy.env.forwarded
    assert "HTTP_PROXY" in policy.env.forwarded


def test_podman_network_allow_is_recorded() -> None:
    policy = build_execution_policy(
        settings(sandbox="podman", sandbox_network_allow="10.10.10.146:8001,10.10.10.169:18542")
    )
    assert policy.network.allow == ["10.10.10.146:8001", "10.10.10.169:18542"]


# ------------------------------------------------------ argv follows policy


def test_argv_uses_host_network_by_default(tmp_path: Path) -> None:
    cfg = settings(sandbox="podman", workspace_dir=str(tmp_path))
    argv = build_sandbox_command(tmp_path, cfg, "echo hi", timeout=60.0)
    assert argv[argv.index("--network") + 1] == "host"


def test_argv_uses_private_network_when_configured(tmp_path: Path) -> None:
    cfg = settings(sandbox="podman", sandbox_network="private")
    argv = build_sandbox_command(tmp_path, cfg, "echo hi", timeout=60.0)
    assert argv[argv.index("--network") + 1] == "slirp4netns"


def test_argv_uses_no_network_when_configured(tmp_path: Path) -> None:
    cfg = settings(sandbox="podman", sandbox_network="none")
    argv = build_sandbox_command(tmp_path, cfg, "echo hi", timeout=60.0)
    assert argv[argv.index("--network") + 1] == "none"


def test_argv_forwards_allowlisted_env(tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.setenv("MY_TOKEN", "s3cret")  # type: ignore[attr-defined]
    cfg = settings(sandbox="podman", sandbox_env_allow="MY_TOKEN")
    argv = build_sandbox_command(tmp_path, cfg, "echo hi", timeout=60.0)
    assert "MY_TOKEN=s3cret" in argv


def test_argv_skips_absent_env_names(tmp_path: Path) -> None:
    import os

    os.environ.pop("ABSENT_TOKEN", None)
    cfg = settings(sandbox="podman", sandbox_env_allow="ABSENT_TOKEN")
    argv = build_sandbox_command(tmp_path, cfg, "echo hi", timeout=60.0)
    assert not any(item.startswith("ABSENT_TOKEN=") for item in argv)
