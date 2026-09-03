"""Helpers for the smart Preview/Export buttons in the Builds tab.

Two responsibilities:

- ``get_render_status`` — given an output_path and a last_rendered_at
  timestamp, return whether the file exists locally, whether a PDF
  exists alongside it, and whether the file has been touched in
  PowerPoint since the last render. The UI uses this to decide between
  "open directly", "re-render silently", and "warn about manual edits".

- ``resolve_show_folder`` — figure out where "Open PDF folder" should
  point. Best case: a locally synced OneDrive copy of the SharePoint
  exports library. Fallback: the SharePoint web URL for the agency/year
  subfolder. Either way the UI just receives a path or a URL and opens
  it.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _parse_iso(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def get_render_status(body: dict, paths=None) -> dict:
    """Inspect the on-disk artifacts for a single build.

    Body keys (either form is accepted):
      - output_path + last_rendered_at — direct call; no project lookup
      - project_id + unit_id [+ individual_id] — server resolves
        output_path, last_rendered_at, AND computes is_stale by comparing
        the render timestamp against the project + draft updated_at.

    Returns:
      - ok: True
      - pptx_exists: bool
      - pdf_exists: bool — sibling .pdf with same stem
      - pdf_path: str (if exists)
      - is_stale: bool — source (project or draft) was modified after the
        last render
      - manually_edited: bool — PPTX mtime is meaningfully newer than the
        recorded render time. We compare with a small slack window to
        avoid false positives from FS rounding or post-render mirror
        writes that might bump mtime.
      - mtime_iso: str — current PPTX mtime in ISO format, useful for
        the UI to display "edited <time>".
    """
    output_path = (body.get("output_path") or "").strip()
    last_rendered_str = (body.get("last_rendered_at") or "").strip()
    is_stale = False

    project_id = (body.get("project_id") or "").strip()
    unit_id = (body.get("unit_id") or "").strip()
    individual_id = (body.get("individual_id") or "").strip()
    if project_id and paths is not None:
        try:
            from ...inputs.project_entry import load_project
            from ...inputs.project_drafts import load_draft
            project = load_project(project_id, paths)
            draft_id = ""
            for bu in project.build_units:
                if bu.unit_id != unit_id and unit_id:
                    continue
                if individual_id:
                    for ind in bu.individuals or []:
                        if ind.individual_id == individual_id:
                            output_path = output_path or ind.output_path
                            last_rendered_str = last_rendered_str or ind.last_rendered_at
                            draft_id = ind.draft_id or ""
                            break
                else:
                    output_path = output_path or bu.output_path
                    last_rendered_str = last_rendered_str or bu.last_rendered_at
                    draft_id = bu.draft_id or ""
                break
            # Staleness: project.updated_at OR draft.updated_at > last_rendered_at
            last_rendered_dt = _parse_iso(last_rendered_str)
            proj_dt = _parse_iso(project.updated_at)
            if last_rendered_dt is None:
                # Never rendered or unknown — treat as stale if a draft exists
                is_stale = bool(draft_id)
            else:
                if proj_dt and proj_dt > last_rendered_dt:
                    is_stale = True
                if draft_id and not is_stale:
                    try:
                        draft = load_draft(draft_id, paths.workspace_drafts_dir)
                        draft_dt = _parse_iso(draft.updated_at)
                        if draft_dt and draft_dt > last_rendered_dt:
                            is_stale = True
                    except Exception:
                        pass
        except Exception:
            logger.exception("render-status: could not load project %s", project_id)

    if not output_path:
        return {"ok": True, "pptx_exists": False, "pdf_exists": False,
                "manually_edited": False, "pdf_path": "", "mtime_iso": "",
                "is_stale": is_stale}

    pptx = Path(output_path)
    pptx_exists = pptx.exists() and pptx.is_file()
    if not pptx_exists:
        return {"ok": True, "pptx_exists": False, "pdf_exists": False,
                "manually_edited": False, "pdf_path": "", "mtime_iso": "",
                "is_stale": is_stale}

    pdf = pptx.with_suffix(".pdf")
    pdf_exists = pdf.exists() and pdf.is_file()

    try:
        mtime = datetime.fromtimestamp(pptx.stat().st_mtime, tz=timezone.utc)
    except OSError:
        mtime = None

    last_rendered = _parse_iso(last_rendered_str)
    manually_edited = False
    if mtime is not None and last_rendered is not None:
        # 5 second slack: cloud mirror and SharePoint sync sometimes touch
        # the file shortly after our local write, but not by minutes. A
        # genuine human edit shows up as many minutes later.
        if mtime > last_rendered:
            manually_edited = (mtime - last_rendered).total_seconds() > 5
    elif mtime is not None and last_rendered is None:
        # Old record with no render timestamp — can't tell, assume the
        # file is whatever the user has now. Not flagged as edited so
        # we don't pester.
        manually_edited = False

    return {
        "ok": True,
        "pptx_exists": True,
        "pdf_exists": pdf_exists,
        "pdf_path": str(pdf) if pdf_exists else "",
        "manually_edited": manually_edited,
        "mtime_iso": mtime.isoformat() if mtime else "",
        "is_stale": is_stale,
        "output_path": output_path,
    }


# ── show-folder resolution ──────────────────────────────────────────────────


_OneDrive_ENV_VARS = (
    "OneDriveCommercial",
    "OneDriveBusiness",
    "OneDrive",  # personal — last resort, almost never the right one for a
                 # synced SharePoint library, but on some installs the
                 # commercial tenant gets mounted here too.
)


def _sanitize_segment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 _.\-]+", " ", value).strip(" .")
    return cleaned or "Unassigned"


def _onedrive_candidate_roots() -> list[Path]:
    """Return likely roots where a synced SharePoint library would mount.

    OneDrive Business sets OneDriveCommercial = the user's personal
    OneDrive folder. Synced SharePoint sites sit as siblings of that
    folder — i.e. at the same depth, in ``%USERPROFILE%`` — using the
    ``"<TenantDisplayName> - <SiteOrLibrary>"`` naming convention.

    Returns the parent directory containing those siblings (typically
    %USERPROFILE%) so callers can glob inside it.
    """
    roots: list[Path] = []
    user_profile = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if user_profile:
        roots.append(Path(user_profile))
        # macOS OneDrive client mounts every SharePoint library under
        # ~/Library/CloudStorage. That's where libraries live, so check
        # there before anywhere else.
        if sys.platform == "darwin":
            roots.append(Path(user_profile) / "Library" / "CloudStorage")
    for var in _OneDrive_ENV_VARS:
        path = os.environ.get(var)
        if path:
            roots.append(Path(path).parent)  # walk up to the sibling level
    # De-dup while preserving order
    seen: set[Path] = set()
    out: list[Path] = []
    for r in roots:
        try:
            resolved = r.resolve(strict=False)
        except Exception:
            resolved = r
        if resolved not in seen:
            seen.add(resolved)
            out.append(r)
    return out


def _find_onedrive_synced_folder(
    library_display_name: str,
    library_internal_name: str,
    base_subpath: str,
    exact: bool = False,
) -> Optional[Path]:
    """Look for a locally-synced OneDrive copy of the target SharePoint
    library.

    On macOS the bundled app does NOT have Full Disk Access by default,
    so iterating arbitrary subfolders of ~/Library/CloudStorage triggers
    a permission prompt PER folder. To avoid that we only construct
    direct candidate paths and check existence — no listing of unrelated
    siblings. If none of the candidates exist, we return None and the
    caller falls back to the SharePoint web URL.

    On Windows the same constraint isn't strictly necessary but the
    targeted form keeps behavior consistent.
    """
    targets = [t.strip() for t in (library_display_name, library_internal_name) if t.strip()]
    if not targets:
        return None

    candidates: list[Path] = []
    for root in _onedrive_candidate_roots():
        if not root.exists() or not root.is_dir():
            continue
        for lib in targets:
            # Common OneDrive mount conventions:
            #   macOS: ~/Library/CloudStorage/OneDrive-SharedLibraries-<tenant>/<library>/
            #   macOS: ~/Library/CloudStorage/<tenant> - <library>/
            #   Windows: %USERPROFILE%\<library>\
            #   Windows: %USERPROFILE%\<tenant>\<library>\
            candidates.append(root / lib)
            candidates.append(root / f"OneDrive - {lib}")

    for c in candidates:
        try:
            if not c.exists() or not c.is_dir():
                continue
        except OSError:
            continue
        leaf = c / base_subpath
        try:
            if leaf.exists() and leaf.is_dir():
                return leaf
        except OSError:
            pass
        # Legacy PDF-folder actions may still open the mounted library root.
        # Explicit vehicle/photo-folder actions must fall through to their
        # exact SharePoint web URL rather than opening a misleading root.
        if not exact:
            return c
    return None


def find_synced_library_folder(
    library_display_name: str,
    library_internal_name: str,
    base_subpath: str,
) -> Optional[Path]:
    """Return an exact locally synced library folder when one is available."""
    return _find_onedrive_synced_folder(
        library_display_name,
        library_internal_name,
        base_subpath,
        exact=True,
    )


def _build_sharepoint_web_url(
    site_id: str,
    library_display_name: str,
    base_subpath: str,
) -> Optional[str]:
    """Compose a SharePoint web URL pointing at the agency/year folder.

    Earlier this function tried to assemble a URL from just the hostname
    + library name, but SharePoint URLs always include /sites/<sitename>/
    in the middle so that approach 404s in the browser. Now we ask Graph
    for the drive's webUrl (which already includes the correct site path)
    and append the agency/year subpath onto it.

    Returns None when the cloud bundle is unavailable, no exports library
    is configured, or Graph can't resolve the drive — the caller then
    treats this as "no folder to open" and surfaces the error to the UI.
    """
    if not site_id:
        return None
    from urllib.parse import quote

    drive_web_url = _get_exports_drive_web_url()
    if not drive_web_url:
        return None

    encoded_subpath = "/".join(quote(seg) for seg in base_subpath.split("/") if seg)
    base = drive_web_url.rstrip("/")
    return f"{base}/{encoded_subpath}" if encoded_subpath else base


def _get_exports_drive_web_url() -> Optional[str]:
    """Resolve the SharePoint web URL for the configured exports library.

    Asks Graph for the drive's ``webUrl`` (which includes the correct
    /sites/<sitename>/<library> path) so we can build a browser-openable
    URL underneath it. The result is cached per cloud config so this
    only costs a Graph call the first time per session.
    """
    try:
        from ..adapters import wiring
        from ..adapters.cloud.config import load_cloud_config_from_env
        if not wiring._cloud_flag_enabled():  # noqa: SLF001
            return None
        config = load_cloud_config_from_env()
        if not config.exports_enabled:
            return None
    except Exception:
        return None

    cache_key = (
        f"{config.sharepoint_site_id}|"
        f"{config.exports_library_name}|"
        f"{config.exports_library_internal_name}"
    )
    cached = _drive_web_url_cache.get(cache_key)
    if cached:
        return cached

    try:
        from ..adapters.cloud.graph_drive_gateway import GraphDriveGateway
        web_url = GraphDriveGateway.web_url_from_active_cloud(
            config,
            library_names=(
                config.exports_library_name,
                config.exports_library_internal_name,
            ),
        )
    except Exception:
        return None
    if not web_url:
        return None
    _drive_web_url_cache[cache_key] = web_url
    return web_url


_drive_web_url_cache: dict[str, str] = {}


def _portable_folder_path(value: str, *, file_path: bool = False) -> tuple[str, str]:
    """Validate a library-relative saved path and return folder/error."""
    from pathlib import PurePosixPath

    normalized = str(value or "").replace("\\", "/").strip("/")
    if not normalized:
        return "", ""
    portable = PurePosixPath(normalized)
    if portable.is_absolute() or ".." in portable.parts:
        return "", "Saved cloud folder path is invalid"
    folder = portable.parent if file_path else portable
    if not str(folder) or str(folder) == ".":
        return "", "Saved cloud folder path is invalid"
    return str(folder), ""


def resolve_show_folder(body: dict) -> dict:
    """Decide what to open for a PDF, vehicle, or photo-folder action.

    Body keys:
      - agency: str
      - year: str

    Returns one of:
      {"ok": True, "method": "explorer", "path": "<local-path>"} — found
        a OneDrive-synced copy of the SharePoint folder; open in
        Explorer.
      {"ok": True, "method": "browser", "url": "<sharepoint-url>"} —
        no OneDrive sync available; open in default browser.
      {"ok": False, "error": "<reason>"} — cloud not configured.
    """
    agency = _sanitize_segment(body.get("agency") or "")
    year = _sanitize_segment(body.get("year") or "Unassigned")

    try:
        from ..adapters.cloud.config import load_cloud_config_from_env
        config = load_cloud_config_from_env()
    except Exception:
        return {"ok": False, "error": "Cloud config not available"}
    requested_target = str(body.get("library_target") or "").strip().casefold()
    folder_path, folder_error = _portable_folder_path(body.get("folder_path") or "")
    shop_pdf_path = str(body.get("shop_pdf_path") or "")
    if not folder_path and shop_pdf_path:
        folder_path, folder_error = _portable_folder_path(shop_pdf_path, file_path=True)
        requested_target = requested_target or "shop"
    if folder_error:
        # Preserve the old Shop-specific wording for existing callers.
        message = "Saved Shop folder path is invalid" if shop_pdf_path else folder_error
        return {"ok": False, "error": message}

    if folder_path:
        base_subpath = folder_path
        if requested_target == "company":
            library_name = config.company_library_name or config.exports_library_name
            internal_name = (
                config.company_library_internal_name or config.exports_library_internal_name
            )
            if not (library_name or internal_name):
                return {"ok": False, "error": "Company Files library not configured"}
        elif requested_target == "shop":
            library_name = config.shop_library_name
            internal_name = config.shop_library_internal_name
            if not (library_name or internal_name):
                return {"ok": False, "error": "Shop Documents library not configured"}
        else:
            return {"ok": False, "error": "Select Company Files or Shop Documents"}
    else:
        if not config.exports_enabled:
            return {"ok": False, "error": "Cloud exports library not configured"}
        base_segments = [s for s in (
            (config.exports_base_folder or "").strip().strip("/"),
            agency,
            year,
        ) if s]
        base_subpath = "/".join(base_segments)
        library_name = config.exports_library_name
        internal_name = config.exports_library_internal_name

    local = _find_onedrive_synced_folder(
        library_name,
        internal_name,
        base_subpath,
        exact=bool(folder_path),
    )
    if local is not None:
        # We don't actually open here — the route handler does that via
        # the platform-appropriate command. We just return the path so
        # the UI can decide.
        return {"ok": True, "method": "explorer", "path": str(local)}

    if folder_path:
        drive_web_url = _get_named_drive_web_url(
            config.sharepoint_site_id, library_name, internal_name,
        )
        if drive_web_url:
            from urllib.parse import quote
            encoded = "/".join(quote(segment) for segment in base_subpath.split("/") if segment)
            web_url = f"{drive_web_url.rstrip('/')}/{encoded}" if encoded else drive_web_url
        else:
            web_url = None
    else:
        web_url = _build_sharepoint_web_url(
            config.sharepoint_site_id,
            config.exports_library_name,
            base_subpath,
        )
    if web_url:
        return {"ok": True, "method": "browser", "url": web_url}
    return {"ok": False, "error": "Could not resolve SharePoint URL from cloud_config"}


def _get_named_drive_web_url(
    site_id: str, library_name: str, internal_name: str,
) -> Optional[str]:
    """Resolve a configured library web URL without assuming its backend name."""
    candidates = {
        str(library_name or "").strip().casefold(),
        str(internal_name or "").strip().casefold(),
    } - {""}
    if not site_id or not candidates:
        return None
    cache_key = f"named|{site_id}|{'|'.join(sorted(candidates))}"
    if cache_key in _drive_web_url_cache:
        return _drive_web_url_cache[cache_key]
    try:
        from ..adapters import wiring
        if not wiring._cloud_flag_enabled():  # noqa: SLF001
            return None
        from ..adapters.cloud.config import load_cloud_config_from_env
        from ..adapters.cloud.graph_drive_gateway import GraphDriveGateway
        config = load_cloud_config_from_env()
        web_url = GraphDriveGateway.web_url_from_active_cloud(
            config,
            library_names=(library_name, internal_name),
        )
    except Exception:
        logger.exception("Could not resolve configured library web URL")
        return None
    if web_url:
        _drive_web_url_cache[cache_key] = web_url
        return web_url
    return None


def open_show_folder(body: dict) -> dict:
    """Resolve + open. Used directly by /api/build/show-folder."""
    resolved = resolve_show_folder(body)
    if not resolved.get("ok"):
        return resolved
    try:
        if resolved["method"] == "explorer":
            path = resolved["path"]
            if sys.platform == "darwin":
                subprocess.Popen(["open", path])
            elif sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", path])
        else:
            url = resolved["url"]
            if sys.platform == "darwin":
                subprocess.Popen(["open", url])
            elif sys.platform == "win32":
                os.startfile(url)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", url])
        return resolved
    except Exception as exc:
        logger.exception("Failed to open show-folder target")
        return {"ok": False, "error": str(exc)}
