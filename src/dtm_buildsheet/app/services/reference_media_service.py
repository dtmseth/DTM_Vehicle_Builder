"""Resolve portable reference assets into a bounded local render cache."""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

from ...domain.project_models import BuildReferenceAsset
from ...paths import AppPaths
from ..adapters import wiring
from ..adapters.cloud.graph_drive_gateway import GraphDriveGateway


logger = logging.getLogger(__name__)
_MAX_REFERENCE_BYTES = 75 * 1024 * 1024
_SAFE_ID = re.compile(r"^[A-Za-z0-9._!~-]+$")


@dataclass(frozen=True)
class ResolvedReferenceMedia:
    path: Path | None
    error: str = ""
    from_cache: bool = False


def _safe_cache_name(value: str) -> str:
    name = Path(str(value or "").replace("\\", "/")).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return cleaned or "reference-photo"


def _cache_paths(asset: BuildReferenceAsset, paths: AppPaths) -> tuple[Path, Path]:
    reference_id = re.sub(r"[^A-Za-z0-9._-]+", "_", asset.reference_id).strip("._")
    if not reference_id:
        reference_id = "reference"
    folder = paths.workspace_reference_cache_dir / reference_id
    media = folder / _safe_cache_name(asset.file_name)
    return media, folder / "source.json"


def _cached_media(asset: BuildReferenceAsset, paths: AppPaths) -> ResolvedReferenceMedia | None:
    media, metadata = _cache_paths(asset, paths)
    if not media.is_file() or media.stat().st_size <= 0:
        return None
    if not asset.source_etag:
        return ResolvedReferenceMedia(media, from_cache=True)
    try:
        saved = json.loads(metadata.read_text(encoding="utf-8"))
    except Exception:
        return None
    if str(saved.get("source_etag") or "") == asset.source_etag:
        return ResolvedReferenceMedia(media, from_cache=True)
    return None


def cached_reference_media(
    asset: BuildReferenceAsset,
    paths: AppPaths,
) -> ResolvedReferenceMedia | None:
    """Return an already-local exact source without starting cloud work."""
    return _cached_media(asset, paths)


def resolve_reference_media(
    asset: BuildReferenceAsset,
    paths: AppPaths,
    *,
    session=None,
    download_timeout_seconds: float = 120,
) -> ResolvedReferenceMedia:
    """Return a local file for one SharePoint item without persisting its path.

    Cached content is usable cloud-off. A cache miss requires the active user's
    existing Microsoft identity; this service never stores a token or source
    absolute path in the project record.
    """
    cached = _cached_media(asset, paths)
    if cached is not None:
        return cached
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("DTM_ALLOW_CLOUD_IN_TESTS"):
        return ResolvedReferenceMedia(None, "Reference photo is not available in the local cache.")
    if not wiring._cloud_flag_enabled():  # noqa: SLF001
        return ResolvedReferenceMedia(None, "Reference photo is not available while cloud mode is off.")
    drive_id = str(asset.source_drive_id or "").strip()
    item_id = str(asset.source_item_id or "").strip()
    if not drive_id or not item_id or not _SAFE_ID.fullmatch(drive_id) or not _SAFE_ID.fullmatch(item_id):
        return ResolvedReferenceMedia(None, "Reference photo has no valid SharePoint item identity.")
    try:
        bundle = wiring.get_active_bundle()
        if not bundle.identity.is_signed_in():
            return ResolvedReferenceMedia(None, "Sign in to Microsoft to load the reference photo.")
        token_provider = getattr(bundle.storage, "_token_provider", None)
        if token_provider is None:
            return ResolvedReferenceMedia(None, "Reference photo storage is unavailable.")
        token = token_provider()
        gateway = GraphDriveGateway(token=token, drive_id=drive_id, session=session)
        data = gateway.download_item(item_id, timeout_seconds=download_timeout_seconds)
    except FileNotFoundError:
        return ResolvedReferenceMedia(None, f"Reference source is missing: {asset.file_name}")
    except Exception as exc:
        logger.warning("Could not resolve reference media %s (%s)", asset.reference_id, type(exc).__name__)
        return ResolvedReferenceMedia(None, f"Could not download reference photo: {asset.file_name}")
    if not data or len(data) > _MAX_REFERENCE_BYTES:
        return ResolvedReferenceMedia(None, f"Reference photo is empty or too large: {asset.file_name}")

    media, metadata = _cache_paths(asset, paths)
    media.parent.mkdir(parents=True, exist_ok=True)
    temporary = media.with_name(media.name + ".download")
    try:
        temporary.write_bytes(data)
        temporary.replace(media)
        metadata.write_text(json.dumps({
            "reference_id": asset.reference_id,
            "source_drive_id": asset.source_drive_id,
            "source_item_id": asset.source_item_id,
            "source_etag": asset.source_etag,
            "source_size": len(data),
        }, indent=2), encoding="utf-8")
    except OSError:
        logger.exception("Could not write reference-media cache")
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return ResolvedReferenceMedia(None, f"Could not cache reference photo: {asset.file_name}")
    return ResolvedReferenceMedia(media)
