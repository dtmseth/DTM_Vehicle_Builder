from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class FileMetadata:
    """Lightweight summary of a remote file, returned by listing operations.

    ``etag`` is whatever opaque token the underlying store uses to mark
    file revisions — Graph's ETag header, SharePoint's @odata.etag, a
    "size:mtime" tuple synthesized by the local-filesystem adapter, etc.
    Equal etags mean the content is provably unchanged; unequal etags
    mean it MIGHT be (or might just be a metadata-only update). Callers
    use this to short-circuit content fetches on the unchanged-and-cached
    fast path.
    """

    path: str
    etag: str = ""


class StorageProvider(ABC):
    @abstractmethod
    def read_text(self, path: str) -> str: ...

    @abstractmethod
    def write_text(self, path: str, data: str) -> None: ...

    @abstractmethod
    def read_bytes(self, path: str) -> bytes: ...

    @abstractmethod
    def write_bytes(self, path: str, data: bytes) -> None: ...

    @abstractmethod
    def delete(self, path: str) -> None: ...

    @abstractmethod
    def list_files(self, directory: str) -> list[str]: ...

    def list_files_with_metadata(self, directory: str) -> list[FileMetadata]:
        """Like list_files, but also surfaces etags when the adapter has them.

        Default implementation has no metadata — every entry's etag is
        empty. SharePoint overrides this to return Graph's ETag header
        per file in a single round trip; sync_work_data uses that to
        skip content fetches when the cloud copy is provably unchanged.
        Adapters with no native etag concept (local filesystem in tests,
        for example) can leave the default and the slow-path
        content-equality check still works.
        """
        return [FileMetadata(path=p) for p in self.list_files(directory)]
