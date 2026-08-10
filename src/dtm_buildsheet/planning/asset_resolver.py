from __future__ import annotations


def size_class_for_part(
    part_number: str,
    asset_manifest: dict,
    *,
    explicit_size_class: str = "",
) -> str:
    """Return the size class for a part.

    ``explicit_size_class`` is the parts-db bridge used by both picker-created
    and legacy-imported lines. It deliberately accepts only a profile that
    actually exists; unassigned parts use the Small profile.
    """
    definitions = asset_manifest.get("size_rule_definitions", {})
    if explicit_size_class and explicit_size_class in definitions:
        return explicit_size_class
    return "sm"


def resolve_asset_path(
    render_kind: str,
    asset_key: str,
    view: str,
    orientation: str,
    color_token: str,
    asset_manifest: dict,
    fallback_images: dict | None = None,
) -> str:
    """Return the relative asset path for one render instance, or '' if none."""
    if render_kind == "equipment":
        manifest_path = (
            asset_manifest.get("equipment_assets", {}).get(asset_key, {}).get(view, "")
            if asset_key
            else ""
        )
        return manifest_path or (fallback_images or {}).get(view, "")

    if render_kind == "bar":
        manifest_path = (
            asset_manifest.get("bar_assets", {}).get(asset_key, {}).get(view, "")
            if asset_key
            else ""
        )
        return manifest_path or (fallback_images or {}).get(view, "")

    if render_kind == "light" and color_token:
        if color_token in ("single", "duo", "trio"):
            return ""
        filename = asset_manifest["light_icon_rule"]["filename_pattern"].format(
            color_token=color_token,
            orientation=orientation,
        )
        return f"{asset_manifest['light_icon_rule']['subfolder']}/{filename}"

    return ""
