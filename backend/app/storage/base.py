"""Storage interface. Implementations: LocalStorage (dev), private S3Storage."""

from abc import ABC, abstractmethod
from typing import BinaryIO


class StorageBackend(ABC):
    @abstractmethod
    def save(self, key: str, data: bytes) -> None:
        """Persist bytes under a logical key (e.g. '<lo_id>/v1/package.zip')."""

    @abstractmethod
    def open(self, key: str) -> BinaryIO:
        """Return a readable binary stream for the key. Raises FileNotFoundError if absent."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove the object. Missing keys are not an error."""
