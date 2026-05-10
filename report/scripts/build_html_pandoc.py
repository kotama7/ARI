#!/usr/bin/env python3
"""Build the HTML rendering of the ARI report using pandoc.

The earlier `make4ht` toolchain produced HTML for the LaTeX sources but
silently dropped Japanese dakuten/handakuten marks during the lualatex
HTML conversion (e.g. "ルブリック" rendered as "ルフリック"), and the
zh build was missing CJK output entirely until a binhex shim was added.

Pandoc's LaTeX->HTML5 reader avoids both problems: it does not call
TeX font shapers at all, so CJK code points pass through cleanly.
TikZ figures, however, are dropped (pandoc cannot render TikZ), so we
post-process the HTML to inject <img> tags pointing at the
shared/figures/preview/*.png renders that the report build pipeline
already maintains.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Figure id -> preview PNG basename (lives under shared/figures/preview/)
# These mirror the \label{fig:...} entries in {en,ja,zh}/chapters/*.tex.
FIGURE_MAP: dict[str, str] = {
    "fig:fullstack":    "F10_full_stack-1.png",
    "fig:architecture": "F01_architecture-1.png",
    "fig:pipeline":     "F05_pipeline_dag-1.png",
    "fig:bftsflow":     "F11_bfts_control-1.png",
    "fig:paperre":      "F12_paperre_components-1.png",
    "fig:checkpoint":   "F13_checkpoint_layout-1.png",
    "fig:nodescore":    "F03_node_score-1.png",
    "fig:react":        "F04_react_loop-1.png",
    "fig:swim":         "F06_paper_swimlane-1.png",
}

LANG_TITLES: dict[str, str] = {
    "en": "ARI: An Autonomous Research Infrastructure",
    "ja": "ARI: 自律型研究基盤",
    "zh": "ARI:自主研究基础设施",
}

LANG_NAV = """\
<nav class="ari-langnav" style="position:fixed;top:0.6em;right:0.8em;font-size:0.9em;background:#fff;padding:0.2em 0.5em;border:1px solid #ddd;border-radius:4px;z-index:1000;">
  <a href="../en/index.html">en</a> |
  <a href="../ja/index.html">ja</a> |
  <a href="../zh/index.html">zh</a>
</nav>"""

# Figure CSS appended to the end of <head>. Width is capped at the
# pandoc body's ~36em so the figure never spills past the prose column.
FIGURE_CSS = """\
<style>
  figure { margin: 1.6em 0; text-align: center; }
  figure img { max-width: 100%; height: auto; border: 1px solid #ddd; padding: 4px; background:#fff; }
  figure figcaption { font-size: 0.92em; color: #333; margin-top: 0.4em; }
  body { max-width: 48em; }
  pre, code { font-family: 'Source Code Pro', 'Menlo', monospace; font-size: 0.92em; }
  h1 { border-bottom: 2px solid #0072b2; padding-bottom: 0.2em; }
  h2 { border-bottom: 1px solid #ddd; padding-bottom: 0.15em; }
</style>"""


def run_pandoc(main_tex: Path, out_html: Path, lang: str) -> None:
    title = LANG_TITLES[lang]
    cmd = [
        "pandoc",
        "-f", "latex",
        "-t", "html5",
        "--standalone",
        "--mathjax",
        "--metadata", f"title={title}",
        "--metadata", f"lang={lang}",
        "-o", str(out_html),
        str(main_tex),
    ]
    subprocess.run(cmd, check=True, cwd=main_tex.parent)


def inject_figures(html_path: Path, figures_rel: str) -> int:
    """Insert <img> tags into <figure id="fig:..."> blocks.

    Returns the number of figure ids that received an <img>.
    """
    text = html_path.read_text(encoding="utf-8")
    inserted = 0

    def replace(match: re.Match) -> str:
        nonlocal inserted
        fig_id = match.group("id")
        body = match.group("body")
        if "<img" in body:
            return match.group(0)
        png = FIGURE_MAP.get(fig_id)
        if not png:
            return match.group(0)
        img = f'<img src="{figures_rel}/{png}" alt="{fig_id}" />\n'
        inserted += 1
        return f'<figure id="{fig_id}"' + match.group("attrs") + ">\n" + img + body + "</figure>"

    pattern = re.compile(
        r'<figure id="(?P<id>fig:[^"]+)"(?P<attrs>[^>]*)>(?P<body>.*?)</figure>',
        re.DOTALL,
    )
    new_text = pattern.sub(replace, text)
    html_path.write_text(new_text, encoding="utf-8")
    return inserted


def inject_chrome(html_path: Path) -> None:
    """Inject the language switcher and figure CSS."""
    text = html_path.read_text(encoding="utf-8")
    if 'class="ari-langnav"' not in text:
        text = re.sub(r"(<body[^>]*>)", r"\1\n" + LANG_NAV, text, count=1)
    if "ari-figure-css" not in text and "figure { margin: 1.6em 0;" not in text:
        text = text.replace("</head>", FIGURE_CSS + "\n</head>", 1)
    html_path.write_text(text, encoding="utf-8")


def build_lang(lang: str) -> dict[str, int | str]:
    src = ROOT / lang / "main.tex"
    out_dir = ROOT / "html" / lang
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "index.html"

    run_pandoc(src, out, lang)
    figures_rel = "../../shared/figures/preview"
    figures_inserted = inject_figures(out, figures_rel)
    inject_chrome(out)

    size = out.stat().st_size
    return {"lang": lang, "out": str(out.relative_to(ROOT)), "size": size, "figures": figures_inserted}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=("en", "ja", "zh", "all"), default="all")
    args = ap.parse_args()

    langs = ["en", "ja", "zh"] if args.lang == "all" else [args.lang]
    for lang in langs:
        result = build_lang(lang)
        print(f"  {result['lang']}: {result['out']} ({result['size']}b, {result['figures']}/9 figures)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
