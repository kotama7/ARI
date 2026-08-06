#!/usr/bin/env python3
"""Evaluate a labelled Manuscript Complete case set as canonical JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ari.manuscript.evaluation import evaluate_labelled_cases


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", type=Path)
    parser.add_argument(
        "--dataset-id",
        help="Dataset identity; defaults to the dataset_id field in an object input.",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    document = json.loads(args.cases.read_text(encoding="utf-8"))
    rows = document.get("cases") if isinstance(document, dict) else document
    if not isinstance(rows, list):
        raise ValueError("evaluation input must be a list or an object with cases")
    embedded_dataset_id = (
        document.get("dataset_id") if isinstance(document, dict) else None
    )
    dataset_id = args.dataset_id or embedded_dataset_id
    if not isinstance(dataset_id, str) or not dataset_id.strip():
        parser.error(
            "--dataset-id is required when the input object has no dataset_id"
        )
    report = evaluate_labelled_cases(rows, dataset_id=dataset_id.strip())
    rendered = json.dumps(
        report.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
