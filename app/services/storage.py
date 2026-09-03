"""Blob storage for original document bytes.

Local filesystem for the POC. A real deployment swaps in an S3-backed
implementation of the same ``Storage`` protocol; callers do not change.
"""

from pathlib import Path
from typing import Protocol
from urllib.parse import unquote, urlparse


class Storage(Protocol):
    def save(self, key: str, data: bytes) -> str:
        """Persist ``data`` under ``key``; return a URI that ``read`` accepts."""

    def read(self, uri: str) -> bytes: ...


def _uri_to_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme in ("", "file"):
        return Path(unquote(parsed.path))
    raise ValueError(f"unsupported storage URI: {uri}")


class LocalFileStorage:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def save(self, key: str, data: bytes) -> str:
        path = self._root / key
        path.write_bytes(data)
        return path.resolve().as_uri()

    def read(self, uri: str) -> bytes:
        return _uri_to_path(uri).read_bytes()
