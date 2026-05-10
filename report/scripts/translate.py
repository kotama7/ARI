#!/usr/bin/env python3
"""LLM translation pipeline for the ARI report.

Reads English chapter sources (`en/chapters/*.tex`) and produces matching
`ja/chapters/*.tex` / `zh/chapters/*.tex` with:

  * paragraph-level Anthropic Claude calls (model pinned, temperature=0)
  * placeholder protection for math, \\cite, \\label, \\ref, \\verb, listings, comments
  * paragraph-hash cache (`scripts/translation_cache.json`) keyed by
    sha256(en_paragraph) ⨯ glossary_hash ⨯ model
  * per-file header
        % translated-from: en/chapters/<name>@<en_sha256>
        % glossary:        <glossary_sha256>
        % model:           <model_name>

Usage:
    python translate.py --target ja --files en/chapters/03_exploration.tex
    python translate.py --target zh --all
    python translate.py --target ja --changed     # only paragraphs whose hash misses cache
    python translate.py --bump-glossary           # invalidate cache (no API calls)

Exit 0 on success, 1 on validation failure or unrecoverable API error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import yaml

REPORT_ROOT = Path(__file__).resolve().parent.parent
SHARED = REPORT_ROOT / "shared"
GLOSSARY = SHARED / "glossary.yaml"
CACHE_PATH = REPORT_ROOT / "scripts" / "translation_cache.json"
PROMPTS = REPORT_ROOT / "scripts" / "prompts"
ENV_PATH = REPORT_ROOT.parent / ".env"

DEFAULT_MODEL = "claude-opus-4-7"

# ----------------------------------------------------------------- protected spans
PROTECTED_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("displaymath",   re.compile(r"\\\[.*?\\\]", re.DOTALL)),
    ("equation",      re.compile(r"\\begin\{(?:equation|align|gather|multline)\*?\}.*?\\end\{(?:equation|align|gather|multline)\*?\}", re.DOTALL)),
    ("inlinemath",    re.compile(r"\$[^$\n]+\$")),
    ("verb",          re.compile(r"\\verb\|[^|]*\|")),
    ("verbatim",      re.compile(r"\\begin\{(?:verbatim|lstlisting|minted|Verbatim)\}.*?\\end\{(?:verbatim|lstlisting|minted|Verbatim)\}", re.DOTALL)),
    ("cite",          re.compile(r"\\cite\w*\s*\{[^}]+\}")),
    ("label",         re.compile(r"\\label\s*\{[^}]+\}")),
    ("ref",           re.compile(r"\\(?:ref|eqref|autoref|cref|Cref)\s*\{[^}]+\}")),
    ("texttt",        re.compile(r"\\texttt\s*\{[^}]+\}")),
    ("comment",       re.compile(r"(?<!\\)%[^\n]*")),
    ("input",         re.compile(r"\\input\s*\{[^}]+\}")),
    ("includegraphics", re.compile(r"\\includegraphics(?:\[[^\]]*\])?\s*\{[^}]+\}")),
    ("figlabel",      re.compile(r"\\figlabel\s*\{[^}]+\}")),
    ("term",          re.compile(r"\\term\s*\{[^}]+\}")),
    ("custom_macro",  re.compile(r"\\(?:Nodes|Tree|children|parentof|axes|nodescore|utility|policy|softmaxbeta|paper|paperscore)\b(?:\[[^\]]*\])?\{?[^}\s]*\}?")),
]


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k in {"ANTHROPIC_API_KEY"}})
    return env


def _glossary_for_lang(target: str) -> tuple[str, dict, dict]:
    raw = GLOSSARY.read_bytes()
    g = yaml.safe_load(raw.decode("utf-8")) or {}
    pairs = {e["en"]: e[target] for e in g.get("entries", []) if target in e}
    forb = (g.get("forbidden_alternatives") or {}).get(target, {})
    return _sha256(raw), pairs, forb


def _glossary_table(pairs: dict, target: str) -> str:
    return "\n".join(f"- {en} → {tgt}" for en, tgt in pairs.items())


def _forbidden_table(forb: dict) -> str:
    return "\n".join(f"- {canon}: never use {alts}" for canon, alts in forb.items())


# ----------------------------------------------------------------- protect / restore
def protect(text: str) -> tuple[str, list[str]]:
    spans: list[tuple[int, int, str]] = []
    for _name, pat in PROTECTED_PATTERNS:
        for m in pat.finditer(text):
            spans.append((m.start(), m.end(), m.group(0)))
    spans.sort()
    # merge overlapping spans (e.g. cite inside displaymath)
    merged: list[tuple[int, int, str]] = []
    for s, e, t in spans:
        if merged and s < merged[-1][1]:
            continue
        merged.append((s, e, t))
    placeholders: list[str] = []
    out: list[str] = []
    cursor = 0
    for idx, (s, e, t) in enumerate(merged):
        out.append(text[cursor:s])
        out.append(f"__PLACEHOLDER_{idx}__")
        placeholders.append(t)
        cursor = e
    out.append(text[cursor:])
    return "".join(out), placeholders


def restore(text: str, placeholders: list[str]) -> str:
    for i, t in enumerate(placeholders):
        text = text.replace(f"__PLACEHOLDER_{i}__", t)
    return text


# ----------------------------------------------------------------- cache
def _load_cache() -> dict:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {"version": 1, "entries": {}}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2),
                          encoding="utf-8")


# ----------------------------------------------------------------- LLM
def _translate_via_anthropic(paragraph_protected: str, target: str,
                             model: str, glossary_table: str,
                             forbidden_table: str, env: dict) -> str:
    api_key = env.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set; cannot translate")
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError("anthropic SDK missing; pip install anthropic") from e
    client = anthropic.Anthropic(api_key=api_key)
    sys_tmpl = (PROMPTS / "translate_system.md").read_text(encoding="utf-8")
    usr_tmpl = (PROMPTS / "translate_user.md").read_text(encoding="utf-8")
    sys_prompt = (sys_tmpl
                  .replace("{TARGET}", target)
                  .replace("{GLOSSARY_TABLE}", glossary_table)
                  .replace("{FORBIDDEN_TABLE}", forbidden_table))
    user = usr_tmpl.replace("{TARGET}", target).replace("{PARAGRAPH}", paragraph_protected)
    resp = client.messages.create(
        model=model,
        max_tokens=2048,
        temperature=0,
        system=sys_prompt,
        messages=[{"role": "user", "content": user}],
    )
    return resp.content[0].text.strip()


# ----------------------------------------------------------------- pipeline
def translate_paragraph(paragraph: str, target: str, model: str,
                        glossary_hash: str, glossary_pairs: dict,
                        forbidden: dict, env: dict, cache: dict,
                        dry_run: bool = False) -> str | None:
    protected, placeholders = protect(paragraph)
    pkey = _sha256(paragraph.encode("utf-8"))
    cache_entry = cache["entries"].get(pkey, {})
    if (cache_entry.get("glossary_hash") == glossary_hash
            and cache_entry.get("model") == model
            and target in cache_entry):
        translated_protected = cache_entry[target]
    else:
        if dry_run:
            return None
        translated_protected = _translate_via_anthropic(
            protected, target, model,
            _glossary_table(glossary_pairs, target),
            _forbidden_table(forbidden), env,
        )
        cache["entries"].setdefault(pkey, {}).update({
            target: translated_protected,
            "glossary_hash": glossary_hash,
            "model": model,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        })
    return restore(translated_protected, placeholders)


def split_paragraphs(text: str) -> Iterable[str]:
    # paragraphs are separated by ≥ one blank line
    for chunk in re.split(r"\n\s*\n", text):
        chunk = chunk.strip("\n")
        if chunk:
            yield chunk


def translate_file(en_file: Path, target: str, model: str,
                   glossary_hash: str, glossary_pairs: dict, forbidden: dict,
                   env: dict, cache: dict, only_changed: bool,
                   dry_run: bool) -> bool:
    out_dir = REPORT_ROOT / target / "chapters"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / en_file.name

    en_bytes = en_file.read_bytes()
    en_hash = _sha256(en_bytes)
    text = en_bytes.decode("utf-8")
    paragraphs = list(split_paragraphs(text))

    new_paragraphs: list[str] = []
    for p in paragraphs:
        translated = translate_paragraph(
            p, target, model, glossary_hash, glossary_pairs, forbidden, env, cache,
            dry_run=dry_run,
        )
        if translated is None:
            new_paragraphs.append(p)  # leave English in place during dry-run misses
        else:
            new_paragraphs.append(translated)

    header = (f"% translated-from: en/chapters/{en_file.name}@{en_hash}\n"
              f"% glossary:        {glossary_hash}\n"
              f"% model:           {model}\n\n")
    out_file.write_text(header + "\n\n".join(new_paragraphs) + "\n", encoding="utf-8")
    print(f"[translate] {target} ← {en_file.name}  paragraphs={len(paragraphs)}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["ja", "zh"], required=True)
    sel = ap.add_mutually_exclusive_group(required=True)
    sel.add_argument("--all", action="store_true")
    sel.add_argument("--changed", action="store_true")
    sel.add_argument("--files", nargs="+", type=Path)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--bump-glossary", action="store_true",
                    help="clear cache entries that don't match current glossary hash")
    ap.add_argument("--dry-run", action="store_true",
                    help="don't call LLM; report which paragraphs miss cache")
    args = ap.parse_args()

    glossary_hash, pairs, forbidden = _glossary_for_lang(args.target)
    cache = _load_cache()

    if args.bump_glossary:
        before = len(cache["entries"])
        cache["entries"] = {k: v for k, v in cache["entries"].items()
                            if v.get("glossary_hash") == glossary_hash}
        _save_cache(cache)
        print(f"[translate] cache pruned {before - len(cache['entries'])} stale entries")
        return 0

    env = _load_env()
    en_dir = REPORT_ROOT / "en" / "chapters"
    if args.files:
        files = list(args.files)
    elif args.all or args.changed:
        files = sorted(en_dir.glob("*.tex"))
    else:
        files = []

    ok = True
    for en_file in files:
        if not translate_file(en_file, args.target, args.model,
                              glossary_hash, pairs, forbidden, env, cache,
                              only_changed=args.changed, dry_run=args.dry_run):
            ok = False

    _save_cache(cache)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
