"""Fail-closed protection for private scheduler site identities.

Physical cluster, partition, and node selectors are runtime inputs.  A
promotion bundle may bind their salted identity digest, but it must never
publish the clear selectors in a file that Git can track.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from providers import ProviderProtocolError


PRIVATE_SITE_SCHEMA = "ari.openroad-slurm-site/v1"
PRIVATE_SITE_FIELDS = (
    "schema_version",
    "site_nonce",
    "cluster_name",
    "partition",
    "node_name",
)
_HIGH_ENTROPY_NONCE = re.compile(r"[0-9a-f]{64}")
_SITE_SELECTOR = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,127}")
_TOKEN_ALPHABET = rb"A-Za-z0-9_.:@+-"


def _git(
    repository: Path, arguments: list[str], *, check: bool = True
) -> subprocess.CompletedProcess[bytes]:
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=False,
        capture_output=True,
        timeout=30,
    )
    if check and completed.returncode:
        raise ProviderProtocolError("Git site-privacy inspection failed")
    return completed


def _repository_relative(path: Path, repository: Path) -> str | None:
    try:
        return path.resolve().relative_to(repository.resolve()).as_posix()
    except ValueError:
        return None


def load_private_site_config(
    path: str | Path,
    *,
    repository: str | Path,
) -> dict[str, str]:
    """Load an ignored, untracked site config with a salted private identity."""

    site_path = Path(path).resolve(strict=True)
    repository_path = Path(repository).resolve(strict=True)
    if site_path.is_symlink() or not site_path.is_file():
        raise ProviderProtocolError("private site configuration must be a regular file")
    relative = _repository_relative(site_path, repository_path)
    if relative is not None:
        tracked = _git(
            repository_path,
            ["ls-files", "--error-unmatch", "--", relative],
            check=False,
        )
        if tracked.returncode == 0:
            raise ProviderProtocolError(
                "private site configuration must not be Git-tracked"
            )
        ignored = _git(
            repository_path,
            ["check-ignore", "--quiet", "--", relative],
            check=False,
        )
        if ignored.returncode != 0:
            raise ProviderProtocolError(
                "private site configuration must be covered by a Git ignore rule"
            )
    try:
        value = json.loads(site_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderProtocolError("private site configuration is invalid") from exc
    if (
        not isinstance(value, dict)
        or tuple(sorted(value)) != tuple(sorted(PRIVATE_SITE_FIELDS))
        or value.get("schema_version") != PRIVATE_SITE_SCHEMA
        or not all(isinstance(value.get(field), str) for field in PRIVATE_SITE_FIELDS)
        or not _HIGH_ENTROPY_NONCE.fullmatch(str(value.get("site_nonce", "")))
        or not all(
            _SITE_SELECTOR.fullmatch(str(value.get(field, "")))
            for field in ("cluster_name", "partition", "node_name")
        )
    ):
        raise ProviderProtocolError(
            "private site configuration requires exact selectors and a 256-bit nonce"
        )
    return {field: str(value[field]) for field in PRIVATE_SITE_FIELDS}


def git_trackable_paths(
    repository: str | Path,
    *,
    pathspecs: Iterable[str] = (),
) -> tuple[Path, ...]:
    """Return tracked plus non-ignored untracked paths for a future commit."""

    repository_path = Path(repository).resolve(strict=True)
    arguments = ["ls-files", "-z", "--cached", "--others", "--exclude-standard"]
    selected = tuple(pathspecs)
    if selected:
        arguments.extend(["--", *selected])
    completed = _git(repository_path, arguments)
    paths: list[Path] = []
    for raw_relative in completed.stdout.split(b"\0"):
        if not raw_relative:
            continue
        relative = raw_relative.decode("utf-8", errors="surrogateescape")
        paths.append(repository_path / relative)
    return tuple(paths)


def _contains_literal(path: Path, literal: bytes) -> bool:
    overlap = max(len(literal) - 1, 0)
    previous = b""
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value = previous + chunk
            if literal in value.lower():
                return True
            previous = value[-overlap:] if overlap else b""
    return False


def _symlink_contains_literal(path: Path, literal: bytes) -> bool:
    try:
        target = path.readlink().as_posix().encode(
            "utf-8", errors="surrogateescape"
        )
    except OSError as exc:
        raise ProviderProtocolError(
            "Git-trackable symlink could not be inspected"
        ) from exc
    return literal in target.lower()


def _git_index_contains_literal(repository: Path, literal: bytes) -> bool:
    """Inspect staged blob bytes without exposing the private literal in argv."""

    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "grep",
            "--cached",
            "--quiet",
            "-a",
            "-i",
            "-F",
            "-f",
            "-",
            "--",
        ],
        input=literal + b"\n",
        check=False,
        capture_output=True,
        timeout=30,
    )
    if completed.returncode == 0:
        return True
    if completed.returncode == 1:
        return False
    raise ProviderProtocolError("Git index site-privacy inspection failed")


def _contains_bounded_token(path: Path, token: bytes) -> bool:
    pattern = re.compile(
        rb"(?<![" + _TOKEN_ALPHABET + rb"])(?:" + re.escape(token) + rb")"
        rb"(?![" + _TOKEN_ALPHABET + rb"])",
        flags=re.IGNORECASE,
    )
    overlap = len(token) + 2
    previous = b""
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value = previous + chunk
            if pattern.search(value):
                return True
            previous = value[-overlap:]
    return False


def assert_no_private_site_identity(
    paths: Iterable[Path],
    *,
    site: Mapping[str, str],
    reject_partition: bool = True,
) -> None:
    """Reject clear private site identity from publishable files and names.

    Node, cluster, and nonce values are rejected as substrings, including in
    FQDNs and scheduler prose.  Partition values are rejected as bounded
    tokens because short generic partition labels may legitimately occur as
    parts of unrelated identifiers.
    """

    substring_fields = ("node_name", "cluster_name", "site_nonce")
    token_fields = ("partition",) if reject_partition else ()
    for path in paths:
        path_bytes = path.as_posix().encode("utf-8", errors="surrogateescape").lower()
        for field in substring_fields:
            literal = str(site[field]).encode("utf-8").lower()
            if literal in path_bytes or (
                path.is_symlink() and _symlink_contains_literal(path, literal)
            ) or (
                path.is_file() and _contains_literal(path, literal)
            ):
                raise ProviderProtocolError(
                    f"Git-trackable content exposes private site field {field}"
                )
        for field in token_fields:
            token = str(site[field]).encode("utf-8")
            if (
                path.is_file()
                and not path.is_symlink()
                and _contains_bounded_token(path, token)
            ):
                raise ProviderProtocolError(
                    f"Git-trackable content exposes private site field {field}"
                )


def assert_repository_site_anonymous(
    repository: str | Path,
    *,
    site: Mapping[str, str],
    pathspecs: Iterable[str] = (),
    reject_partition: bool = False,
) -> None:
    """Fail if the worktree candidate set or Git index exposes site identity."""

    repository_path = Path(repository).resolve(strict=True)
    assert_no_private_site_identity(
        git_trackable_paths(repository_path, pathspecs=pathspecs),
        site=site,
        reject_partition=reject_partition,
    )
    # Reading worktree paths alone is insufficient: a staged blob can contain
    # a selector after the worktree copy has been sanitized.  Inspect the Git
    # index bytes as a second, independent gate.  Values are supplied over
    # stdin so they never appear in the process argument list.
    for field in ("node_name", "cluster_name", "site_nonce"):
        literal = str(site[field]).encode("utf-8")
        if _git_index_contains_literal(repository_path, literal):
            raise ProviderProtocolError(
                f"Git index exposes private site field {field}"
            )


def public_site_identity(site: Mapping[str, Any], *, digest: str) -> dict[str, str]:
    """Return the only site identity representation allowed in tracked output."""

    del site
    return {
        "identity_disclosure": "salted-digest-only",
        "site_identity_digest": digest,
    }


__all__ = [
    "PRIVATE_SITE_FIELDS",
    "PRIVATE_SITE_SCHEMA",
    "assert_no_private_site_identity",
    "assert_repository_site_anonymous",
    "git_trackable_paths",
    "load_private_site_config",
    "public_site_identity",
]
