from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .base import StorageProvider


class LocalStorageProvider(StorageProvider):
    def read_text(self, path: str) -> str:
        return Path(path).read_text(encoding="utf-8")

    def write_text(self, path: str, data: str) -> None:
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=dest.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
            os.replace(tmp_name, dest)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def write_bytes(self, path: str, data: bytes) -> None:
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=dest.parent)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp_name, dest)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def delete(self, path: str) -> None:
        Path(path).unlink()

    def list_files(self, directory: str) -> list[str]:
        return [str(p) for p in Path(directory).iterdir() if p.is_file()]
