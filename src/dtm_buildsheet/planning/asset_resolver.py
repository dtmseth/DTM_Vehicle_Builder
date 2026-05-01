from __future__ import annotations


def size_class_for_part(part_number: str, asset_manifest: dict) -> str:
    """Return the size class ('sm', 'md', 'lg', etc.) for a part number."""
    rules = asset_manifest.get("part_number_size_rules", {})
    part_number_upper = part_number.strip().upper()
    if not part_number_upper:
        return "sm"
    if part_number_upper in rules:
        return rules[part_number_upper]
    for key, size_class in rules.items():
        if key.upper() in part_number_upper:
            return size_class
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
