#!/usr/bin/env python3
"""Sync per-directory ``README.md`` ``## Contents`` indexes with the filesystem.

Every in-scope directory's README carries a ``## Contents`` section that lists
each file and subdirectory beneath it (recursively), so that adding or removing
a file shows up as a README diff. This tool keeps that listing in sync:

  --check   compare the listed PATH structure against the actual tree and exit
            1 on drift (missing/extra paths). This is the CI / pre-commit gate.
  --write   regenerate the ``## Contents`` block in place. The heading, role
            line and ``## See also`` are preserved; existing per-path
            descriptions are reused (harvested across all READMEs); a NEW file
            with no known description gets ``TODO``.

This tool NEVER calls an LLM or any network API. New-file descriptions
(``TODO`` placeholders) are written by hand afterwards. Both modes are pure
Python stdlib.

Only READMEs that already contain a ``## Contents`` heading are managed;
curated roots without one (e.g. ari-core/README.md) are left untouched.

Convention: ari-core/ari/orchestrator/README.md is the reference format.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Directories omitted entirely (generated / vendored / ephemeral / out of
# scope): never listed and never given a README. Matched by exact name…
SKIP_NAMES = {
    "__pycache__", ".pytest_cache", ".venv", "venv", "node_modules",
    "site-packages", "dist", "build", ".git", ".github", ".vscode",
    ".claude", ".mypy_cache", ".ruff_cache", ".idea",
}
# …or by suffix…
SKIP_SUFFIXES = (".egg-info",)
# …or by path relative to the repo root (language mirrors / assets / runtime).
SKIP_RELPATHS = {
    "workspace", "docs/assets", "docs/i18n", "docs/ja", "docs/zh",
    "report/en", "report/ja", "report/zh", "ari-core/ari/viz/static",
}

# Directories listed as a single leaf (kept visible, contents not enumerated).
# Keyed by bare name…
NOT_ENUMERATED = {
    "vendor": "vendored third-party source (not enumerated)",
    "fixtures": "test fixtures (not enumerated)",
}
# …or by repo-relative path (generated figure artifact dirs).
NOT_ENUMERATED_RELPATHS = {
    "report/shared/figures/data": "figure data files (not enumerated)",
    "report/shared/figures/dot": "Graphviz figure sources (not enumerated)",
    "report/shared/figures/pgf": "generated PGF figures (not enumerated)",
    "report/shared/figures/preview": "rendered figure previews (not enumerated)",
    "report/shared/figures/tikz": "TikZ figure sources (not enumerated)",
}

CONTENTS_HEADING = "## Contents"
# `- name` or `- name — description`, 2-space indent per nesting level.
BULLET_RE = re.compile(r"^(?P<indent> *)- `(?P<name>[^`]+)`(?: +[—-] +(?P<desc>.*))?\s*$")


def rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def is_skipped(path: Path) -> bool:
    if path.name in SKIP_NAMES or path.name.endswith(SKIP_SUFFIXES):
        return True
    return rel(path) in SKIP_RELPATHS


def ordered_children(d: Path) -> list[Path]:
    """README.md, then __init__.py, then other files (sorted), then dirs."""
    files, dirs = [], []
    for child in sorted(d.iterdir(), key=lambda p: p.name.lower()):
        if is_skipped(child):
            continue
        if child.is_dir():
            dirs.append(child)
        elif child.is_file() and not child.name.endswith(".pyc"):
            files.append(child)

    def file_key(p: Path) -> tuple:
        return (p.name != "README.md", p.name != "__init__.py", p.name.lower())

    return sorted(files, key=file_key) + dirs


class Entry:
    __slots__ = ("depth", "relpath", "name", "is_dir", "leaf")

    def __init__(self, depth: int, relpath: str, name: str, is_dir: bool, leaf: bool):
        self.depth, self.relpath, self.name = depth, relpath, name
        self.is_dir, self.leaf = is_dir, leaf  # leaf: dir listed but not descended


def leaf_note(child: Path) -> str | None:
    """If ``child`` should be listed but NOT descended into, return its note.

    Boundaries: explicit not-enumerated dirs, generated artifact dirs, and any
    directory documented by a CURATED README (one without ``## Contents``) —
    that README owns its subtree, so we stop and let it track its own files."""
    if child.name in NOT_ENUMERATED:
        return NOT_ENUMERATED[child.name]
    if rel(child) in NOT_ENUMERATED_RELPATHS:
        return NOT_ENUMERATED_RELPATHS[rel(child)]
    readme = child / "README.md"
    if readme.is_file() and CONTENTS_HEADING not in readme.read_text(encoding="utf-8"):
        return (role_line(readme) or "documented in its own README").rstrip(".")
    return None


def walk(d: Path, base: Path, depth: int = 0) -> list[Entry]:
    """Recursive listing of ``d`` as it should appear in base's Contents."""
    out: list[Entry] = []
    for child in ordered_children(d):
        relpath = child.relative_to(base).as_posix()
        if child.is_dir():
            note = leaf_note(child)
            out.append(Entry(depth, relpath + "/", child.name + "/", True, note is not None))
            if note is None:
                out.extend(walk(child, base, depth + 1))
        else:
            out.append(Entry(depth, relpath, child.name, False, False))
    return out


# ── README parse / render ────────────────────────────────────────────────

def split_readme(text: str) -> tuple[str, list[str], str] | None:
    """Return (head, contents_lines, tail) or None if no ``## Contents``.

    head  = everything up to and including the ``## Contents`` line + trailing blank.
    tail  = the next ``## `` section onwards (e.g. ``## See also``), or "".
    """
    lines = text.splitlines()
    try:
        ci = next(i for i, l in enumerate(lines) if l.strip() == CONTENTS_HEADING)
    except StopIteration:
        return None
    ti = len(lines)
    for i in range(ci + 1, len(lines)):
        if lines[i].startswith("## "):
            ti = i
            break
    head = "\n".join(lines[: ci + 1])
    contents = lines[ci + 1 : ti]
    tail = "\n".join(lines[ti:])
    return head, contents, tail


def parse_contents(lines: list[str]) -> tuple[list[str], dict[str, str]]:
    """Parse a Contents block into (ordered relpaths, relpath -> description)."""
    paths: list[str] = []
    desc: dict[str, str] = {}
    stack: list[str] = []  # names by depth, dirs keep trailing "/"
    for line in lines:
        m = BULLET_RE.match(line)
        if not m:
            continue
        depth = len(m.group("indent")) // 2
        name = m.group("name")
        stack = stack[:depth]
        stack.append(name)
        relpath = "".join(
            s if s.endswith("/") else s + "/" for s in stack[:-1]
        ) + name
        paths.append(relpath)
        if m.group("desc"):
            desc[relpath] = m.group("desc").strip()
    return paths, desc


def render(entries: list[Entry], descriptions: dict[str, str]) -> str:
    out = ["- `README.md` — this file."]
    for e in entries:
        if e.name == "README.md":
            continue  # rendered per-dir below as "<dir> index."
        indent = "  " * e.depth
        out.append(f"{indent}- `{e.name}` — {descriptions[e.relpath]}")
    return "\n".join(out)


# ── descriptions ───────────────────────────────────────────────────────────

def role_line(readme: Path) -> str | None:
    """First non-empty line of a README's body (its role sentence)."""
    if not readme.is_file():
        return None
    body = False
    for line in readme.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            body = True
            continue
        if body and line.strip() and not line.startswith("#"):
            return line.strip()
    return None


def make_description(entry: Entry, base: Path, fallback: str = "TODO") -> str:
    """Deterministic description for an entry that has none yet.

    Directories borrow their own README's role line; files get ``TODO`` for a
    human to fill in. This tool NEVER calls an LLM / API — new-file prose is
    authored by hand (see the module docstring)."""
    abspath = base / entry.relpath.rstrip("/")
    if entry.is_dir:
        if entry.name.rstrip("/") in NOT_ENUMERATED:
            return NOT_ENUMERATED[entry.name.rstrip("/")]
        sub = role_line(abspath / "README.md")
        if sub:
            return sub if len(sub) >= 90 else sub.rstrip(".")
    return fallback


# ── README discovery ─────────────────────────────────────────────────────

def managed_readmes() -> list[Path]:
    out = []
    for readme in REPO_ROOT.rglob("README.md"):
        if any(part in SKIP_NAMES or part.endswith(SKIP_SUFFIXES) for part in readme.parts):
            continue
        if rel(readme.parent) in SKIP_RELPATHS or any(
            rel(readme.parent).startswith(p + "/") for p in SKIP_RELPATHS
        ):
            continue
        if CONTENTS_HEADING in readme.read_text(encoding="utf-8"):
            out.append(readme)
    return sorted(out)


def build_desc_index() -> dict[str, str]:
    """repo-relative path -> description, harvested from every managed README.

    Lets a parent README reuse the description a file already has in its own
    directory's README (so inlining a subtree needs no rewriting). When a file
    is listed in several READMEs (a child's own + a parent's inlined copy), the
    CLOSEST README wins — i.e. the file's own directory README is canonical, so
    a parent's stale inlined copy can never clobber it."""
    best: dict[str, tuple[int, str]] = {}  # key -> (base depth, description)
    for readme in managed_readmes():
        split = split_readme(readme.read_text(encoding="utf-8"))
        if not split:
            continue
        _, desc = parse_contents(split[1])
        base = rel(readme.parent)
        depth = 0 if base == "." else base.count("/") + 1
        for p, d in desc.items():
            if d == "TODO":
                continue  # don't let a placeholder stick; leave it to be filled
            key = (f"{base}/{p}" if base != "." else p).rstrip("/")
            if key not in best or depth > best[key][0]:
                best[key] = (depth, d)
    return {k: v[1] for k, v in best.items()}


# ── modes ──────────────────────────────────────────────────────────────────

def check() -> int:
    drift = 0
    for readme in managed_readmes():
        split = split_readme(readme.read_text(encoding="utf-8"))
        if not split:
            continue
        listed, _ = parse_contents(split[1])
        listed_set = {p for p in listed if p != "README.md"}
        actual = {e.relpath for e in walk(readme.parent, readme.parent) if e.relpath != "README.md"}
        missing = sorted(actual - listed_set)   # on disk, not in README
        extra = sorted(listed_set - actual)     # in README, gone from disk
        if missing or extra:
            drift += 1
            print(f"DRIFT {rel(readme)}")
            for p in missing:
                print(f"  + {p}  (on disk, not listed)")
            for p in extra:
                print(f"  - {p}  (listed, not on disk)")
    if drift:
        print(f"\n{drift} README(s) out of sync. Run: python scripts/readme_sync.py --write")
        return 1
    print("All managed READMEs are in sync.")
    return 0


def write() -> int:
    index = build_desc_index()
    changed = 0
    for readme in managed_readmes():
        text = readme.read_text(encoding="utf-8")
        split = split_readme(text)
        if not split:
            continue
        head, _old_lines, tail = split
        base = rel(readme.parent)
        entries = walk(readme.parent, readme.parent)

        descriptions: dict[str, str] = {}
        for e in entries:
            if e.name == "README.md":
                continue
            key = (f"{base}/{e.relpath}" if base != "." else e.relpath).rstrip("/")
            if e.is_dir and e.leaf:
                descriptions[e.relpath] = leaf_note(readme.parent / e.relpath.rstrip("/")) or "not enumerated"
            else:
                descriptions[e.relpath] = index.get(key) or make_description(e, readme.parent)
        # nested README.md entries -> "<dir> index."
        new_lines = _render_with_indexes(entries, descriptions, readme.parent)

        new_text = head + "\n\n" + new_lines + ("\n\n" + tail if tail else "") + "\n"
        new_text = re.sub(r"\n{3,}", "\n\n", new_text)
        if new_text != text:
            readme.write_text(new_text, encoding="utf-8")
            changed += 1
            print(f"updated {rel(readme)}")
    print(f"\n{changed} README(s) updated.")
    return 0


def _render_with_indexes(entries, descriptions, base) -> str:
    out = ["- `README.md` — this file."]
    for e in entries:
        indent = "  " * e.depth
        if e.name == "README.md":
            if e.relpath == "README.md":
                continue  # the dir's own README — already rendered above
            parent_name = Path(e.relpath).parent.name
            out.append(f"{indent}- `README.md` — {parent_name} index.")
        else:
            out.append(f"{indent}- `{e.name}` — {descriptions[e.relpath]}")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="fail on path drift (CI gate)")
    g.add_argument("--write", action="store_true",
                   help="regenerate Contents blocks; new files get TODO (fill by hand)")
    args = ap.parse_args()
    return check() if args.check else write()


if __name__ == "__main__":
    raise SystemExit(main())
