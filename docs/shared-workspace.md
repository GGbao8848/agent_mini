# Workspace: a container of working folders (design)

Status: implemented (2026-09-11).

## Shape

```
<workspace_dir>/                the workspace is a container, not a working dir
├── default/                    working folder for conversations not bound to a project
│   └── (whatever the agent creates)
├── <project-dir>/              a bound project works here (its own folder)
├── skills/                     global skills (one dir per skill) — outside any working folder
└── uploads/<batch>/            attachment staging — outside any working folder
```

This mirrors ZCode (``…/.zcode/workspace/default``): one folder per group, named.

## Decision

A conversation's **working folder** is the bound project's directory, or the
workspace's ``default`` folder otherwise. The file tools are rooted at that
folder and present it as the virtual root ``/``.

**Nothing is pre-created inside a working folder.** An earlier iteration laid
out ``inputs/ outputs/ scratch/ workspace/`` and made ``/inputs`` read-only; that
was over-design — no code ever wrote to those directories, they only imposed a
structure the agent then had to work around. A working folder is handed over
empty and the agent decides how to organize it.

``skills/`` and ``uploads/`` stay at the workspace **root** — siblings of the
working folders — because they are global (skills) and pre-run staging (uploads),
not per-conversation content.

## Consequences

- Files persist across conversations inside a group (``default``): a script
  written in one conversation is there in the next.
- Artifacts are discovered relative to the working folder; only ``uploads/`` is
  excluded (a mirrored attachment is not a deliverable). Everything else in the
  folder counts as a deliverable candidate.
- Attachments are staged at ``<workspace>/uploads/<batch>/`` (outside the working
  folder) and **mirrored** into the working folder so the message's
  ``uploads/<batch>/...`` hint resolves against the file tools' root.
- No filesystem read-only zones remain: the agent may write anywhere under its
  working folder (and under ``/skills``). The earlier ``/inputs`` immutability
  invariant was removed with the layout that created it.
- Isolation is by group (project vs default), not by conversation.

## Legacy

Conversations that ran under earlier layouts keep their files under
``workspace/tasks/<task_id>/`` (per-task) — archived to
``.db_backup/tasks-per-conversation-archive-20260911``. Very old artifact
download links may no longer resolve; acceptable for pre-release history.
