from pathlib import Path
from typing import BinaryIO

from app.storage.base import StorageBackend


class LocalStorage(StorageBackend):
    """Stores objects under a root directory. Keys are validated so they cannot escape the root."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        candidate = (self._root / key).resolve()
        if not candidate.is_relative_to(self._root):
            raise ValueError("storage key escapes the storage root")
        return candidate

    def save(self, key: str, data: bytes) -> None:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def open(self, key: str) -> BinaryIO:
        return self._path_for(key).open("rb")

    def delete(self, key: str) -> None:
        path = self._path_for(key)
        if path.exists():
            path.unlink()
