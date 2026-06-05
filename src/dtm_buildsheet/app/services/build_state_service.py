"""Helpers for the smart Preview/Export buttons in the Builds tab.

Two responsibilities:

- ``get_render_status`` — given an output_path and a last_rendered_at
  timestamp, return whether the file exists locally, whether a PDF
  exists alongside it, and whether the file has been touched in
  PowerPoint since the last render. The UI uses this to decide between
  "open directly", "re-render silently", and "warn about manual edits".

- ``resolve_show_folder`` — figure out where "Show in folder" should
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
) -> Optional[Path]:
    """Glob the user's local OneDrive siblings for a folder matching the
    target SharePoint library.

    Examples on Windows:
        %USERPROFILE%\\dtmfleet.com\\Company Files\\Vehicle Builder Projects\\Acme PD\\2026
        %USERPROFILE%\\OneDrive - dtmfleet.com\\Company Files\\Vehicle Builder Projects\\Acme PD\\2026

    We try each candidate root; for each one we walk one or two levels
    deep looking for a directory whose name contains the library display
    or internal name, then descend into base_subpath under it.
    """
    targets = {t.strip().lower() for t in (library_display_name, library_internal_name) if t.strip()}
    if not targets:
        return None

    for root in _onedrive_candidate_roots():
        if not root.exists() or not root.is_dir():
            continue
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            name_lc = entry.name.lower()
            # The library folder might be a direct child (e.g. "Company Files")
            # or nested inside a tenant-named folder ("dtmfleet.com").
            if any(t in name_lc for t in targets):
                candidate = entry / base_subpath
                if candidate.exists():
                    return candidate
                if entry.exists():
                    return entry  # at least the library — better than nothing
                continue
            # Otherwise descend one level (tenant folder convention).
            try:
                children = list(entry.iterdir())
            except OSError:
                continue
            for child in children:
                if not child.is_dir():
                    continue
                if any(t in child.name.lower() for t in targets):
                    candidate = child / base_subpath
                    if candidate.exists():
                        return candidate
                    return child
    return None


def _build_sharepoint_web_url(
    site_id: str,
    library_display_name: str,
    base_subpath: str,
) -> Optional[str]:
    """Compose a SharePoint web URL pointing at the agency/year folder.

    The site_id stored in cloud_config has the form
    "{host},{site_collection_guid},{site_guid}". We can extract the
    hostname and build a /sites/.../<library>/<path> URL. If the host
    can't be parsed we return None and the caller falls back to a
    raw-file open of the local copy.
    """
    if not site_id:
        return None
    host = site_id.split(",", 1)[0].strip()
    if not host:
        return None
    # Most internal-name aware URLs require knowing the site relative
    # path, but the public host + library route works without it.
    from urllib.parse import quote
    encoded_subpath = "/".join(quote(seg) for seg in base_subpath.split("/") if seg)
    library = quote(library_display_name or "")
    return f"https://{host}/{library}/{encoded_subpath}" if library else None


def resolve_show_folder(body: dict) -> dict:
    """Decide what to open for the per-build "Show in folder" button.

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
    if not config.exports_enabled:
        return {"ok": False, "error": "Cloud exports library not configured"}

    base_segments = [s for s in (
        (config.exports_base_folder or "").strip().strip("/"),
        agency,
        year,
    ) if s]
    base_subpath = "/".join(base_segments)

    local = _find_onedrive_synced_folder(
        config.exports_library_name,
        config.exports_library_internal_name,
        base_subpath,
    )
    if local is not None:
        # We don't actually open here — the route handler does that via
        # the platform-appropriate command. We just return the path so
        # the UI can decide.
        return {"ok": True, "method": "explorer", "path": str(local)}

    web_url = _build_sharepoint_web_url(
        config.sharepoint_site_id,
        config.exports_library_name,
        base_subpath,
    )
    if web_url:
        return {"ok": True, "method": "browser", "url": web_url}
    return {"ok": False, "error": "Could not resolve SharePoint URL from cloud_config"}


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
