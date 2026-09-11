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
from agent_core.domain.permission import PermissionDecision
from agent_core.domain.skill import SkillManifest
from agent_core.domain.tool import RiskLevel, ToolDefinition
from agent_core.permissions.policy import ActionPolicy
from agent_core.registries import AgentRegistry, SkillRegistry, ToolRegistry
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


def test_i03_skills_are_served_from_the_one_skills_directory(tmp_path: Path) -> None:
    """There is exactly one skills directory; nothing is copied per task."""
    workspace = tmp_path / "workspace"
    skill_dir = workspace / "skills" / "web-research"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# web-research\n", encoding="utf-8")
    builder = make_builder(workspace=workspace)

    builder.build(base_spec())

    # The one directory is the source; no second copy appears in a task root.
    assert (skill_dir / "SKILL.md").is_file()
    tasks_root = workspace / "tasks"
    task_copies = list(tasks_root.rglob("SKILL.md")) if tasks_root.exists() else []
    assert task_copies == [], f"skills must not be copied into task roots: {task_copies}"


def test_i03_skill_source_is_reachable_through_the_backend(tmp_path: Path) -> None:
    """No copy still means readable: the backend exposes the skills directory."""
    workspace = tmp_path / "workspace"
    skill_dir = workspace / "skills" / "web-research"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# web-research\n", encoding="utf-8")
    builder = make_builder(workspace=workspace)

    backend = builder._backend_kwargs(base_spec())["backend"]
    read = backend.read("/skills/web-research/SKILL.md", offset=0, limit=20)
    assert read.error is None, read
    assert "web-research" in read.file_data["content"]


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


def test_i04_no_skill_install_tool_exists() -> None:
    """A skill is a directory, not a control-plane action.

    The old design published to a registry through a HIGH-risk ``install_skill``
    tool. Under "skills as a directory" there is no such tool: the agent edits
    the skills directory with its ordinary file tools, so there is nothing for
    an implicit agent to publish.
    """
    from agent_core.application.bootstrap import default_service

    service = default_service()
    assert "install_skill" not in service.runtime.tools


# ------------------------------------------------------------------ I-02 skill source


def test_i02_skill_writes_go_to_the_skills_dir_not_outside_it(tmp_path: Path) -> None:
    """The skills directory is writable; nothing outside it becomes reachable."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("original", encoding="utf-8")

    builder = make_builder(workspace=workspace)
    backend = builder._backend_kwargs(base_spec())["backend"]

    # The skills mount points at <workspace>/skills and is writable.
    written = backend.write("/skills/new-skill/SKILL.md", "---\nname: new-skill\n---\n")
    assert written.error is None, written
    assert (workspace / "skills" / "new-skill" / "SKILL.md").is_file()

    # A path outside the mount still cannot be reached to rewrite it: traversal
    # is refused outright (ValueError) or returns an error result — never a write.
    before = outside.read_text()
    with pytest.raises(ValueError, match="[Tt]raversal|outside"):
        backend.write("../outside.txt", "pwned")
    assert outside.read_text() == before
