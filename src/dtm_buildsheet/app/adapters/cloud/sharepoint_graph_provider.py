from __future__ import annotations

import logging
from typing import Callable
from urllib.parse import quote

import requests

from ....storage.base import FileMetadata, StorageProvider
from .config import GRAPH_ENDPOINT, CloudConfig

logger = logging.getLogger(__name__)


# 4 MB — Graph's documented threshold above which an upload session is
# required. Settings files are far below this; PPTX/installer uploads will
# need a chunked path added in a later phase.
SMALL_UPLOAD_LIMIT_BYTES = 4 * 1024 * 1024


TokenProvider = Callable[[], str]


class SharePointRequestError(RuntimeError):
    """A safe summary of a failed Microsoft Graph request.

    Graph may redirect downloads to a time-limited URL that contains an
    authorization query string.  ``requests.HTTPError`` includes that final
    URL in its text, so callers must receive this deliberately plain error
    instead of the original exception.
    """


class SharePointGraphProvider(StorageProvider):
    """`StorageProvider` backed by Microsoft Graph drive items.

    Paths are drive-relative (e.g. ``"Settings/parts_db.json"``). A leading
    slash is tolerated and stripped. The provider performs one HTTP round-trip
    per call; callers that need caching should layer it on top — keeping the
    adapter dumb makes it easy to test and easy to swap.
    """

    def __init__(
        self,
        config: CloudConfig,
        token_provider: TokenProvider,
        *,
        http_timeout: float = 30.0,
        session: requests.Session | None = None,
    ) -> None:
        self._config = config
        self._token_provider = token_provider
        self._http_timeout = http_timeout
        self._session = session or requests.Session()

    # ── StorageProvider interface ─────────────────────────────────────────

    def read_text(self, path: str) -> str:
        return self.read_bytes(path).decode("utf-8")

    def write_text(self, path: str, data: str) -> None:
        self.write_bytes(path, data.encode("utf-8"))

    def read_bytes(self, path: str) -> bytes:
        url = self._item_content_url(path)
        response = self._request(
            "read",
            path,
            lambda: self._session.get(
                url,
                headers=self._auth_headers(),
                timeout=self._http_timeout,
                allow_redirects=True,
            ),
        )
        if response.status_code == 404:
            raise FileNotFoundError(path)
        self._raise_for_status(response, operation="read", path=path)
        return response.content

    def write_bytes(self, path: str, data: bytes) -> None:
        if len(data) > SMALL_UPLOAD_LIMIT_BYTES:
            raise NotImplementedError(
                f"SharePoint upload >{SMALL_UPLOAD_LIMIT_BYTES} bytes requires an "
                "upload session — not implemented yet"
        )
        url = self._item_content_url(path)
        response = self._request(
            "write",
            path,
            lambda: self._session.put(
                url,
                headers={
                    **self._auth_headers(),
                    "Content-Type": "application/octet-stream",
                },
                data=data,
                timeout=self._http_timeout,
            ),
        )
        self._raise_for_status(response, operation="write", path=path)

    def delete(self, path: str) -> None:
        url = self._item_url(path)
        response = self._request(
            "delete",
            path,
            lambda: self._session.delete(
                url,
                headers=self._auth_headers(),
                timeout=self._http_timeout,
            ),
        )
        if response.status_code == 404:
            raise FileNotFoundError(path)
        self._raise_for_status(response, operation="delete", path=path)

    def list_files(self, directory: str) -> list[str]:
        """Return drive-relative paths of files directly under *directory*."""
        return [m.path for m in self.list_files_with_metadata(directory)]

    def list_files_with_metadata(self, directory: str) -> list[FileMetadata]:
        """List files with Graph's ETag attached.

        The children endpoint returns ``eTag`` per item in the same response
        as the path; surfacing it lets sync_work_data skip the per-file
        content fetch when the cloud copy hasn't changed since we last
        recorded it. Pagination via ``@odata.nextLink`` is followed so
        callers see the full listing of folders larger than Graph's
        default page size.
        """
        base = self._normalize(directory)
        url = self._children_url(base)
        results: list[FileMetadata] = []
        while url:
            response = self._request(
                "list",
                directory,
                lambda: self._session.get(
                    url,
                    headers=self._auth_headers(),
                    timeout=self._http_timeout,
                ),
            )
            if response.status_code == 404:
                raise FileNotFoundError(directory)
            self._raise_for_status(response, operation="list", path=directory)
            payload = response.json()
            for item in payload.get("value", []):
                if "folder" in item:
                    continue
                name = item.get("name")
                if not name:
                    continue
                path = f"{base}/{name}" if base else name
                # Graph returns eTag as either ``eTag`` (top-level) or
                # cTag. Prefer eTag — it changes on content updates;
                # cTag also changes for metadata-only updates which would
                # produce false-positive "changed" results.
                etag = str(item.get("eTag") or item.get("cTag") or "")
                results.append(FileMetadata(path=path, etag=etag))
            url = payload.get("@odata.nextLink")
        return results

    # ── Internal URL builders ─────────────────────────────────────────────

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token_provider()}"}

    def _request(self, operation: str, path: str, send):
        """Send one request without exposing request/redirect URLs on error."""
        try:
            return send()
        except requests.RequestException as exc:
            raise SharePointRequestError(
                f"SharePoint {operation} request failed for {self._normalize(path)} "
                f"({type(exc).__name__})"
            ) from None

    def _raise_for_status(self, response, *, operation: str, path: str) -> None:
        try:
            response.raise_for_status()
        except requests.RequestException:
            status = getattr(response, "status_code", None)
            status_text = f"HTTP {status}" if status else "HTTP request failed"
            raise SharePointRequestError(
                f"SharePoint {operation} failed for {self._normalize(path)} ({status_text})"
            ) from None

    def _drive_root(self) -> str:
        return (
            f"{GRAPH_ENDPOINT}/sites/{self._config.sharepoint_site_id}"
            f"/drives/{self._config.sharepoint_drive_id}/root"
        )

    def _item_url(self, path: str) -> str:
        path = self._normalize(path)
        if not path:
            return self._drive_root()
        return f"{self._drive_root()}:/{quote(path, safe='/')}"

    def _item_content_url(self, path: str) -> str:
        path = self._normalize(path)
        if not path:
            raise ValueError("empty path")
        return f"{self._drive_root()}:/{quote(path, safe='/')}:/content"

    def _children_url(self, path: str) -> str:
        path = self._normalize(path)
        if not path:
            return f"{self._drive_root()}/children"
        return f"{self._drive_root()}:/{quote(path, safe='/')}:/children"

    @staticmethod
    def _normalize(path: str) -> str:
        return path.strip().lstrip("/")
