#!/usr/bin/env python3
"""Build a machine-readable local Constitutional ARI-RQGM test artifact.

This script is intentionally offline and deterministic apart from runtime
metadata and pytest duration.  It never claims that a dirty worktree is a
published artifact: the manifest records both the Git revision and a
content hash over every selected source/test/prompt file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "ari-core"
DEFAULT_OUTPUT = ROOT / "report" / "shared" / "artifact"

# ── recorded locations ─────────────────────────────────────────────────────
# A tracked artifact identifies the WORK; it must never identify the machine
# that produced it.  Absolute paths reach this bundle from three directions --
# the interpreter ARI was launched with, `pip freeze`'s editable-install lines,
# and pytest's own output -- and none of them is under this script's control.
#
# So locations are rewritten on the way IN, before anything is written and
# therefore before anything is hashed.  A scrub applied afterwards would be one
# a regeneration could skip, and the digests would then cover the unscrubbed
# bytes.  `_assert_no_machine_identity` then refuses to leave a bundle that
# still names a home, so a leak form nobody anticipated fails the regeneration
# instead of being published.

_OUTSIDE = "<outside-repository>"

#: Every spelling of this checkout, longest first so the longest prefix wins.
#: The same tree is reachable under more than one absolute path at sites that
#: mount a work filesystem under the home namespace, and only one of them is
#: what `Path.resolve()` returns.
_CHECKOUT_PREFIXES = tuple(
    sorted(
        {str(ROOT), str(ROOT.resolve()), str(Path.cwd().resolve())},
        key=len,
        reverse=True,
    )
)

#: An absolute path, or the `../`-traversal spelling `pip freeze` writes into
#: `subdirectory=` for an editable install that lives outside its environment.
#: The lookbehind is what keeps a URL intact: without it the `//` in
#: `git+https://github.com/...` starts a match that swallows the rest of the
#: line, and the real path buried at its end is never examined.
_PATH_TOKEN = re.compile(
    r"(?<![\w:/])(?:\.\./)+[\w./+-]*|(?<![\w:/])/[\w./+-]*"
)

#: What "names a machine" means here: a home directory, under any of the
#: prefixes a site may mount one at.  Deliberately broad -- this drives a
#: fail-closed check, where a false positive costs a human glance and a false
#: negative costs a published username.
_HOME_ROOTED = re.compile(r"(?:/hs/work\d+)?/(?:home|Users)/[^\s\"'<>,;:()\[\]]+")

#: Container-internal paths that only look like a home directory.  These are
#: fixed by an upstream harness image, identical on every machine, and so carry
#: no site identity.
_CONTAINER_INTERNAL = ("/home/submission", "/home/paper", "/home/agent", "/home/logs")

_REDACTED = "<redacted-credential>"

#: Credential-shaped strings.  A test that asserts an injected key was seen
#: prints the key it ACTUALLY saw, so when the suite runs somewhere a real
#: credential is reachable, the failure message carries that credential into
#: the log this bundle publishes.  Nothing about a path rewrite would catch it.
#:
#: Fake keys used as fixtures match too, and that is the right trade: no rule
#: can tell a live key from a convincing placeholder, and a redacted assertion
#: message costs a reader some context while a published key costs a rotation.
#:
#: The threshold is deliberately low and ``.`` is inside the character class,
#: because pytest ABBREVIATES a long string in an assertion summary, to the
#: shape ``'sk-<first twelve>...<last thirteen>'``.  A pattern written for whole
#: keys leaves that line untouched, and it discloses both ends of a live one.
_CREDENTIAL = re.compile(
    r"\b(?:sk-[A-Za-z0-9_.-]{6,}"
    r"|gh[pousr]_[A-Za-z0-9_.-]{6,}"
    r"|AKIA[0-9A-Z]{8,}"
    r"|xox[baprs]-[A-Za-z0-9_.-]{6,}"
    r"|AIza[A-Za-z0-9_.-]{10,})"
)


def _resolved(path: str) -> str:
    """Canonical spelling of ``path``, or ``path`` if it cannot be canonicalized.

    A site can mount the same checkout under more than one absolute path, and
    output captured from a subprocess may use either.  Comparing the canonical
    form as well is what makes a repo-relative rewrite work under an alias
    instead of falling through to ``<outside-repository>``.
    """
    try:
        return str(Path(path).resolve())
    except OSError:
        return path


def _scrub_path(token: str) -> str:
    """Rewrite one path token so it names a location, never a machine."""
    if token.startswith("../"):
        cleaned = "/" + re.sub(r"^(?:\.\./)+", "", token)
    else:
        cleaned = token
    if not cleaned.startswith("/"):
        return token
    for candidate in (cleaned, _resolved(cleaned)):
        for prefix in _CHECKOUT_PREFIXES:
            if candidate == prefix:
                return "."
            if candidate.startswith(prefix + "/"):
                return candidate[len(prefix) + 1 :]
    if cleaned.startswith(_CONTAINER_INTERNAL):
        return cleaned
    marker = "/site-packages/"
    if marker in cleaned:
        # WHICH module a warning came from is the informative part; WHOSE
        # environment holds it is not.
        return "<env>/site-packages/" + cleaned.split(marker, 1)[1]
    if _HOME_ROOTED.match(cleaned):
        return _OUTSIDE
    return token


def _scrub(text: str) -> str:
    """Rewrite every path token and redact every credential in captured output."""
    rewritten = _PATH_TOKEN.sub(lambda match: _scrub_path(match.group(0)), text)
    return _CREDENTIAL.sub(_REDACTED, rewritten)


def _recorded(command: list[str]) -> list[str]:
    """The command as it should be published: runnable, and site-neutral."""
    return [_scrub_path(argument) for argument in command]


def _assert_publishable(out_dir: Path) -> None:
    """Refuse to leave a bundle that names a home directory or carries a credential.

    The rewrites above handle the forms seen so far.  This refuses the next one:
    an unanticipated leak fails the regeneration instead of being published.
    Offenders are reported by kind and location only -- printing the matched
    text would copy the very thing this refuses to write.
    """
    offenders: list[str] = []
    for path in sorted(out_dir.rglob("*")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _HOME_ROOTED.finditer(text):
            if match.group(0).startswith(_CONTAINER_INTERNAL):
                continue
            offenders.append(f"{path.relative_to(out_dir)}: home-rooted path")
        if _CREDENTIAL.search(text):
            offenders.append(f"{path.relative_to(out_dir)}: credential-shaped string")
    if offenders:
        raise SystemExit(
            "reproduce_constitutional_rqgm: refusing to publish a bundle that "
            "identifies a machine or carries a credential:\n  "
            + "\n  ".join(sorted(set(offenders))[:20])
        )

_FOCUSED_TESTS = sorted(
    {
        *CORE.glob("tests/test_rqgm_*.py"),
        *CORE.glob("tests/test_claim_gate_*.py"),
    }
)

SELECTORS = {
    "focused": [
        sys.executable,
        "-m",
        "pytest",
        *(str(path.relative_to(CORE)) for path in _FOCUSED_TESTS),
        "-q",
    ],
    "full": [
        sys.executable,
        "-m",
        "pytest",
        "tests/",
        "-q",
        "-rxX",
        "--ignore=tests/skills",
    ],
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(args: list[str], *, cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONHASHSEED": "0"},
        check=False,
    )


def _git(*args: str) -> str:
    result = _run(["git", *args])
    return result.stdout.strip() if result.returncode == 0 else ""


def _selected_files() -> list[Path]:
    roots = [
        CORE / "ari",
        CORE / "tests",
    ]
    out: list[Path] = []
    for base in roots:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                continue
            out.append(path)
    out.extend([
        ROOT / "requirements.lock",
        CORE / "pyproject.toml",
        Path(__file__).resolve(),
    ])
    return sorted({p.resolve() for p in out if p.is_file()})


def _source_manifest() -> tuple[list[dict], str]:
    entries = [
        {
            "path": str(path.relative_to(ROOT)),
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in _selected_files()
    ]
    encoded = json.dumps(
        entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return entries, hashlib.sha256(encoded).hexdigest()


def _collect(selector: str, out_dir: Path) -> dict:
    command = [
        *(arg for arg in SELECTORS[selector] if arg != "-q"),
        "--collect-only",
        "-q",
    ]
    result = _run(command, cwd=CORE)
    stdout = _scrub(result.stdout)
    log_path = out_dir / f"{selector}-collect.log"
    log_path.write_text(stdout, encoding="utf-8")
    test_ids = sorted({
        line.strip()
        for line in stdout.splitlines()
        if "::" in line and not line.lstrip().startswith(("<", "="))
    })
    list_path = out_dir / f"{selector}-tests.txt"
    list_path.write_text(
        "".join(f"{test_id}\n" for test_id in test_ids),
        encoding="utf-8",
    )
    return {
        "command": _recorded(command),
        "returncode": result.returncode,
        "collected_test_ids": len(test_ids),
        "list_sha256": _sha256(list_path),
        "log_sha256": _sha256(log_path),
    }


def _execute(selector: str, out_dir: Path) -> dict:
    command = SELECTORS[selector]
    result = _run(command, cwd=CORE)
    stdout = _scrub(result.stdout)
    log_path = out_dir / f"{selector}-run.log"
    log_path.write_text(stdout, encoding="utf-8")
    return {
        "command": _recorded(command),
        "returncode": result.returncode,
        "log_sha256": _sha256(log_path),
        "summary_tail": stdout.splitlines()[-8:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="artifact directory (default: report/shared/artifact)",
    )
    parser.add_argument(
        "--run",
        choices=("none", "focused", "full", "all"),
        default="none",
        help="also execute tests after collecting their exact IDs",
    )
    args = parser.parse_args()

    out_dir = args.output.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    files, source_digest = _source_manifest()
    (out_dir / "source-files.json").write_text(
        json.dumps(files, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    freeze = _run([sys.executable, "-m", "pip", "freeze"])
    # An editable install is recorded by pip as a path, so the dependency set
    # cannot be published verbatim: it names every checkout on this machine.
    (out_dir / "python-packages.txt").write_text(
        _scrub(freeze.stdout), encoding="utf-8"
    )
    authority = _run(
        [sys.executable, "-m", "ari.rqgm.authority_manifest"], cwd=CORE
    )
    authority_path = out_dir / "authority-matrix.json"
    authority_path.write_text(_scrub(authority.stdout), encoding="utf-8")

    collection = {
        name: _collect(name, out_dir) for name in ("focused", "full")
    }
    execution = {}
    selected = (
        ("focused", "full")
        if args.run == "all"
        else ((args.run,) if args.run != "none" else ())
    )
    for name in selected:
        execution[name] = _execute(name, out_dir)

    status = _git("status", "--porcelain=v1", "--untracked-files=all")
    manifest = {
        "artifact": "constitutional-ari-rqgm-local-reproduction",
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "publication_status": "local-unpublished",
        "git": {
            "commit": _git("rev-parse", "HEAD"),
            "branch": _git("branch", "--show-current"),
            "working_tree_dirty": bool(status),
        },
        "source_manifest_sha256": source_digest,
        "source_file_count": len(files),
        "requirements_lock_sha256": _sha256(ROOT / "requirements.lock"),
        "runtime": {
            "python": sys.version,
            # WHICH interpreter is already in `python` above; WHERE it lives
            # only says whose machine ran this.
            "executable": _scrub_path(sys.executable),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "pythonhashseed": "0",
            "pip_freeze_returncode": freeze.returncode,
            "python_packages_sha256": _sha256(
                out_dir / "python-packages.txt"
            ),
        },
        "authority_matrix": {
            "command": _recorded(
                [sys.executable, "-m", "ari.rqgm.authority_manifest"]
            ),
            "returncode": authority.returncode,
            "sha256": _sha256(authority_path),
        },
        "collection": collection,
        "execution": execution,
        "limitations": [
            "This directory is not an immutable public tag or DOI archive.",
            "A dirty tree is identified by content hashes, not by Git SHA alone.",
            "No model calls or scientific-quality experiments are run here.",
            "Recorded locations are repo-relative; a path outside this checkout "
            "is replaced rather than disclosed, and credential-shaped strings in "
            "captured output are redacted.",
        ],
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _assert_publishable(out_dir)
    print(json.dumps({
        "manifest": str(manifest_path),
        "source_manifest_sha256": source_digest,
        "collection": collection,
        "execution_returncodes": {
            name: result["returncode"] for name, result in execution.items()
        },
    }, ensure_ascii=False, indent=2))
    return max(
        [authority.returncode]
        + [result["returncode"] for result in execution.values()]
    )


if __name__ == "__main__":
    raise SystemExit(main())
