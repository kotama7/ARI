"""`ari memory` subcommand.

Wired into the main Typer app in ``ari.cli`` as a sub-app. Commands:

  ari memory migrate         one-shot import of v0.5.x JSONL → Letta
  ari memory backup          snapshot Letta collections to checkpoint
  ari memory restore         inverse of backup
  ari memory start-local     bring up local Letta (docker/singularity/pip)
  ari memory stop-local      kill local Letta
  ari memory prune-local     remove local Letta data
  ari memory compact-access  summarise rotated memory_access.jsonl files
  ari memory health          proxy for backend.health()
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import typer
from rich.console import Console

log = logging.getLogger(__name__)
memory_app = typer.Typer(name="memory", help="Letta memory admin commands")
console = Console()
_MAX_BACKUP_BYTES = 512 * 1024 * 1024


def _resolve_ckpt(path: "str | Path | None", scan: bool = False) -> Path:
    if path is None:
        from ari.paths import PathManager
        env_ckpt = PathManager.checkpoint_dir_from_env()
        if env_ckpt is not None:
            return env_ckpt.expanduser().resolve()
        raise typer.BadParameter(
            "--checkpoint is required (no ARI_CHECKPOINT_DIR in env)"
        )
    return Path(path).expanduser().resolve()


def _get_backend(checkpoint_dir: Path):
    from ari.paths import PathManager
    PathManager.set_checkpoint_dir_env(checkpoint_dir)
    from ari.memory import get_backend
    return get_backend(checkpoint_dir=checkpoint_dir)


# ─ migrate ────────────────────────────────────────────────────────────

def _load_legacy_jsonl(path: Path) -> list[dict]:
    entries: list[dict] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{path.name}:{line_number} is not valid JSON"
            ) from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path.name}:{line_number} must contain an object")
        entries.append(value)
    return entries


def _legacy_record(entry: dict, *, ordinal: int) -> dict:
    """Convert one v0.5 node entry into a conservative v1 index record."""

    from ari.public.memory import build_memory_record

    metadata = dict(entry.get("metadata") or {})
    node_id = str(entry.get("node_id") or metadata.get("node_id") or "")
    text = str(entry.get("text") or entry.get("content") or "")
    if not node_id or not text:
        raise ValueError(f"legacy memory entry {ordinal} lacks node_id or text")
    legacy_kind = str(metadata.get("mem_kind") or metadata.get("type") or "")
    supported = {
        "observation",
        "experiment_result",
        "failure_case",
        "procedure",
        "reflection",
        "artifact_summary",
        "paper_claim",
    }
    kind = legacy_kind if legacy_kind in supported else "observation"
    ancestors = entry.get("ancestor_ids") or metadata.get("ancestor_ids") or []
    if not isinstance(ancestors, list):
        raise ValueError(f"legacy memory entry {ordinal} has invalid ancestor_ids")
    run_id = str(entry.get("run_id") or metadata.get("run_id") or "legacy-v0.5")

    artifact_refs: list[dict] = []
    for raw_ref in metadata.get("artifact_refs") or []:
        if not isinstance(raw_ref, dict):
            continue
        digest = str(raw_ref.get("digest") or raw_ref.get("sha256") or "")
        if digest and not digest.startswith("sha256:"):
            digest = "sha256:" + digest
        path = str(raw_ref.get("relative_path") or raw_ref.get("path") or "")
        if len(digest) != 71 or not path:
            continue
        artifact_refs.append(
            {
                "relative_path": path,
                "digest": digest,
                "size_bytes": int(raw_ref.get("size_bytes") or 0),
                "role": str(raw_ref.get("role") or "legacy-unknown"),
                # A legacy hash has not been re-read from the migrated host.
                "integrity_status": "unverified",
            }
        )

    metric_ptr = metadata.get("metric_ptr")
    if not (
        isinstance(metric_ptr, dict)
        and metric_ptr.get("name")
        and metric_ptr.get("unit")
        and isinstance(metric_ptr.get("value"), (int, float))
        and not isinstance(metric_ptr.get("value"), bool)
    ):
        metric_ptr = None
    attributes = {
        "legacy_schema": "ari.memory-store/v0.5",
        "legacy_entry_digest": _canonical_digest(entry),
        "legacy_kind": legacy_kind or None,
        "legacy_metadata": metadata,
    }
    return build_memory_record(
        kind=kind,
        text=text,
        source_run_id=run_id,
        source_node_id=node_id,
        ancestor_node_ids=[str(value) for value in ancestors],
        artifact_refs=artifact_refs,
        metric_ptr=metric_ptr,
        confidence=(
            metadata.get("confidence")
            if isinstance(metadata.get("confidence"), (int, float))
            and not isinstance(metadata.get("confidence"), bool)
            else None
        ),
        created_by_tool_ref="ari-memory-migrate:v05",
        attributes=attributes,
    ).model_dump(mode="json")


def _archive_legacy_source(path: Path) -> Path:
    stamp = time.time_ns()
    target = path.with_name(f"{path.name}.migrated-{stamp}")
    path.rename(target)
    return target


def _do_migrate(
    ckpt: Path,
    *,
    include_react: bool = False,
    dry_run: bool = False,
) -> dict:
    """Offline, idempotent v0.5 JSONL -> MemoryRecordV1 migration."""

    src_node = ckpt / "memory_store.jsonl"
    src_react = ckpt / "memory.json"
    legacy_nodes = _load_legacy_jsonl(src_node) if src_node.exists() else []
    records = [
        _legacy_record(entry, ordinal=index)
        for index, entry in enumerate(legacy_nodes, start=1)
    ]
    react_entries: list[dict] = []
    if include_react and src_react.exists():
        try:
            raw_react = json.loads(src_react.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("memory.json is not valid JSON") from exc
        if not isinstance(raw_react, list) or not all(
            isinstance(item, dict) for item in raw_react
        ):
            raise ValueError("memory.json must contain a list of objects")
        react_entries = raw_react
    if dry_run:
        return {
            "records": len(records),
            "react_entries": len(react_entries),
            "imported": 0,
            "archived_sources": [],
            "dry_run": True,
        }

    backend = _get_backend(ckpt)
    existing_entries = [
        entry
        for entries in backend.list_all_nodes().get("by_node", {}).values()
        for entry in entries
    ]
    unversioned = [
        entry
        for entry in existing_entries
        if not (entry.get("metadata") or {}).get("record_digest")
    ]
    if unversioned:
        raise MemoryBackupIntegrityError(
            "target backend already contains unversioned memory; migrate into "
            "an empty backend or restore a canonical backup"
        )
    existing_digests = _validated_backend_record_digests(backend)
    node_entries = [
        {
            "node_id": record["source_node_id"],
            "text": record["text"],
            "metadata": _record_metadata(record),
            "ts": float(index),
        }
        for index, record in enumerate(records)
        if record["record_digest"] not in existing_digests
    ]
    imported = 0
    if node_entries:
        imported += backend.bulk_import(node_entries, kind="node_scope")["imported"]
    existing_react_digests = {
        _canonical_digest(
            {
                "content": str(entry.get("content") or ""),
                "metadata": dict(entry.get("metadata") or {}),
                "ts": float(entry.get("ts") or 0.0),
            }
        )
        for entry in backend.list_react_entries()
    }
    normalized_react = []
    for entry in react_entries:
        payload = {
            "content": str(entry.get("content") or entry.get("text") or ""),
            "metadata": dict(entry.get("metadata") or {}),
            "ts": float(entry.get("ts") or 0.0),
        }
        if _canonical_digest(payload) not in existing_react_digests:
            normalized_react.append(
                {
                    "text": payload["content"],
                    "metadata": payload["metadata"],
                    "ts": payload["ts"],
                }
            )
    if normalized_react:
        imported += backend.bulk_import(
            normalized_react, kind="react_step"
        )["imported"]

    backup = _do_backup(ckpt)
    archived: list[str] = []
    if src_node.exists():
        archived.append(str(_archive_legacy_source(src_node)))
    if include_react and src_react.exists():
        archived.append(str(_archive_legacy_source(src_react)))
    return {
        "records": len(records),
        "react_entries": len(react_entries),
        "imported": imported,
        "skipped": (
            len(records) - len(node_entries)
            + len(react_entries) - len(normalized_react)
        ),
        "archived_sources": archived,
        "backup": backup,
        "dry_run": False,
    }


@memory_app.command("migrate")
def migrate_cmd(
    checkpoint: "Path | None" = typer.Option(None, help="Checkpoint directory"),
    react: bool = typer.Option(False, "--react", help="Also migrate memory.json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Offline import of v0.5 JSONL as content-addressed v1 records."""
    ckpt = _resolve_ckpt(checkpoint)
    if not ckpt.is_dir():
        console.print(f"[red]Not a directory: {ckpt}[/red]")
        raise typer.Exit(1)

    try:
        result = _do_migrate(ckpt, include_react=react, dry_run=dry_run)
    except (ValueError, OSError) as exc:
        console.print(f"[red]migration failed: {exc}[/red]")
        raise typer.Exit(2) from exc
    console.print(f"[cyan]node records: {result['records']}[/cyan]")
    if react:
        console.print(f"[cyan]react entries: {result['react_entries']}[/cyan]")
    if dry_run:
        console.print("[yellow]--dry-run: validated without writes.[/yellow]")
    else:
        console.print(
            f"[green]✓ imported {result['imported']} entries and wrote "
            f"{result['backup']['backup_digest']}[/green]"
        )

    # Global memory: detect but do not migrate.
    # Phase 5 (REFACTORING.md §8) parks the legacy path in
    # ``ari.migrations.v05_to_v07.memory`` so all readers reference one
    # constant — the v1.0 deletion only has to remove that file.
    from ari.migrations.v05_to_v07.memory import LEGACY_GLOBAL_PATH
    global_path = LEGACY_GLOBAL_PATH
    if global_path.exists():
        console.print(
            f"[yellow]WARNING: {global_path} found — global memory is removed in "
            "v0.6.0 and is intentionally not imported.[/yellow]"
        )


# ─ backup / restore ───────────────────────────────────────────────────

class MemoryBackupIntegrityError(ValueError):
    """A portable memory backup is corrupt or contains unsupported records."""


def _canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _record_metadata(record: dict) -> dict:
    return {
        "memory_record": record,
        "record_digest": record["record_digest"],
        "type": record["kind"],
        "mem_kind": record["kind"],
        "metric_ptr": record.get("metric_ptr"),
        "artifact_refs": record.get("artifact_refs") or [],
        "node_report_ref": record.get("node_report_ref"),
        "repro_target_id": record.get("repro_target_id"),
        "repro_status": record.get("repro_status"),
        "confidence": record.get("confidence"),
    }


def _validated_backend_record_digests(backend: object) -> set[str]:
    from ari.public.memory import MemoryRecordV1

    digests: set[str] = set()
    by_node = backend.list_all_nodes().get("by_node", {})
    for node_id, entries in by_node.items():
        for entry in entries:
            metadata = entry.get("metadata") or {}
            raw = metadata.get("memory_record")
            if not isinstance(raw, dict):
                raise MemoryBackupIntegrityError(
                    "target backend contains an unversioned memory record"
                )
            try:
                record = MemoryRecordV1.model_validate(raw)
            except ValueError as exc:
                raise MemoryBackupIntegrityError(
                    "target backend contains an invalid canonical memory record"
                ) from exc
            if (
                record.source_node_id != node_id
                or record.text != entry.get("text", "")
                or metadata.get("record_digest") != record.record_digest
            ):
                raise MemoryBackupIntegrityError(
                    "target backend projection disagrees with MemoryRecordV1"
                )
            if record.record_digest in digests:
                raise MemoryBackupIntegrityError(
                    "target backend contains duplicate canonical memory records"
                )
            digests.add(record.record_digest)
    return digests


def _backup_path(ckpt: Path) -> Path:
    return ckpt / "memory_backup.v1.json.gz"


def _do_backup(ckpt: Path) -> dict:
    from ari.public.memory import (
        MemoryRecordV1,
        build_memory_backup,
        build_memory_react_entry,
    )

    backend = _get_backend(ckpt)
    path = _backup_path(ckpt)
    records: list[dict] = []
    record_order: list[str] = []
    by_node = backend.list_all_nodes().get("by_node", {})
    for node_id in sorted(by_node):
        entries = by_node[node_id]
        for entry in entries:
            raw = (entry.get("metadata") or {}).get("memory_record")
            if not isinstance(raw, dict):
                raise MemoryBackupIntegrityError(
                    "runtime backup refuses an unversioned memory record; "
                    "run the offline `ari memory migrate` command first"
                )
            record = MemoryRecordV1.model_validate(raw)
            if record.source_node_id != node_id or record.text != entry.get("text", ""):
                raise MemoryBackupIntegrityError(
                    "memory backend projection disagrees with MemoryRecordV1"
                )
            normalized = record.model_dump(mode="json")
            records.append(normalized)
            record_order.append(normalized["record_digest"])
    records.sort(key=lambda item: item["record_digest"])

    react: list[dict] = []
    for entry in backend.list_react_entries():
        item = build_memory_react_entry(
            content=str(entry.get("content") or ""),
            metadata=dict(entry.get("metadata") or {}),
            ts=float(entry.get("ts") or 0.0),
        ).model_dump(mode="json")
        react.append(item)
    react.sort(key=lambda item: item["entry_digest"])
    context = dict(backend.get_experiment_context() or {})
    # Empty backends expose ``seeded_at=0`` as a convenience projection; it is
    # not a real core-memory record and must not create a phantom backup entry.
    if set(context) <= {"seeded_at"} and not context.get("seeded_at"):
        context = {}
    document = build_memory_backup(
        records=records,
        react_entries=react,
        core_context=context,
        record_digests=[item["record_digest"] for item in records],
        record_order=record_order,
    ).model_dump(mode="json")
    raw_payload = (
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
            temp_path = Path(temporary.name)
            with gzip.GzipFile(
                fileobj=temporary, mode="wb", filename="", mtime=0
            ) as stream:
                stream.write(raw_payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temp_path, path)
        temp_path = None
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    compressed = path.read_bytes()
    return {
        "entries": len(records) + len(react) + int(bool(context)),
        "records": len(records),
        "react_entries": len(react),
        "backup_digest": document["backup_digest"],
        "artifact_digest": "sha256:" + hashlib.sha256(compressed).hexdigest(),
        "size_bytes": len(compressed),
        "path": str(path),
    }


def _load_backup(path: Path) -> dict:
    from ari.public.memory import MemoryBackupV1

    try:
        if path.stat().st_size > _MAX_BACKUP_BYTES:
            raise MemoryBackupIntegrityError("compressed memory backup exceeds size limit")
        with gzip.open(path, "rb") as stream:
            payload = stream.read(_MAX_BACKUP_BYTES + 1)
        if len(payload) > _MAX_BACKUP_BYTES:
            raise MemoryBackupIntegrityError("expanded memory backup exceeds size limit")
        raw_document = json.loads(payload.decode("utf-8"))
    except MemoryBackupIntegrityError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MemoryBackupIntegrityError("memory backup is not valid gzip JSON") from exc
    try:
        return MemoryBackupV1.model_validate(raw_document).model_dump(mode="json")
    except ValueError as exc:
        raise MemoryBackupIntegrityError(f"memory backup validation failed: {exc}") from exc


def _do_restore(ckpt: Path, on_conflict: str = "skip") -> dict:
    path = _backup_path(ckpt)
    if not path.exists():
        return {"restored": 0, "reason": "no backup"}
    if on_conflict not in {"skip", "overwrite", "merge"}:
        raise ValueError("on_conflict must be skip, overwrite, or merge")
    document = _load_backup(path)
    backend = _get_backend(ckpt)
    if on_conflict == "overwrite":
        backend.purge_checkpoint()
    existing_records = _validated_backend_record_digests(backend)
    node_entries = []
    skipped = 0
    records_by_digest = {
        record["record_digest"]: record for record in document["records"]
    }
    for order_index, record_digest in enumerate(document["record_order"]):
        record = records_by_digest[record_digest]
        if record["record_digest"] in existing_records:
            skipped += 1
            continue
        node_entries.append(
            {
                "node_id": record["source_node_id"],
                "text": record["text"],
                "metadata": _record_metadata(record),
                # A portable logical clock preserves append order, including
                # the latest reproducibility event, without wall-clock noise.
                "ts": float(order_index),
            }
        )
    existing_react = {
        _canonical_digest(
            {
                "content": str(entry.get("content") or ""),
                "metadata": dict(entry.get("metadata") or {}),
                "ts": float(entry.get("ts") or 0.0),
            }
        )
        for entry in backend.list_react_entries()
    }
    react_entries = []
    for item in document.get("react_entries") or []:
        if item["entry_digest"] in existing_react:
            skipped += 1
            continue
        react_entries.append(
            {
                "text": item["content"],
                "metadata": item["metadata"],
                "ts": item["ts"],
            }
        )
    target_context = document.get("core_context") or {}
    current_context = dict(backend.get_experiment_context() or {})
    if set(current_context) <= {"seeded_at"} and not current_context.get("seeded_at"):
        current_context = {}
    core_entries = []
    if target_context and target_context != current_context:
        core_entries = [{"persona": "", "human": "", "context": target_context}]
    elif target_context:
        skipped += 1

    total = 0
    if node_entries:
        total += backend.bulk_import(node_entries, kind="node_scope")["imported"]
    if react_entries:
        total += backend.bulk_import(react_entries, kind="react_step")["imported"]
    if core_entries:
        total += backend.bulk_import(core_entries, kind="core_seed")["imported"]
    restored_digests = _validated_backend_record_digests(backend)
    missing = sorted(set(document["record_digests"]) - restored_digests)
    if missing:
        raise MemoryBackupIntegrityError(
            f"restored backend is missing {len(missing)} memory record digests"
        )
    return {
        "restored": total,
        "skipped": skipped,
        "backup_digest": document["backup_digest"],
        "record_digests": document["record_digests"],
        "record_order": document["record_order"],
        "conflict_policy": on_conflict,
    }


@memory_app.command("backup")
def backup_cmd(
    checkpoint: "Path | None" = typer.Option(None, help="Checkpoint directory"),
) -> None:
    """Snapshot canonical memory to ``{ckpt}/memory_backup.v1.json.gz``."""
    ckpt = _resolve_ckpt(checkpoint)
    try:
        result = _do_backup(ckpt)
    except Exception as e:
        console.print(f"[red]backup failed: {e}[/red]")
        raise typer.Exit(1)
    console.print(
        f"[green]✓ wrote {_backup_path(ckpt)} "
        f"({result['entries']} entries, {result['backup_digest']})[/green]"
    )


@memory_app.command("restore")
def restore_cmd(
    checkpoint: "Path | None" = typer.Option(None, help="Checkpoint directory"),
    on_conflict: str = typer.Option("skip", help="skip|overwrite|merge"),
) -> None:
    """Validate and import ``memory_backup.v1.json.gz`` into Letta."""
    ckpt = _resolve_ckpt(checkpoint)
    res = _do_restore(ckpt, on_conflict=on_conflict)
    console.print(f"[green]✓ restored {res['restored']} entries[/green]")


# ─ local Letta lifecycle ──────────────────────────────────────────────

def _scripts_root() -> Path:
    # scripts/letta/ relative to ari-core
    return Path(__file__).resolve().parents[2] / "scripts" / "letta"


@memory_app.command("start-local")
def start_local_cmd(
    path: str = typer.Option(
        "auto", help="docker|singularity|pip|auto — deployment path"
    ),
) -> None:
    """Start a local Letta server."""
    root = _scripts_root()
    chosen = path
    if chosen == "auto":
        chosen = _detect_deployment()
    cmd: list[str] = []
    if chosen == "docker":
        cmd = ["docker", "compose", "-f", str(root / "docker-compose.yml"), "up", "-d"]
    elif chosen == "singularity":
        cmd = ["bash", str(root / "start_singularity.sh")]
    elif chosen == "pip":
        cmd = ["bash", str(root / "start_pip.sh")]
    else:
        console.print(f"[red]Unsupported path: {chosen}[/red]")
        raise typer.Exit(1)
    try:
        subprocess.run(cmd, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        console.print(f"[red]start-local failed: {e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]✓ {chosen} started[/green]")


@memory_app.command("stop-local")
def stop_local_cmd() -> None:
    """Stop the locally-started Letta."""
    # Try each known form — best-effort.
    for cmd in (
        ["docker", "compose", "-f", str(_scripts_root() / "docker-compose.yml"), "down"],
        ["singularity", "instance", "stop", "ari-letta"],
        ["pkill", "-f", "letta server"],
    ):
        try:
            subprocess.run(cmd, check=False)
        except FileNotFoundError:
            continue
    console.print("[green]✓ stop signals sent[/green]")


@memory_app.command("prune-local")
def prune_local_cmd(
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Delete local Letta state (docker volumes / sif / venv)."""
    if not yes:
        if not typer.confirm("Remove all local Letta data?"):
            raise typer.Exit(0)
    root = _scripts_root()
    subprocess.run(
        ["docker", "compose", "-f", str(root / "docker-compose.yml"), "down", "-v"],
        check=False,
    )
    env_value = os.environ.get("ARI_LETTA_VENV", "").strip()
    if env_value:
        venv = Path(env_value)
    else:
        # Phase DR2 (DEPRECATION_REMOVAL.md tier B): the legacy
        # ``~/.ari/letta-venv/`` fallback is kept for one minor version
        # behind a DeprecationWarning; v1.0 makes ARI_LETTA_VENV mandatory.
        venv = Path.home() / ".ari/letta-venv"
        if venv.exists():
            from ari._deprecation import warn_deprecated_path
            warn_deprecated_path(
                venv,
                replacement="ARI_LETTA_VENV environment variable (will be required in v1.0)",
            )
    if venv.exists():
        shutil.rmtree(venv, ignore_errors=True)
    dotletta = Path.home() / ".letta"
    if dotletta.exists():
        shutil.rmtree(dotletta, ignore_errors=True)
    console.print("[green]✓ local Letta state removed[/green]")


# ─ access log ─────────────────────────────────────────────────────────

@memory_app.command("compact-access")
def compact_access_cmd(
    checkpoint: "Path | None" = typer.Option(None, help="Checkpoint directory"),
) -> None:
    """Summarise rotated memory_access.<ts>.jsonl files into a single summary."""
    ckpt = _resolve_ckpt(checkpoint)
    rotated = sorted(ckpt.glob("memory_access.*.jsonl"))
    if not rotated:
        console.print("[yellow]no rotated files to compact[/yellow]")
        return
    by_node: dict[str, dict[str, int]] = {}
    for f in rotated:
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                ev = json.loads(line)
            except Exception:
                continue
            nid = ev.get("node_id", "")
            by_node.setdefault(nid, {"writes": 0, "reads": 0})
            if ev.get("op") == "write":
                by_node[nid]["writes"] += 1
            elif ev.get("op") == "read":
                by_node[nid]["reads"] += 1
    summary = ckpt / "memory_access.summary.json"
    summary.write_text(
        json.dumps(by_node, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for f in rotated:
        f.unlink()
    console.print(
        f"[green]✓ compacted {len(rotated)} files → {summary}[/green]"
    )


# ─ health ─────────────────────────────────────────────────────────────

@memory_app.command("health")
def health_cmd(
    checkpoint: "Path | None" = typer.Option(None, help="Checkpoint directory"),
) -> None:
    """Ping the backend and show its reachability."""
    ckpt = _resolve_ckpt(checkpoint)
    try:
        backend = _get_backend(ckpt)
        h = backend.health()
    except Exception as e:
        console.print(f"[red]unhealthy: {e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]{h}[/green]")


# ─ helpers ────────────────────────────────────────────────────────────

def _detect_deployment() -> str:
    """Pick a local Letta deployment path."""
    on_hpc = bool(os.environ.get("SLURM_CLUSTER_NAME"))
    if shutil.which("docker") and not on_hpc:
        return "docker"
    if shutil.which("singularity") or shutil.which("apptainer"):
        return "singularity"
    if shutil.which("python") or shutil.which("python3"):
        return "pip"
    return "none"


__all__ = [
    "memory_app",
    "_do_backup",
    "_do_migrate",
    "_do_restore",
    "_detect_deployment",
    "MemoryBackupIntegrityError",
]
