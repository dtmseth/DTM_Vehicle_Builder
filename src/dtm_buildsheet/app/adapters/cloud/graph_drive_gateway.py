"""Narrow Microsoft Graph drive-item adapter for vehicle/reference services."""
from __future__ import annotations

import time
from urllib.parse import quote

import requests


_GRAPH = "https://graph.microsoft.com/v1.0"
_SMALL_UPLOAD_LIMIT = 4 * 1024 * 1024
_UPLOAD_CHUNK_SIZE = 10 * 1024 * 1024


class GraphDriveError(RuntimeError):
    """Safe Graph failure that never includes token-bearing redirect URLs."""


class GraphDriveGateway:
    """Folder/item operations against one resolved SharePoint drive."""

    def __init__(self, *, token: str, drive_id: str, session=None):
        self._token = token
        self._drive_id = drive_id
        self._headers = {"Authorization": f"Bearer {token}"}
        self._session = session or requests.Session()

    @property
    def drive_id(self) -> str:
        return self._drive_id

    @classmethod
    def from_active_cloud(
        cls,
        config,
        *,
        library_names: tuple[str, ...],
        timeout_seconds: float = 30,
    ):
        # Deferred adapter-to-wiring lookup avoids constructing cloud state at
        # import time while preserving the app's single active identity.
        from .. import wiring

        bundle = wiring.get_active_bundle()
        token_provider = getattr(bundle.storage, "_token_provider", None)
        if token_provider is None:
            raise GraphDriveError("SharePoint authentication is unavailable")
        token = token_provider()
        drive_id = cls.resolve_drive_id(
            token=token,
            site_id=config.sharepoint_site_id,
            library_names=library_names,
            timeout_seconds=timeout_seconds,
        )
        if not drive_id:
            raise GraphDriveError("The configured SharePoint library was not found")
        return cls(token=token, drive_id=drive_id)

    @classmethod
    def web_url_from_active_cloud(cls, config, *, library_names: tuple[str, ...]) -> str:
        """Return the configured drive's browser URL using the active identity."""
        from .. import wiring

        bundle = wiring.get_active_bundle()
        token_provider = getattr(bundle.storage, "_token_provider", None)
        if token_provider is None:
            raise GraphDriveError("SharePoint authentication is unavailable")
        return cls.resolve_drive_web_url(
            token=token_provider(),
            site_id=config.sharepoint_site_id,
            library_names=library_names,
        )

    @classmethod
    def resolve_drive_id(
        cls,
        *,
        token: str,
        site_id: str,
        library_names: tuple[str, ...],
        session=None,
        timeout_seconds: float = 30,
    ) -> str:
        client = session or requests.Session()
        try:
            response = client.get(
                f"{_GRAPH}/sites/{quote(site_id, safe='')}/drives",
                headers={"Authorization": f"Bearer {token}"},
                timeout=max(1.0, min(float(timeout_seconds), 120.0)),
            )
            cls._raise_for_status(response, operation="library lookup")
            drives = response.json().get("value", [])
        except GraphDriveError:
            raise
        except Exception as exc:
            raise GraphDriveError(
                f"Graph library lookup failed ({type(exc).__name__})"
            ) from None
        candidates = {
            str(name or "").strip().casefold() for name in library_names
        } - {""}
        return next((
            str(item.get("id") or "")
            for item in drives
            if str(item.get("name") or "").strip().casefold() in candidates
        ), "")

    @classmethod
    def resolve_drive_web_url(
        cls,
        *,
        token: str,
        site_id: str,
        library_names: tuple[str, ...],
        session=None,
    ) -> str:
        client = session or requests.Session()
        try:
            response = client.get(
                f"{_GRAPH}/sites/{quote(site_id, safe='')}/drives",
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
            cls._raise_for_status(response, operation="library lookup")
            drives = response.json().get("value", [])
        except GraphDriveError:
            raise
        except Exception as exc:
            raise GraphDriveError(
                f"Graph library lookup failed ({type(exc).__name__})"
            ) from None
        candidates = {
            str(name or "").strip().casefold() for name in library_names
        } - {""}
        return next((
            str(item.get("webUrl") or "")
            for item in drives
            if str(item.get("name") or "").strip().casefold() in candidates
        ), "")

    def _path_url(self, remote_path: str) -> str:
        encoded = quote(remote_path.strip("/"), safe="/")
        return f"{_GRAPH}/drives/{quote(self._drive_id, safe='')}/root:/{encoded}"

    @staticmethod
    def _raise_for_status(response, *, operation: str) -> None:
        try:
            response.raise_for_status()
        except requests.RequestException:
            status = getattr(response, "status_code", None)
            detail = f"HTTP {status}" if status else "request failed"
            raise GraphDriveError(f"Graph {operation} failed ({detail})") from None

    def _get_path(self, remote_path: str, *, timeout_seconds: float = 30) -> dict | None:
        try:
            response = self._session.get(
                self._path_url(remote_path), headers=self._headers,
                timeout=max(1.0, min(float(timeout_seconds), 120.0)),
            )
        except requests.RequestException as exc:
            raise GraphDriveError(
                f"Graph folder lookup failed ({type(exc).__name__})"
            ) from None
        if response.status_code == 404:
            return None
        self._raise_for_status(response, operation="folder lookup")
        return dict(response.json())

    def get_item_by_path(
        self,
        remote_path: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict | None:
        """Return the exact drive item at *remote_path*, or ``None``."""
        return self._get_path(remote_path, timeout_seconds=timeout_seconds)

    def get_item(self, item_id: str) -> dict | None:
        """Return a drive item by its durable Graph ID, or ``None``.

        Item IDs survive user-driven folder renames and moves.  Folder
        reconciliation uses this lookup to recover the item's current path
        instead of trusting a stale path saved before the move.
        """
        try:
            response = self._session.get(
                f"{_GRAPH}/drives/{quote(self._drive_id, safe='')}/items/"
                f"{quote(str(item_id or ''), safe='')}",
                headers=self._headers,
                timeout=30,
            )
        except requests.RequestException as exc:
            raise GraphDriveError(
                f"Graph item lookup failed ({type(exc).__name__})"
            ) from None
        if response.status_code == 404:
            return None
        self._raise_for_status(response, operation="item lookup")
        return dict(response.json())

    def ensure_folder(self, remote_path: str, *, timeout_seconds: float = 30) -> dict:
        current_path = ""
        item: dict = {}
        for segment in [part for part in remote_path.strip("/").split("/") if part]:
            parent_path = current_path
            current_path = "/".join(part for part in (current_path, segment) if part)
            existing = self._get_path(current_path, timeout_seconds=timeout_seconds)
            if existing is not None:
                if not isinstance(existing.get("folder"), dict):
                    raise GraphDriveError("A file blocks the configured SharePoint folder path")
                item = existing
                continue
            children_url = (
                f"{self._path_url(parent_path)}:/children"
                if parent_path
                else f"{_GRAPH}/drives/{quote(self._drive_id, safe='')}/root/children"
            )
            try:
                response = self._session.post(
                    children_url,
                    headers={**self._headers, "Content-Type": "application/json"},
                    json={
                        "name": segment,
                        "folder": {},
                        "@microsoft.graph.conflictBehavior": "fail",
                    },
                    timeout=max(1.0, min(float(timeout_seconds), 120.0)),
                )
            except requests.RequestException as exc:
                raise GraphDriveError(
                    f"Graph folder creation failed ({type(exc).__name__})"
                ) from None
            if response.status_code == 409:
                existing = self._get_path(current_path, timeout_seconds=timeout_seconds)
                if existing is None:
                    self._raise_for_status(response, operation="folder creation")
                item = existing
            else:
                self._raise_for_status(response, operation="folder creation")
                item = dict(response.json())
        return item

    def upload_file(
        self,
        remote_path: str,
        data: bytes,
        *,
        timeout_seconds: float = 120,
    ) -> dict:
        if len(data) <= _SMALL_UPLOAD_LIMIT:
            try:
                response = self._session.put(
                    f"{self._path_url(remote_path)}:/content",
                    headers={**self._headers, "Content-Type": "application/octet-stream"},
                    data=data,
                    timeout=max(1.0, min(float(timeout_seconds), 300.0)),
                )
            except requests.RequestException as exc:
                raise GraphDriveError(
                    f"Graph file upload failed ({type(exc).__name__})"
                ) from None
            self._raise_for_status(response, operation="file upload")
            return dict(response.json())
        self._upload_large_file(remote_path, data)
        item = self._get_path(remote_path)
        if item is None:
            raise GraphDriveError("Uploaded SharePoint file could not be verified")
        return item

    def _upload_large_file(self, remote_path: str, data: bytes) -> None:
        create_url = f"{self._path_url(remote_path)}:/createUploadSession"
        try:
            response = self._session.post(
                create_url,
                headers={**self._headers, "Content-Type": "application/json"},
                json={"item": {"@microsoft.graph.conflictBehavior": "replace"}},
                timeout=30,
            )
            self._raise_for_status(response, operation="upload-session creation")
            upload_url = str(response.json().get("uploadUrl") or "")
            if not upload_url:
                raise GraphDriveError("Graph upload session did not return an upload URL")
            total = len(data)
            for offset in range(0, total, _UPLOAD_CHUNK_SIZE):
                chunk = data[offset:offset + _UPLOAD_CHUNK_SIZE]
                last = offset + len(chunk) - 1
                chunk_response = self._session.put(
                    upload_url,
                    headers={
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {offset}-{last}/{total}",
                    },
                    data=chunk,
                    timeout=120,
                )
                if chunk_response.status_code not in {200, 201, 202}:
                    raise GraphDriveError(
                        f"Graph upload chunk failed (HTTP {chunk_response.status_code})"
                    )
        except GraphDriveError:
            raise
        except requests.RequestException as exc:
            raise GraphDriveError(
                f"Graph upload session failed ({type(exc).__name__})"
            ) from None

    def move_item(self, item_id: str, *, parent_id: str, new_name: str) -> dict:
        safe_item_id = quote(str(item_id or "").strip(), safe="")
        if not safe_item_id or not str(parent_id or "").strip():
            raise GraphDriveError("Saved vehicle folder identity is incomplete")
        try:
            response = self._session.patch(
                f"{_GRAPH}/drives/{quote(self._drive_id, safe='')}/items/{safe_item_id}",
                headers={**self._headers, "Content-Type": "application/json"},
                json={
                    "name": new_name,
                    "parentReference": {"id": str(parent_id).strip()},
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            raise GraphDriveError(
                f"Graph item move failed ({type(exc).__name__})"
            ) from None
        self._raise_for_status(response, operation="item move")
        return dict(response.json())

    def copy_item(
        self,
        item_id: str,
        *,
        parent_id: str,
        new_name: str,
        destination_path: str,
        timeout_seconds: float = 600,
    ) -> dict:
        """Copy one item in this drive and wait for its exact destination.

        Microsoft Graph performs folder copies asynchronously.  The monitor
        response is treated only as progress; the destination path must also
        resolve before the operation is considered complete.  This keeps the
        legacy-photo migration from persisting a destination that Graph has
        accepted but not actually materialized yet.
        """
        safe_item_id = quote(str(item_id or "").strip(), safe="")
        destination_parent = str(parent_id or "").strip()
        safe_name = str(new_name or "").strip()
        if not safe_item_id or not destination_parent or not safe_name:
            raise GraphDriveError("SharePoint copy identity is incomplete")
        try:
            response = self._session.post(
                f"{_GRAPH}/drives/{quote(self._drive_id, safe='')}/items/{safe_item_id}/copy",
                headers={**self._headers, "Content-Type": "application/json"},
                json={
                    "parentReference": {
                        "driveId": self._drive_id,
                        "id": destination_parent,
                    },
                    "name": safe_name,
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            raise GraphDriveError(
                f"Graph item copy failed ({type(exc).__name__})"
            ) from None
        if response.status_code not in {200, 201, 202}:
            self._raise_for_status(response, operation="item copy")

        deadline = time.monotonic() + max(1.0, float(timeout_seconds))
        monitor_url = str(response.headers.get("Location") or "").strip()
        while monitor_url and time.monotonic() < deadline:
            try:
                monitor = self._session.get(
                    # The Location value is a pre-authorized monitor URL.
                    # Microsoft rejects a second bearer credential here.
                    monitor_url, timeout=30,
                )
            except requests.RequestException as exc:
                raise GraphDriveError(
                    f"Graph item copy monitor failed ({type(exc).__name__})"
                ) from None
            if monitor.status_code >= 400:
                self._raise_for_status(monitor, operation="item copy monitor")
            payload = monitor.json() if monitor.content else {}
            status = str(payload.get("status") or "").casefold()
            if status in {"failed", "deletefailed"}:
                raise GraphDriveError("Graph item copy did not complete")
            if monitor.status_code != 202 and status not in {"inprogress", "notstarted"}:
                break
            retry_after = str(monitor.headers.get("Retry-After") or "1").strip()
            try:
                delay = min(5.0, max(0.25, float(retry_after)))
            except ValueError:
                delay = 1.0
            time.sleep(delay)

        while time.monotonic() < deadline:
            copied = self._get_path(destination_path)
            if copied is not None:
                return copied
            time.sleep(0.5)
        raise GraphDriveError("Graph item copy timed out before the destination appeared")

    def delete_item(self, item_id: str) -> None:
        safe_id = quote(str(item_id or "").strip(), safe="")
        if not safe_id:
            return
        try:
            response = self._session.delete(
                f"{_GRAPH}/drives/{quote(self._drive_id, safe='')}/items/{safe_id}",
                headers=self._headers,
                timeout=30,
            )
        except requests.RequestException as exc:
            raise GraphDriveError(
                f"Graph item deletion failed ({type(exc).__name__})"
            ) from None
        if response.status_code not in {204, 404}:
            self._raise_for_status(response, operation="item deletion")

    def list_children(
        self,
        remote_path: str,
        *,
        timeout_seconds: float = 30,
    ) -> list[dict]:
        encoded_path = quote(remote_path.strip("/"), safe="/")
        url = (
            f"{_GRAPH}/drives/{quote(self._drive_id, safe='')}/root:/{encoded_path}:/children"
            if encoded_path
            else f"{_GRAPH}/drives/{quote(self._drive_id, safe='')}/root/children"
        )
        items: list[dict] = []
        while url:
            try:
                response = self._session.get(
                    url,
                    headers=self._headers,
                    timeout=max(1.0, min(float(timeout_seconds), 120.0)),
                )
            except requests.RequestException as exc:
                raise GraphDriveError(
                    f"Graph folder listing failed ({type(exc).__name__})"
                ) from None
            if response.status_code == 404:
                raise FileNotFoundError(remote_path)
            self._raise_for_status(response, operation="folder listing")
            payload = response.json()
            items.extend(item for item in payload.get("value", []) if isinstance(item, dict))
            url = str(payload.get("@odata.nextLink") or "")
        return items

    def download_item(self, item_id: str, *, timeout_seconds: float = 120) -> bytes:
        safe_item_id = quote(str(item_id or "").strip(), safe="")
        if not safe_item_id:
            raise FileNotFoundError(item_id)
        try:
            response = self._session.get(
                f"{_GRAPH}/drives/{quote(self._drive_id, safe='')}/items/{safe_item_id}/content",
                headers=self._headers,
                timeout=max(1.0, min(float(timeout_seconds), 300.0)),
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            raise GraphDriveError(
                f"Graph item download failed ({type(exc).__name__})"
            ) from None
        if response.status_code == 404:
            raise FileNotFoundError(item_id)
        self._raise_for_status(response, operation="item download")
        return bytes(response.content)

    def download_thumbnail(
        self,
        item_id: str,
        *,
        size: str = "large",
        timeout_seconds: float = 60,
    ) -> bytes:
        """Download Microsoft's generated thumbnail for one drive item.

        The Graph endpoint redirects to a short-lived CDN URL.  Redirect URLs
        are never returned or logged; callers receive only the thumbnail bytes.
        """
        safe_item_id = quote(str(item_id or "").strip(), safe="")
        safe_size = size if size in {"small", "medium", "large"} else "large"
        if not safe_item_id:
            raise FileNotFoundError(item_id)
        try:
            response = self._session.get(
                f"{_GRAPH}/drives/{quote(self._drive_id, safe='')}/items/"
                f"{safe_item_id}/thumbnails/0/{safe_size}/content",
                headers=self._headers,
                timeout=max(1.0, min(float(timeout_seconds), 120.0)),
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            raise GraphDriveError(
                f"Graph thumbnail download failed ({type(exc).__name__})"
            ) from None
        if response.status_code == 404:
            raise FileNotFoundError(item_id)
        self._raise_for_status(response, operation="thumbnail download")
        return bytes(response.content)
