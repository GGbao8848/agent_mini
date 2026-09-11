# One workspace, shared across conversations (design)

Status: implemented (2026-09-11). Supersedes the per-task sandbox folder.

## Problem

Every unbound conversation worked in its own folder,
``workspace/tasks/<task_id>/``. So a repeating task — "generate 10 images with
this script" — re-authored the *same* script in every new conversation: the old
one was in a sibling folder the new conversation could not see. The agent had no
way to reuse its own previous work, and the workspace became N near-identical
trees.

ZCode's shape is simpler and better: one workspace directory, everything lives
in it, every conversation shares it.

## Decision

There is **one working root** for unbound conversations: the workspace directory
itself. Only conversations **bound to a project** get a separate root (that
project's directory), because a project *is* the thing that owns a distinct
workspace.

- `current_task_dir` returns the workspace root when no project is bound — no
  per-task folder is created.
- The workspace root holds the task layout (``inputs/ outputs/ scratch/``) plus
  the shared ``skills/`` and ``uploads/`` directories.
- Files therefore persist across conversations: a script written in one is
  right there in the next. This is the point of the change.

## Consequences

- **Artifacts** are discovered relative to the run root (workspace, or the bound
  project directory). ``skills/`` and ``uploads/`` are excluded — a skill the
  agent edited is a capability, not a deliverable, and uploads are inputs.
  Manifest paths are root-relative.
- **Attachments** already land under ``<workspace>/uploads/<batch>/``, which is
  inside the shared root, so the ``uploads/<batch>/...`` paths in the message
  hint resolve directly. Per-conversation mirroring is gone.
- **Isolation is by project, not by conversation.** Two conversations in the
  same workspace share files (intended). Two projects stay separate. The old
  "concurrent tasks never see each other's files" guarantee applies to
  *projects*, not to unbound conversations running side by side — that is the
  trade the user asked for.
- The environment note now says files persist across conversations and to look
  before re-generating.

## Legacy

Conversations that ran under the old layout keep their files under
``workspace/tasks/<task_id>/``; those directories are left in place (their runs
still reference them). The sidebar/download paths resolve against the current
root, so very old artifacts may no longer resolve — acceptable for pre-release
history.
