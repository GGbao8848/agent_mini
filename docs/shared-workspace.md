# Workspace as a container of working folders (design)

Status: implemented (2026-09-11). Supersedes the per-task sandbox folder.

## Shape

```
<workspace_dir>/                the workspace is a container, not a working dir
├── default/                    working folder for conversations not bound to a project
│   ├── inputs/                 read-only: user-provided material (attachments)
│   ├── workspace/              agent scratch space
│   ├── outputs/                deliverables
│   ├── scratch/                ephemeral scratch (not "tmp" — see below)
│   └── uploads/                mirrored attachments (a copy of the staged batch)
├── <project-dir>/              a bound project works here (its own folder)
├── skills/                     global skills (one dir per skill) — outside any working folder
└── uploads/<batch>/            attachment staging — outside any working folder
```

This mirrors how ZCode lays it out (``…/.zcode/workspace/default``): one folder
per group, named, with ``default`` holding everything ungrouped.

## Decision

A conversation's **working folder** is:

- the bound project's directory, when the conversation is bound to a project; or
- the workspace's ``default`` folder, otherwise.

The agent's file tools are rooted at the working folder, presented as the
virtual root ``/``. ``skills/`` and the ``uploads/`` staging area live at the
workspace **root** — siblings of the working folders, never inside one — because
they are global (skills) and pre-run staging (uploads).

## Why not just the workspace root

The previous iteration made the workspace root itself the working folder. That
works, but it conflates "the container" with "a working folder": global
``skills/`` and staging ``uploads/`` got mixed in with deliverables, and there
was no place to put a *second* group later. A named ``default`` folder keeps the
container clean and leaves room for more groups (projects already are groups).

## Consequences

- Files persist across conversations inside ``default`` (the point of the
  change): a script written in one conversation is there in the next.
- Artifacts are discovered relative to the working folder; only ``uploads/`` is
  excluded (a mirrored attachment is not a deliverable). ``inputs/`` and
  ``outputs/`` deliberately still count.
- Attachments are staged at ``<workspace>/uploads/<batch>/`` (outside the working
  folder) and **mirrored** into the working folder so the message's
  ``uploads/<batch>/...`` hint resolves against the file tools' root.
- Isolation is by group (project vs default), not by conversation. Two unbound
  conversations share ``default``; two projects stay separate.

## Legacy

Conversations that ran under the earlier layouts keep their files under
``workspace/tasks/<task_id>/`` (per-task) — archived to
``.db_backup/tasks-per-conversation-archive-20260911``. Very old artifact
download links may no longer resolve; acceptable for pre-release history.
