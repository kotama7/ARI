"""Line-oriented subprocess fixture used by secure stdio proxy tests."""

from __future__ import annotations

import json
import os
import sys


for line in sys.stdin:
    if not line:
        break
    secret = os.environ.get("FIXTURE_SECRET", "")
    print(
        json.dumps(
            {
                "allowed": os.environ.get("FIXTURE_ALLOWED"),
                "secret": secret,
                "undeclared": os.environ.get("FIXTURE_UNDECLARED"),
            }
        ),
        flush=True,
    )
    print(f"fixture stderr {secret}", file=sys.stderr, flush=True)
