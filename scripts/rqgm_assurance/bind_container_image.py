#!/usr/bin/env python3
"""Establish what is inside a Harness container image, and bind it to the file.

A manifest pins container CONTENT, because that is what a verdict depends on and
it is what survives the image being fetched again: two pulls of one tag differ
byte for byte and agree on every filesystem entry except the runtime's own
build-date metadata. Reading the whole rootfs is far too slow to do per run, so
it is done here, once, and recorded beside the image.

Run this after obtaining or re-obtaining an image. It does not change any
manifest and needs no approval: it asserts nothing about whether the content is
the RIGHT content -- it only records what the content is. The manifest's pin is
what decides whether that content may verify anything, and the executor compares
the two.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "ari-core"))

from ari.assurance.container_identity import (  # noqa: E402
    file_digest,
    rootfs_content_digest,
    write_binding,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path,
                        help="the SIF to establish the content of")
    parser.add_argument("--work-dir", type=Path, default=None,
                        help="where to extract while reading; needs room for the "
                             "whole rootfs")
    arguments = parser.parse_args(argv)

    image = arguments.image.resolve(strict=True)
    if image.is_symlink() or not image.is_file():
        raise SystemExit("the image must be a regular file")
    content_digest, entries = rootfs_content_digest(image, work_dir=arguments.work_dir)
    entry = write_binding(image.parent, image=image, content_digest=content_digest,
                          entry_count=entries)
    print(json.dumps({
        "image": image.name,
        "file_digest": file_digest(image),
        "content_digest": content_digest,
        "entry_count": entries,
        "excluded_paths": entry["excluded_paths"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
