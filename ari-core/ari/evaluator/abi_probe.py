"""Resolve a built library's exported symbols in a process we throw away.

WHY THIS IS NOT A FUNCTION CALL. ``dlopen`` runs the object's ELF constructors,
and the ABI audit used to call it in the SCORER. That handed every candidate a
constructor slot inside the process that goes on to score every later node.

Measured, not theorised. A candidate declaring ``-Ofast`` (or ``-ffast-math``)
makes GCC link ``crtfastmath.o``, whose constructor sets the MXCSR FTZ/DAZ bits
process-wide and with no matching unset: ``5e-324 * 1.0`` returned ``5e-324``
before the audit's ``dlopen`` and ``0.0`` after it. Every subsequent evaluation
in that process then rounds differently -- including oracles whose guarantee
depends on denormals surviving, such as the spmm oracle's bound of exactly 0.0
for an empty row. The candidate does not have to be measured to do it, and
nothing in the resulting evidence records that it happened.

WHY THE FLAGS ARE NOT THE MECHANISM. The same flush was measured from a plain
``-O2`` candidate carrying its own ``__attribute__((constructor))`` that calls
``_MM_SET_FLUSH_ZERO_MODE``. A screen over flag spellings cannot see into the
candidate's C, so refusing ``-Ofast`` would have closed the spelling and left
the escape. Saving and restoring the FP environment around the ``dlopen`` closes
the FP register and leaves the rest of the constructor slot -- signal handlers,
threads, ``atexit``, ``exit()``, the heap. A constructor runs arbitrary code, so
the only bound that holds for every route is a process boundary.

WHY IT IS STILL ``dlopen`` AND ``dlsym``. Reading ``.dynsym`` would answer a
different question than the verifier asks: ifuncs, symbol versioning, symbols
supplied by a dependency, and a library that will not load at all are all cases
where the table and the loader disagree. The audit and the verification it
gates must not be able to disagree about what "exported" means, so this does
exactly what ``drivers/shared_library`` does -- somewhere disposable.

This mirrors the pattern the rest of the repository already uses for the same
hazard: ``drivers/native_worker`` launches ``drivers/native_candidate_host`` to
load a candidate library, and the timed path launches its own child. The scoring
path's audit was the one place a candidate object was still opened in-process.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
from pathlib import Path


def probe(library: str, required: tuple[str, ...]) -> dict:
    """``dlopen`` then ``dlsym`` each name; report which did not resolve."""
    try:
        handle = ctypes.CDLL(library)
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    missing = []
    for name in required:
        try:
            getattr(handle, name)
        except AttributeError:
            missing.append(name)
    return {"ok": True, "missing": missing}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", required=True)
    parser.add_argument("--symbol", action="append", default=[])
    # The answer goes to a file rather than stdout because the constructor that
    # runs inside `probe` can write to this process's stdout, and an envelope a
    # debug `printf` can corrupt would turn a working candidate into a refusal.
    # A constructor CAN read this path back out of /proc/self/cmdline and forge
    # the envelope -- but forging "no missing symbols" is strictly weaker than
    # just exporting stub symbols, which this audit already admits by design: it
    # checks that the contract's symbols resolve, and the Harness checks what
    # they compute.
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    envelope = probe(args.library, tuple(args.symbol))
    Path(args.out).write_text(json.dumps(envelope), encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover - subprocess entry point
    raise SystemExit(main())
