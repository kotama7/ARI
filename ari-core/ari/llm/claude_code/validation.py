"""ARI-side JSON schema validation for Claude Code outputs.

Claude Code's native ``--json-schema`` transport already validates on its
side, but ARI never trusts that alone: EVERY schema-bearing response is
re-validated here (jsonschema Draft 2020-12) before it reaches a caller.
The outcome is persisted to validation.json either way.
"""

from __future__ import annotations

import json
from typing import Any


class ClaudeCodeSchemaError(RuntimeError):
    """Output failed schema validation (after any repair retry)."""

    def __init__(self, errors: list[str], provenance_path: str | None) -> None:
        self.errors = errors
        self.provenance_path = provenance_path
        where = f" (provenance: {provenance_path})" if provenance_path else ""
        super().__init__(
            "claude_code output failed JSON schema validation"
            + where
            + ":\n- "
            + "\n- ".join(errors[:10])
        )


def extract_json(text: str) -> Any:
    """Parse the model's text output as JSON, tolerating markdown fences
    and surrounding prose. Raises ValueError when no JSON value is found."""
    s = (text or "").strip()
    if s.startswith("```"):
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1 :]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
        s = s.strip()
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        pass
    # Fall back to balanced {...}/[...] spans. EVERY opening bracket is a
    # candidate (in order of appearance), because prose before the JSON can
    # itself contain braces — set notation, code, LaTeX — whose span either
    # fails json.loads or never balances; giving up on the first candidate
    # would burn the repair retry on perfectly recoverable output.
    for start, open_ch in ((i, c) for i, c in enumerate(s) if c in "{["):
        close_ch = "}" if open_ch == "{" else "]"
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(s)):
            c = s[i]
            if in_str:
                if escape:
                    escape = False
                elif c == "\\":
                    escape = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == open_ch:
                depth += 1
            elif c == close_ch:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(s[start : i + 1])
                    except (json.JSONDecodeError, ValueError):
                        break
    raise ValueError(f"no JSON value found in output: {s[:200]!r}")


def validate_against_schema(obj: Any, schema: dict) -> list[str]:
    """Return a list of validation error messages ([] when valid)."""
    try:
        import jsonschema
    except ImportError as e:  # pragma: no cover — declared dependency
        raise RuntimeError(
            "jsonschema is required for claude_code response_schema "
            "validation (pip install jsonschema)"
        ) from e
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)
    return [
        f"{'/'.join(str(p) for p in err.absolute_path) or '<root>'}: {err.message}"
        for err in sorted(validator.iter_errors(obj), key=str)
    ]
