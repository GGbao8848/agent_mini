"""Artifact contract invariants (R8 / I-06).

ART-001: a claimed artifact carries the explicit contract — id, path, size,
mime type and content hash.
ART-003 / I-06: the contract is independent of the workspace scan; a later
directory listing must not clobber the explicit metadata.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from agent_core import artifacts


def test_claimed_artifact_carries_explicit_contract(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    task_id = "t1"
    target = workspace / "outputs" / "report.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = b"hello artifact"
    target.write_bytes(payload)

    artifacts.register_artifact(workspace, task_id, target)
    claims = artifacts.claimed_artifacts(task_id)

    assert len(claims) == 1
    record = claims[0]
    assert record["artifact_id"] == f"{task_id}:outputs/report.txt"
    assert record["path"] == "outputs/report.txt"
    assert record["size"] == len(payload)
    assert record["mime_type"] == "text/plain"
    assert record["sha256"] == hashlib.sha256(payload).hexdigest()
    artifacts.clear_claims(task_id)


def test_artifact_outside_root_is_not_claimable(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    stray = tmp_path / "elsewhere.txt"
    stray.write_text("nope")

    artifacts.register_artifact(workspace, "t1", stray)

    assert artifacts.claimed_artifacts("t1") == []


def test_scan_does_not_overwrite_explicit_claim(tmp_path: Path) -> None:
    """The contract survives a scan of the same path (I-06)."""
    workspace = tmp_path / "workspace"
    task_id = "t1"
    target = workspace / "outputs" / "result.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("data")

    artifacts.register_artifact(workspace, task_id, target)
    claimed = {a["path"]: a for a in artifacts.claimed_artifacts(task_id)}
    scanned = {a["path"]: a for a in artifacts.scan_workspace_artifacts(workspace, since_ts=0.0)}

    merged: dict[str, dict[str, object]] = dict(claimed)
    for path, record in scanned.items():
        merged.setdefault(path, record)

    # The claimed record (with sha256/mime) wins over the bare scan entry.
    assert merged["outputs/result.txt"]["sha256"] == claimed["outputs/result.txt"]["sha256"]
    assert "sha256" in merged["outputs/result.txt"]
    artifacts.clear_claims(task_id)


def test_enrich_artifact_fills_contract_from_a_scan_record(tmp_path: Path) -> None:
    """A bare scan record becomes a full-contract artifact (ART-001)."""
    root = tmp_path / "task"
    (root / "outputs").mkdir(parents=True)
    target = root / "outputs" / "data.csv"
    target.write_text("n,square\n1,1\n")

    # What a directory scan returns: path/size/mtime only.
    bare = {"path": "outputs/data.csv", "size": 13, "mtime": "2026-01-01T00:00:00Z"}

    enriched = artifacts.enrich_artifact(bare, root, task_id="t1", run_id="r1")

    assert enriched["artifact_id"] == "t1:outputs/data.csv"
    assert enriched["mime_type"] == "text/csv"
    assert enriched["sha256"]
    assert enriched["task_id"] == "t1"
    assert enriched["run_id"] == "r1"
