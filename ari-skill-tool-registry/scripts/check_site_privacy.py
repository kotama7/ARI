#!/usr/bin/env python3
"""Fail if a private scheduler site identity can enter the Git snapshot."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parent
if str(PACKAGE_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from site_privacy import (  # noqa: E402
    assert_repository_site_anonymous,
    load_private_site_config,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=str(REPO_ROOT))
    parser.add_argument(
        "--site-config",
        default=os.environ.get(
            "ARI_PRIVATE_SLURM_SITE_CONFIG",
            str(REPO_ROOT / "workspace" / "openroad-slurm-site-v1.json"),
        ),
    )
    args = parser.parse_args(argv)
    try:
        repository = Path(args.repository).resolve(strict=True)
        site = load_private_site_config(args.site_config, repository=repository)
        assert_repository_site_anonymous(repository, site=site)
    except Exception as exc:
        # Do not forward arbitrary exception text: a malformed external path
        # can itself contain private site identity.  Detailed inspection stays
        # local to the operator; hook and CI output disclose only the class.
        print(f"site-privacy-audit: FAIL ({type(exc).__name__})", file=sys.stderr)
        return 1
    print("site-privacy-audit: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
