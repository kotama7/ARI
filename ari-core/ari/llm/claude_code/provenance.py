"""Per-call provenance sandbox for the Claude Code provider.

Every request gets its own directory (concurrency-safe: the call id embeds
pid + a process-local counter + random suffix, so parallel BFTS shards never
collide) holding every input artifact, the exact command, the environment
allowlist, raw stdout/stderr, the normalized result, schema validation
outcome, and content hashes:

    <checkpoint>/claude_code/<call_id>/
      ├─ input/messages.json
      ├─ prompt.txt
      ├─ system.txt
      ├─ schema.json
      ├─ command.json
      ├─ env_allowlist.json
      ├─ claude_version.txt
      ├─ stdout.json
      ├─ stderr.log
      ├─ result.json
      ├─ validation.json
      ├─ input_hashes.json
      ├─ output_hashes.json
      ├─ provenance.json
      ├─ trace.jsonl          (low_overhead mode: SDK event trace)
      ├─ cwd/                 (the request's throwaway working directory)
      └─ attempt_2/           (schema repair retry, same layout)

Bit-level output equality across runs is NOT guaranteed (LLM sampling);
what this layer guarantees is verifiability: identical inputs/policy are
provable via input_hashes.json and any output is auditable via
output_hashes.json.

Secrets never land in provenance: environment VALUES are recorded only as
"<inherited>"/"<forced:...>" markers (see command.build_subprocess_env).
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import re
import time
import uuid
from pathlib import Path

_CALL_SEQ = itertools.count()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def new_call_id(label: str = "") -> str:
    """Mint a unique, sortable call id (concurrency-safe across processes)."""
    ts = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    seq = next(_CALL_SEQ)
    suffix = uuid.uuid4().hex[:8]
    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", label)[:40]
    parts = [ts, str(os.getpid()), f"{seq:04d}", suffix]
    if slug:
        parts.append(slug)
    return "_".join(parts)


def resolve_provenance_root(explicit: str | Path | None = None) -> Path | None:
    """Locate the run's claude_code provenance root, if any.

    Precedence: explicit argument > ``$ARI_CHECKPOINT_DIR/claude_code``
    (via the blessed PathManager accessor). Returns None when no checkpoint
    is pinned — the provider then falls back to a temp dir (still recorded
    in the response's ``provenance_path``).
    """
    if explicit:
        return Path(explicit)
    from ari.paths import PathManager

    ckpt = PathManager.checkpoint_dir_from_env()
    if ckpt is None:
        return None
    return Path(ckpt) / "claude_code"


class ProvenanceWriter:
    """Writes one call's artifact set. All writes are best-effort ordered:
    inputs before the subprocess runs, outputs immediately after."""

    def __init__(self, call_dir: Path) -> None:
        self.dir = Path(call_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "input").mkdir(exist_ok=True)
        self._input_hashes: dict[str, str] = {}
        self._output_hashes: dict[str, str] = {}

    # -- inputs ----------------------------------------------------------
    def write_input(
        self,
        *,
        messages: list[dict],
        prompt: str,
        system: str,
        schema_json: str | None,
    ) -> None:
        messages_json = json.dumps(
            messages, ensure_ascii=False, indent=2, default=str
        )
        self._write("input/messages.json", messages_json, self._input_hashes)
        self._write("prompt.txt", prompt, self._input_hashes)
        self._write("system.txt", system, self._input_hashes)
        if schema_json is not None:
            self._write("schema.json", schema_json, self._input_hashes)
        self._dump_json("input_hashes.json", self._input_hashes)

    def write_command(
        self,
        *,
        argv: tuple[str, ...] | list[str],
        cwd: str,
        stdin_from: str = "prompt.txt",
        runner: str = "cli",
        options: dict | None = None,
    ) -> None:
        self._dump_json(
            "command.json",
            {
                "argv": list(argv),
                "cwd": cwd,
                "stdin_from": stdin_from,
                "runner": runner,
                "options": options or {},
            },
        )

    def write_env_allowlist(self, record: dict[str, str]) -> None:
        self._dump_json("env_allowlist.json", record)

    def write_claude_version(self, version: str) -> None:
        self._write("claude_version.txt", version, self._input_hashes)
        # Called after write_input, which already dumped input_hashes.json —
        # re-dump so the version hash actually lands in it.
        self._dump_json("input_hashes.json", self._input_hashes)

    # -- outputs ---------------------------------------------------------
    def write_output(self, *, stdout: str, stderr: str, returncode: int) -> None:
        self._write("stdout.json", stdout, self._output_hashes)
        self._write("stderr.log", stderr, self._output_hashes)
        self._output_hashes["returncode"] = str(returncode)
        self._dump_json("output_hashes.json", self._output_hashes)

    def write_result(self, result: dict) -> None:
        text = json.dumps(result, ensure_ascii=False, indent=2, default=str)
        self._write("result.json", text, self._output_hashes)
        self._dump_json("output_hashes.json", self._output_hashes)

    def write_validation(self, validation: dict) -> None:
        self._dump_json("validation.json", validation)

    def append_trace(self, event: dict) -> None:
        with open(self.dir / "trace.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")

    def write_provenance(self, provenance: dict) -> None:
        self._dump_json("provenance.json", provenance)

    def attempt_dir(self, attempt: int) -> Path:
        """Sub-sandbox for the schema repair retry (attempt >= 2)."""
        d = self.dir / f"attempt_{attempt}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def cwd_dir(self) -> Path:
        d = self.dir / "cwd"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # -- helpers ---------------------------------------------------------
    def _write(self, rel: str, text: str, hashes: dict[str, str]) -> None:
        path = self.dir / rel
        path.write_text(text, encoding="utf-8")
        hashes[rel] = sha256_text(text)

    def _dump_json(self, rel: str, obj: dict) -> None:
        (self.dir / rel).write_text(
            json.dumps(obj, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
