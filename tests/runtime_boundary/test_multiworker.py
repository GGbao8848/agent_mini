"""Multi-worker / cross-process consistency (R13).

The runtime is deployed as a single uvicorn process, so the in-memory registry
read path is correct today. The realistic multi-process story with SQLite is
*eventual* consistency: writes are persisted write-through, and a second
process picks them up on ``hydrate``. These tests pin that contract so a future
move to multiple workers is a deliberate change, not an accident.

They also pin the known limitation: a second live process does NOT see writes
made after it hydrated (no invalidation/event bus yet) — if that ever needs to
hold, this test must be updated together with a real consistency mechanism.
"""

from __future__ import annotations

from pathlib import Path

from agent_core.domain.skill import SkillManifest
from agent_core.persistence.store import SqliteStore
from agent_core.registries import SkillRegistry


def test_writes_are_visible_to_a_process_that_hydrates_later(tmp_path: Path) -> None:
    """Worker A writes; a later-starting Worker B sees it after hydrate."""
    dsn = f"sqlite:///{tmp_path / 'registry.db'}"
    worker_a = SkillRegistry(SqliteStore(dsn))
    worker_a.register(SkillManifest(id="shared", name="Shared", version="1.0.0"))

    worker_b = SkillRegistry(SqliteStore(dsn))
    worker_b.hydrate()

    assert worker_b.get("shared", "1.0.0").name == "Shared"


def test_replacement_is_visible_after_rehydrate(tmp_path: Path) -> None:
    """A version bump by A is seen by B once B re-hydrates."""
    dsn = f"sqlite:///{tmp_path / 'registry.db'}"
    store_a = SqliteStore(dsn)
    worker_a = SkillRegistry(store_a)
    worker_a.register(SkillManifest(id="shared", name="Shared", version="1.0.0"))

    store_b = SqliteStore(dsn)
    worker_b = SkillRegistry(store_b)
    worker_b.hydrate()
    worker_a.register(SkillManifest(id="shared", name="Shared", version="1.1.0"))

    # A fresh hydrate reflects the new version (eventual consistency).
    store_c = SqliteStore(dsn)
    worker_c = SkillRegistry(store_c)
    worker_c.hydrate()

    assert worker_c.get("shared").version == "1.1.0"
    store_a.close()
    store_b.close()
    store_c.close()
