"""Built-in ``install_skill`` tool: register a skill directory into the SkillRegistry.

Skills are a shared pool — anything registered is loaded for every agent on
the next run (no per-agent binding). This tool is the *agent-facing* side of
that: when the avatar authors a skill in the workspace (writes a ``SKILL.md``
plus optional assets via its file tools / run_code), it calls this tool to
make the skill real. Without it the files are inert — they never reach the
SkillRegistry, so the console's skill list and the next run's skill staging
both ignore them.

The directory must live inside the workspace (the sandbox's ``/work`` mount
is the same directory, so files written there resolve to workspace paths).
Validation mirrors the console's zip-upload path: a ``SKILL.md`` must exist
and its frontmatter must parse to a sane id/name.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from agent_core.config.settings import get_settings
from agent_core.domain.skill import SkillManifest
from agent_core.domain.tool import ToolDefinition, ToolSource
from agent_core.errors.exceptions import RegistryError, ToolError

if TYPE_CHECKING:
    from agent_core.application.service import AgentCoreService

INSTALL_SKILL_TOOL = "install_skill"

# Skill ids are registry keys and directory names: keep them filesystem-safe.
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

_DESCRIPTION = (
    "Register a skill directory into the skill registry so it becomes available "
    "to every agent on the next run. Use this AFTER you have written a skill "
    "directory (containing SKILL.md) inside the workspace. Pass the workspace-relative "
    "path, e.g. 'my-skill' or 'skills/my-skill'. The skill id is read from the "
    "SKILL.md frontmatter. Re-registering the same id+version fails; register a "
    "new version or omit to let the agent pick."
)


def _parse_frontmatter(text: bytes) -> dict[str, Any]:
    """Parse the YAML frontmatter block of a SKILL.md (empty dict if absent)."""
    try:
        raw = text.decode("utf-8")
    except UnicodeDecodeError:
        return {}
    if not raw.startswith("---"):
        return {}
    body: list[str] = []
    for line in raw.splitlines()[1:]:
        if line.strip() == "---":
            break
        body.append(line)
    try:
        parsed = yaml.safe_load("\n".join(body))
    except yaml.YAMLError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def make_install_skill(service: AgentCoreService) -> tuple[ToolDefinition, Any]:
    """Handler bound to the service's SkillRegistry."""

    async def install_skill(path: str, version: str = "0.1.0") -> str:
        workspace = Path(get_settings().workspace_dir).resolve()
        # Accept both absolute (inside workspace) and workspace-relative paths.
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = workspace / candidate
        skill_dir = candidate.resolve()
        if not skill_dir.is_relative_to(workspace):
            raise ToolError(
                f"Skill directory '{path}' is outside the workspace; "
                "write skills inside the workspace first."
            )
        md_path = skill_dir / "SKILL.md"
        if not md_path.is_file():
            raise ToolError(
                f"No SKILL.md at '{skill_dir}'; a skill directory needs a SKILL.md "
                "with YAML frontmatter (name + description)."
            )
        try:
            raw = md_path.read_text("utf-8")
        except UnicodeDecodeError as exc:
            raise ToolError(f"SKILL.md is not valid UTF-8: {exc}") from exc
        frontmatter = _parse_frontmatter(raw.encode("utf-8"))
        skill_id = str(frontmatter.get("name") or "").strip()
        if not skill_id or not _SAFE_ID.match(skill_id):
            raise ToolError(
                "SKILL.md frontmatter must declare a valid 'name' "
                "(letters/digits/dot/dash/underscore)."
            )
        name = str(frontmatter.get("name") or skill_id).strip() or skill_id
        description = str(frontmatter.get("description") or "").strip()
        manifest = SkillManifest(
            id=skill_id,
            name=name,
            version=version,
            description=description,
            path=skill_dir,
        )
        registry = service.runtime.skills
        try:
            registry.register(manifest)
        except RegistryError as exc:
            if "already registered" in exc.message:
                raise ToolError(
                    f"Skill '{skill_id}' version '{version}' is already registered. "
                    "Pick a different version, or update the existing skill."
                ) from exc
            raise
        return (
            f"Skill '{skill_id}' v{version} installed and registered. "
            f"It is now available to every agent on the next run. "
            f"(path: {skill_dir}, description: {description[:120]})"
        )

    definition = ToolDefinition(
        name=INSTALL_SKILL_TOOL,
        description=_DESCRIPTION,
        source=ToolSource.INTERNAL,
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Workspace-relative (or absolute-in-workspace) path "
                    "to the skill directory containing SKILL.md",
                },
                "version": {
                    "type": "string",
                    "description": "Version to register (default 0.1.0)",
                },
            },
            "required": ["path"],
        },
        metadata={"builtin": True, "available": True},
    )
    return definition, install_skill
