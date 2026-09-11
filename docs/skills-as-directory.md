# Skills as a directory (design)

Status: implementing (2026-09-11).

## Problem

Two identical txt2img tasks (`4341ab90…`, `ab4c6e70…`) both burned their first
4–8 tool calls fighting the same thing: the agent could not open a skill it had
just been told about. Both then abandoned the built-in file tools for
`run_code`, and both tripped over `tmp/` vs `/tmp` when writing a scratch
script. The task succeeded, but every run paid the same tax.

Root causes (see the run traces):

1. **Two contradictory path models in the prompt.** The framework's skill list
   says `read_file("/skills/<id>/SKILL.md")`; the environment note says the
   skill is at the host path `…/workspace/.skills-upload/<id>` and "host 模式
   没有 /skills 挂载点，不要访问 /skills". The file tools *do* serve `/skills/`
   in host mode, so the note sent the agent to a path those tools cannot open.
2. **`tmp/` collides with `/tmp`.** The task root has a real `tmp/` directory
   and the backend renders it as the virtual path `/tmp/x`, indistinguishable
   from the system temp dir. A `write_file("tmp/x")` receipt reads
   `Updated file /tmp/x`; RUN2 then ran `python /tmp/x` and got exit 2.
3. **A skill is not something the agent can operate.** The skill source lives
   outside the task root, mounted read-only; the only write path is the
   `install_skill` tool (HIGH risk, approval-gated), and its relative-path base
   (the workspace root) does not match the agent's cwd (the task dir), so the
   natural `install_skill("my-skill")` looks in the wrong place.

## Decision

A skill is **a directory**, and that directory is the single source of truth —
the model ZCode/Codex use. The agent adds, updates, and deletes skills with its
ordinary file tools; there is no registration step and no version table.

- One skills root: `<workspace_dir>/skills/`.
- Mounted at `/skills/` **writable** for the agent's file tools, and writable in
  `run_code`'s sandbox, so the same path works in both namespaces.
- The registry is *derived*: it scans the root (`sync_from_dir`) at process
  start and at the start of every run. Deleting the directory removes the
  skill; writing `SKILL.md` adds it. Effect lands on the next run's prompt.
- `install_skill` is removed. So are the registry-as-truth vestiges: versioned
  addressing, the enable toggle, and the console write endpoints.

## Deliberately dropped

- **Multi-version skills.** A skill is one directory; `version` is read from the
  SKILL.md frontmatter and shown as metadata, not used as a registry key.
- **The enable toggle.** Presence in the directory means available. Disable by
  removing or renaming the directory. (Keeps the console from becoming a second
  source of truth.)
- **`install_skill` + the console upload/register channels** (already removed;
  this finishes the job).

## Trade-off accepted

The old invariant "running prompts never see a skill mutate" is dropped: the
skills directory is writable during a run. A newly written skill is picked up on
the *next* run (the prompt listing is built at build time), which keeps a single
run self-consistent. Skill directory writes still flow through the normal
filesystem permission rules (the permission-mode gate), so `变更前确认` still
asks before the agent writes one.

## Blast radius

Skill writes now originate in the filesystem layer, so there is no separate
boundary wrapper: `BoundaryBackend` and the `FilesystemPermission` list were
removed once the pre-created read-only layout went away (see
`docs/shared-workspace.md`).
`SkillRegistry` keeps its in-memory API (used by capability tests) but nothing
in production calls `register`; production populates it via `sync_from_dir`.
