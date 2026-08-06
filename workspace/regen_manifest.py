"""Regenerate a v2 harness.toml: refresh [files] sha256s and the [integrity] self-digest."""
import sys, re, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "ari-core"))
from ari.harness_registry import (sha256_file, manifest_integrity_hash,
                                  unpinned_files)
try: import tomllib
except ModuleNotFoundError: import tomli as tomllib


def audit_unpinned(task_dir: pathlib.Path, pinned: set):
    """Refuse to regenerate while a scored file is missing from [files].

    This script only refreshes digests for paths ALREADY listed in the manifest,
    so a newly added file is silently left unpinned — and an unpinned file is
    freely modifiable without the integrity check noticing. That matters most
    for exactly the kind of file most likely to be added: reference_gemm.c is
    the score denominator, and an unpinned denominator makes every score
    unverifiable.

    The rule now lives in the registry (``unpinned_files``), which also enforces
    it at LOAD. Keeping a second copy here meant "what counts as scored
    scaffolding" had two answers, and only the re-pin path was ever asked.
    """
    missing = unpinned_files(task_dir, pinned)
    if missing:
        raise SystemExit(
            f"{task_dir.name}: these files are present but NOT pinned in "
            f"[files]: {', '.join(missing)}. Add them to harness.toml (any "
            f"64-hex placeholder digest) and re-run; refusing to regenerate a "
            f"manifest that would leave scored scaffolding unverified.")


def regen(task_dir: pathlib.Path):
    man_path = task_dir / "harness.toml"
    text = man_path.read_text(encoding="utf-8")
    man = tomllib.loads(text)
    new = {}
    for rel in man.get("files", {}):
        p = task_dir / rel
        if not p.is_file():
            raise SystemExit(f"pinned file missing: {p}")
        new[rel] = sha256_file(p)
    audit_unpinned(task_dir, set(man.get("files", {})))
    out = text
    for rel, dig in new.items():
        out = re.sub(rf'(?m)^("{re.escape(rel)}"\s*=\s*)"[0-9a-f]{{64}}"', rf'\g<1>"{dig}"', out)
    man2 = tomllib.loads(out)
    self_hash = manifest_integrity_hash(man2)
    out = re.sub(r'(?m)^(self_sha256\s*=\s*)"[0-9a-f]{64}"', rf'\g<1>"{self_hash}"', out)
    man_path.write_text(out, encoding="utf-8")
    changed = [r for r in new if new[r] != man["files"][r]]
    print(f"{task_dir.name}: refreshed {len(new)} digests ({len(changed)} changed: {', '.join(changed) or 'none'})")
    print(f"{task_dir.name}: self_sha256 -> {self_hash}")

if not sys.argv[1:]:
    # Silently doing nothing is the dangerous outcome here: it looks exactly
    # like a successful regeneration, and the caller then ships a harness whose
    # manifest still pins the OLD scaffolding.
    raise SystemExit("usage: regen_manifest.py <task> [<task> ...]  (e.g. gemm spmm stencil)")

# Where the harnesses are is ARI_WORKSPACE's answer when it has one. Hardcoding
# this script's own parent made it unusable for a harness registered anywhere
# else -- including a pool variant under a different workspace -- and it failed
# with a bare FileNotFoundError rather than saying what it had looked for.
import os as _os
_ROOT = pathlib.Path(_os.environ.get("ARI_WORKSPACE")
                     or pathlib.Path(__file__).resolve().parent) / "harnesses"
for t in sys.argv[1:]:
    d = _ROOT / t
    if not (d / "harness.toml").is_file():
        raise SystemExit(
            f"no harness.toml at {d}. Registered harnesses are searched under "
            f"{_ROOT} (set ARI_WORKSPACE to look elsewhere); found: "
            f"{', '.join(sorted(x.name for x in _ROOT.iterdir() if x.is_dir())) if _ROOT.is_dir() else '(no such directory)'}")
    regen(d)
