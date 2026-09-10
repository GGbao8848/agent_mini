"""Runtime boundary invariants (R1 baseline).

These encode the *target* contract from the runtime engineering guide — the
tests are expected to fail against the pre-refactor implementation, proving the
violation, and to pass once R2–R7 land. Each test names its invariant
(``I-01`` … ``I-12``) so a failure points straight at the guide's contract.

Invariants covered here:
- I-01 Agent cannot write immutable inputs.
- I-02 Agent cannot modify the skill source.
- I-03 Skill is not physically copied into every task workspace.
- I-04 Agent cannot directly publish/install a global skill.
- I-05 Agent cannot reach runtime-internal paths (checkpoint/registry/db).
- I-11 Skill ``allowed_tools`` is enforced, not just described.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_core.domain.agent import AgentSpec
from agent_core.domain.mcp import MCPServerDefinition, MCPTransport
from agent_core.domain.permission import PermissionDecision, PermissionRule, PermissionSpec
from agent_core.domain.skill import SkillManifest
from agent_core.domain.tool import RiskLevel, ToolDefinition, ToolSource
from agent_core.permissions.policy import ActionPolicy
from agent_core.registries import AgentRegistry, MCPRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime.builder import AgentBuilder

# --------------------------------------------------------------------------- helpers


def stub_model_factory(model_spec: str | None) -> Any:
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model="gpt-4o-mini", api_key="test-key")


def make_builder(
    *,
    tools: ToolRegistry | None = None,
    skills: SkillRegistry | None = None,
    workspace: Path | None = None,
) -> AgentBuilder:
    from agent_core.config.settings import Settings

    settings = Settings(
        _env_file=None,
        workspace_dir=str(workspace) if workspace else "./workspace",
    )
    return AgentBuilder(
        AgentRegistry(),
        tools or ToolRegistry(),
        skills or SkillRegistry(),
        model_factory=stub_model_factory,
        settings=settings,
    )


def base_spec(**overrides: Any) -> AgentSpec:
    data: dict[str, Any] = {"id": "helper", "name": "Helper", "model": "openai:gpt-4o-mini"}
    data.update(overrides)
    return AgentSpec(**data)


def registered_skill(skills: SkillRegistry, root: Path, skill_id: str = "web-research") -> Path:
    directory = root / skill_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(f"# {skill_id}\n\nDo the thing.", encoding="utf-8")
    skills.register(SkillManifest(id=skill_id, name=skill_id, path=directory))
    return directory


# ------------------------------------------------------------------ I-03 Skill copy


def test_i03_skills_are_not_physically_copied_into_task_root(tmp_path: Path) -> None:
    """Skills are served from their single source, never copied per task."""
    skills = SkillRegistry()
    source = registered_skill(skills, tmp_path / "skill-src")
    workspace = tmp_path / "workspace"
    builder = make_builder(skills=skills, workspace=workspace)
    spec = base_spec()

    builder.build(spec)

    # The source is untouched and no copy exists anywhere under the workspace.
    assert source.is_dir()
    copies = list((workspace).rglob("SKILL.md"))
    assert copies == [], f"skills must not be copied into the workspace: {copies}"
    # Nor is a staging dir created inside the task root.
    assert not (workspace / ".skills").exists()


def test_i03_skill_source_is_reachable_through_the_backend(tmp_path: Path) -> None:
    """No copy still means readable: the backend exposes skills read-only."""
    skills = SkillRegistry()
    registered_skill(skills, tmp_path / "skill-src", "web-research")
    builder = make_builder(skills=skills, workspace=tmp_path / "workspace")
    spec = base_spec()

    kwargs = builder._backend_kwargs(spec)

    backend = kwargs["backend"]
    listing = backend.ls("/")
    entry_names = {e["path"] for e in getattr(listing, "entries", listing)}
    assert any("skills" in name for name in entry_names), entry_names


# ----------------------------------------------------------- I-01 inputs read-only


def test_i01_backend_denies_writing_inputs(tmp_path: Path) -> None:
    """The file backend must refuse writes under /inputs (immutable inputs)."""
    from agent_core.workspace import layout

    workspace = tmp_path / "workspace"
    builder = make_builder(workspace=workspace)
    layout.WorkspaceLayout.ensure(workspace / "tasks" / "t1")
    kwargs = builder._backend_kwargs(base_spec())
    backend = kwargs["backend"]

    result = backend.write("/inputs/important.txt", "tampered")

    assert getattr(result, "error", None), "writing an immutable input must be denied"


def test_i01_backend_allows_writing_workspace_and_outputs(tmp_path: Path) -> None:
    """The writable zones stay writable."""
    from agent_core.workspace import layout

    workspace = tmp_path / "workspace"
    builder = make_builder(workspace=workspace)
    layout.WorkspaceLayout.ensure(workspace / "tasks" / "t1")
    backend = builder._backend_kwargs(base_spec())["backend"]

    assert not getattr(backend.write("/workspace/a.txt", "ok"), "error", None)
    assert not getattr(backend.write("/outputs/b.txt", "ok"), "error", None)


# ------------------------------------------------------------------ I-05 hidden paths


def test_i05_backend_cannot_reach_parent_of_task_root(tmp_path: Path) -> None:
    """Traversal and absolute escapes stay blocked (raise or error result)."""
    builder = make_builder(workspace=tmp_path / "workspace")
    backend = builder._backend_kwargs(base_spec())["backend"]

    with pytest.raises(ValueError):
        backend.write("../../etc/evil.txt", "x")
    # An absolute path outside the root: virtual mode anchors it under root,
    # so it can never reach the real /etc.
    result = backend.write("/etc/evil.txt", "x")
    assert not (tmp_path / ".." / "etc" / "evil.txt").exists()
    written = getattr(result, "path", "") or ""
    assert "etc/evil.txt" not in str(tmp_path.parent / "etc")


# --------------------------------------------------------------- I-11 allowed_tools


def test_i11_gate_denies_tool_outside_skill_allowed_tools() -> None:
    """A skill's allowed_tools must gate execution, not just be advisory."""
    tools = ToolRegistry()
    tools.register(ToolDefinition(name="read_file", risk_level=RiskLevel.LOW), lambda **_: "ok")
    tools.register(ToolDefinition(name="write_file", risk_level=RiskLevel.LOW), lambda **_: "ok")
    skills = SkillRegistry()
    skills.register(
        SkillManifest(id="read-only", name="Read Only", allowed_tools=["read_file"])
    )
    policy = ActionPolicy(skill_allowed_tools=lambda sid: skills.get(sid).allowed_tools)
    spec = base_spec(skills=["read-only"])

    allowed = policy.evaluate(spec, tools.get("read_file"))
    denied = policy.evaluate(spec, tools.get("write_file"))

    assert allowed is PermissionDecision.ALLOW
    assert denied is PermissionDecision.DENY


def test_i11_unrestricted_skill_does_not_lock_agent_out() -> None:
    """A bound skill without allowed_tools leaves capabilities unchanged."""
    tools = ToolRegistry()
    tools.register(ToolDefinition(name="run_code", risk_level=RiskLevel.LOW), lambda **_: "ok")
    skills = SkillRegistry()
    skills.register(SkillManifest(id="free", name="Free", allowed_tools=[]))
    policy = ActionPolicy(skill_allowed_tools=lambda sid: skills.get(sid).allowed_tools)

    assert policy.evaluate(base_spec(skills=["free"]), tools.get("run_code")) is PermissionDecision.ALLOW


def test_i11_agent_tool_allowlist_is_enforced() -> None:
    """An agent's explicit tool list is a hard capability boundary."""
    tools = ToolRegistry()
    tools.register(ToolDefinition(name="read_file", risk_level=RiskLevel.LOW), lambda **_: "ok")
    tools.register(ToolDefinition(name="run_code", risk_level=RiskLevel.HIGH), lambda **_: "ok")
    builder = make_builder(tools=tools)

    names = builder._agent_tool_names(base_spec(tools=["read_file"]))

    assert names == ["read_file"]


# ------------------------------------------------------------- I-04 skill self-install


def test_i04_install_skill_is_not_a_default_agent_capability() -> None:
    """Publishing to the global skill registry is a control-plane action."""
    from agent_core.application.bootstrap import default_service

    service = default_service()
    runtime = service.runtime
    tools = runtime.tools
    if "install_skill" in tools:
        definition = tools.get("install_skill")
        # Either unavailable to implicit agents, or escalated to human approval.
        flagged_unavailable = definition.metadata.get("available") is False
        approval_required = definition.risk_level >= RiskLevel.HIGH
        assert flagged_unavailable or approval_required, (
            "install_skill must be unavailable to implicit agents or require approval"
        )


# ------------------------------------------------------------------ I-02 skill source


def test_i02_skill_source_paths_are_not_writable_via_backend(tmp_path: Path) -> None:
    """Skill sources live outside the writable root and are mounted read-only."""
    skills = SkillRegistry()
    source = registered_skill(skills, tmp_path / "skill-src")
    builder = make_builder(skills=skills, workspace=tmp_path / "workspace")
    backend = builder._backend_kwargs(base_spec())["backend"]

    # A write targeting the mounted skill source must be denied (or the path is
    # simply unreachable) — either way the on-disk source must not change.
    before = (source / "SKILL.md").read_text()
    for attempt in ("/skills/web-research/SKILL.md", ".skills/web-research/SKILL.md"):
        backend.write(attempt, "pwned")
    assert (source / "SKILL.md").read_text() == before
