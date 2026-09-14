"""Read exact Git trees as inert bytes for external Knowledge import."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from ari.knowledge.importer import KnowledgeImportError
from ari.protocols.integrity import (
    FULL_GIT_COMMIT_PATTERN,
    bytes_digest,
    canonical_digest,
)


class KnowledgeGitSourceError(KnowledgeImportError):
    pass


@dataclass(frozen=True)
class GitSnapshotFile:
    relative_path: str
    mode: str
    git_object_id: str
    sha256: str
    payload: bytes


@dataclass(frozen=True)
class GitKnowledgeSnapshot:
    repository: str
    commit: str
    subpath: str
    files: tuple[GitSnapshotFile, ...]
    snapshot_digest: str

    def file_map(self) -> dict[str, GitSnapshotFile]:
        return {item.relative_path: item for item in self.files}


def _safe_subpath(value: str) -> str:
    raw = value.strip()
    path = PurePosixPath(raw)
    if path.is_absolute():
        raise KnowledgeGitSourceError("Git subpath must be safe and POSIX-relative")
    text = raw.rstrip("/")
    path = PurePosixPath(text)
    if (
        not text
        or "\\" in text
        or path.is_absolute()
        or ".." in path.parts
        or any(ord(character) < 32 for character in text)
    ):
        raise KnowledgeGitSourceError("Git subpath must be safe and POSIX-relative")
    return path.as_posix()


def _repository_argument(repository: str) -> tuple[str, bool]:
    value = repository.strip()
    if (
        not value
        or value.startswith("-")
        or any(ord(character) < 32 for character in value)
    ):
        raise KnowledgeGitSourceError("unsafe Git repository identity")
    parsed = urlsplit(value)
    if parsed.scheme:
        if parsed.scheme not in {"https", "ssh", "file"}:
            raise KnowledgeGitSourceError("Git repository scheme is not admitted")
        if parsed.password is not None or (parsed.scheme == "https" and parsed.username):
            raise KnowledgeGitSourceError("credentials must not be embedded in repository URLs")
        return value, parsed.scheme == "file"
    if re.fullmatch(r"(?:[A-Za-z0-9._-]+@)?[A-Za-z0-9._-]+:.+", value):
        return value, False
    local = Path(value).resolve(strict=True)
    if not local.is_dir():
        raise KnowledgeGitSourceError("local Git repository must be a directory")
    return str(local), True


class PinnedGitRepository:
    """A temporary bare fetch that resolves only one caller-supplied commit."""

    def __init__(
        self,
        *,
        repository: str,
        commit: str,
        timeout_seconds: float = 120.0,
        max_files: int = 4096,
        max_blob_bytes: int = 32 * 1024 * 1024,
        max_total_bytes: int = 256 * 1024 * 1024,
    ) -> None:
        if re.fullmatch(FULL_GIT_COMMIT_PATTERN, commit) is None:
            raise KnowledgeGitSourceError("external Git source requires a full commit SHA")
        if timeout_seconds <= 0 or max_files <= 0 or max_blob_bytes <= 0 or max_total_bytes <= 0:
            raise KnowledgeGitSourceError("Git import limits must be positive")
        self.commit = commit
        self.timeout_seconds = timeout_seconds
        self.max_files = max_files
        self.max_blob_bytes = max_blob_bytes
        self.max_total_bytes = max_total_bytes
        self._fetch_argument, self._local = _repository_argument(repository)
        self.repository = self._fetch_argument if self._local else repository.strip()
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self._bare: Path | None = None
        self._git = shutil.which("git")
        if self._git is None:
            raise KnowledgeGitSourceError("git executable is unavailable")

    def __enter__(self) -> "PinnedGitRepository":
        self._temporary = tempfile.TemporaryDirectory(prefix="ari-knowledge-git-")
        self._bare = Path(self._temporary.name) / "source.git"
        try:
            init = [self._git, "init", "--quiet", "--bare"]
            if len(self.commit) == 64:
                init.append("--object-format=sha256")
            init.append(str(self._bare))
            self._run(init, operation="init")
            file_policy = "always" if self._local else "never"
            self._run(
                [
                    self._git,
                    "-C",
                    str(self._bare),
                    "-c",
                    "protocol.ext.allow=never",
                    "-c",
                    f"protocol.file.allow={file_policy}",
                    "fetch",
                    "--quiet",
                    "--no-tags",
                    "--depth=1",
                    self._fetch_argument,
                    self.commit,
                ],
                operation="fetch exact commit",
            )
            resolved = self._text(
                [
                    self._git,
                    "-C",
                    str(self._bare),
                    "rev-parse",
                    "--verify",
                    "FETCH_HEAD^{commit}",
                ],
                operation="resolve fetched commit",
            ).strip()
            if resolved != self.commit:
                raise KnowledgeGitSourceError(
                    "fetched Git object differs from the pinned commit"
                )
        except Exception:
            self._temporary.cleanup()
            self._temporary = None
            self._bare = None
            raise
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._temporary is not None:
            self._temporary.cleanup()
        self._temporary = None
        self._bare = None

    def _environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        for key in (
            "GIT_ALTERNATE_OBJECT_DIRECTORIES",
            "GIT_ASKPASS",
            "GIT_CONFIG_COUNT",
            "GIT_CONFIG_PARAMETERS",
            "GIT_DIR",
            "GIT_INDEX_FILE",
            "GIT_OBJECT_DIRECTORY",
            "GIT_PROXY_COMMAND",
            "GIT_SSH",
            "GIT_SSH_COMMAND",
            "GIT_WORK_TREE",
            "SSH_ASKPASS",
        ):
            environment.pop(key, None)
        environment.update(
            {
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_LFS_SKIP_SMUDGE": "1",
                "GIT_OPTIONAL_LOCKS": "0",
            }
        )
        return environment

    def _run(self, argv: list[str], *, operation: str) -> bytes:
        try:
            completed = subprocess.run(
                argv,
                check=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
                env=self._environment(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise KnowledgeGitSourceError(f"Git {operation} failed") from exc
        return completed.stdout

    def _text(self, argv: list[str], *, operation: str) -> str:
        try:
            return self._run(argv, operation=operation).decode("ascii", errors="strict")
        except UnicodeDecodeError as exc:
            raise KnowledgeGitSourceError(f"Git {operation} returned non-ASCII identity") from exc

    def snapshot(self, subpath: str) -> GitKnowledgeSnapshot:
        if self._bare is None:
            raise KnowledgeGitSourceError("Git source is not open")
        normalized = _safe_subpath(subpath)
        tree_command = [
            self._git,
            "-C",
            str(self._bare),
            "ls-tree",
            "-r",
            "-z",
            "--full-tree",
            self.commit,
        ]
        if normalized != ".":
            tree_command.extend(("--", normalized))
        listing = self._run(tree_command, operation="enumerate pinned tree")
        records = [item for item in listing.split(b"\0") if item]
        if not records:
            raise KnowledgeGitSourceError("pinned Git subpath is empty or missing")
        if len(records) > self.max_files:
            raise KnowledgeGitSourceError("pinned Git subpath exceeds the file-count limit")
        prefix = "" if normalized == "." else normalized + "/"
        files: list[GitSnapshotFile] = []
        total = 0
        for record in records:
            metadata, separator, raw_path = record.partition(b"\t")
            if not separator:
                raise KnowledgeGitSourceError("malformed Git tree record")
            try:
                mode, object_type, object_id = metadata.decode("ascii").split(" ")
                full_path = raw_path.decode("utf-8", errors="strict")
            except (UnicodeDecodeError, ValueError) as exc:
                raise KnowledgeGitSourceError("Git tree contains an invalid path or identity") from exc
            if prefix and not full_path.startswith(prefix):
                raise KnowledgeGitSourceError("Git tree record escaped the requested subpath")
            relative = _safe_subpath(full_path[len(prefix) :])
            if object_type != "blob" or mode not in {"100644", "100755"}:
                raise KnowledgeGitSourceError(
                    f"Git Knowledge source contains a symlink, submodule, or special entry: {relative}"
                )
            size_text = self._text(
                [
                    self._git,
                    "-C",
                    str(self._bare),
                    "cat-file",
                    "-s",
                    object_id,
                ],
                operation="read pinned blob size",
            ).strip()
            try:
                size = int(size_text)
            except ValueError as exc:
                raise KnowledgeGitSourceError("Git blob size is invalid") from exc
            if size < 0 or size > self.max_blob_bytes:
                raise KnowledgeGitSourceError(f"Git blob exceeds the import limit: {relative}")
            total += size
            if total > self.max_total_bytes:
                raise KnowledgeGitSourceError("pinned Git subpath exceeds the total-size limit")
            payload = self._run(
                [
                    self._git,
                    "-C",
                    str(self._bare),
                    "cat-file",
                    "blob",
                    object_id,
                ],
                operation="read pinned blob",
            )
            if len(payload) != size:
                raise KnowledgeGitSourceError("Git blob size changed while importing")
            files.append(
                GitSnapshotFile(
                    relative_path=relative,
                    mode=mode,
                    git_object_id=object_id,
                    sha256=bytes_digest(payload),
                    payload=payload,
                )
            )
        files.sort(key=lambda item: item.relative_path)
        if len({item.relative_path for item in files}) != len(files):
            raise KnowledgeGitSourceError("Git tree contains duplicate normalized paths")
        snapshot_digest = canonical_digest(
            {
                "repository": self.repository,
                "commit": self.commit,
                "subpath": normalized,
                "files": [
                    {
                        "path": item.relative_path,
                        "mode": item.mode,
                        "git_object_id": item.git_object_id,
                        "sha256": item.sha256,
                        "size": len(item.payload),
                    }
                    for item in files
                ],
            }
        )
        return GitKnowledgeSnapshot(
            repository=self.repository,
            commit=self.commit,
            subpath=normalized,
            files=tuple(files),
            snapshot_digest=snapshot_digest,
        )


def fetch_git_knowledge_snapshot(
    *, repository: str, commit: str, subpath: str
) -> GitKnowledgeSnapshot:
    with PinnedGitRepository(repository=repository, commit=commit) as source:
        return source.snapshot(subpath)


__all__ = [
    "GitKnowledgeSnapshot",
    "GitSnapshotFile",
    "KnowledgeGitSourceError",
    "PinnedGitRepository",
    "fetch_git_knowledge_snapshot",
]
