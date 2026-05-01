from __future__ import annotations

_COLOR_PRESETS: dict[str, tuple[str, str] | None] = {
    "blue": ("legacy_uniform", "blue"),
    "white": ("legacy_uniform", "white"),
    "amber": ("legacy_uniform", "amber"),
    "red/blue": ("legacy_uniform", "red-blue"),
    "red and blue": ("duo_r_b", ""),
    "red/white blue/white": ("std_duo_rb_w", ""),
    "red/amber blue/amber": ("duo_ra_ba", ""),
    "single color (specify)": None,
    "dual color (specify)": None,
    "tri color (specify)": None,
}


def _normalize_token(value: str) -> str:
    if not value:
        return ""
    token = value.strip().lower()
    for separator in ["/", " and ", "&", ",", " "]:
        token = token.replace(separator, "-")
    while "--" in token:
        token = token.replace("--", "-")
    return token.strip("-")


def resolve_profile(part, spec: dict, asset_manifest: dict) -> tuple[str, str]:
    """Return (profile_id, raw_color_token) for a part."""
    color_profiles = asset_manifest.get("color_profiles", {})

    explicit = _normalize_token(part.explicit_color_profile)
    if explicit and explicit in color_profiles:
        return explicit, ""

    if part.raw_color:
        preset_key = part.raw_color.strip().lower()
        if preset_key in _COLOR_PRESETS:
            preset_result = _COLOR_PRESETS[preset_key]
            if preset_result is not None:
                return preset_result
            category = {"single": "single", "dual": "duo", "tri": "trio"}.get(
                preset_key.split()[0], "single"
            )
            if part.notes:
                notes_token = _normalize_token(part.notes)
                notes_preset_result = _COLOR_PRESETS.get(part.notes.strip().lower())
                if notes_preset_result is not None:
                    return notes_preset_result
                notes_alias = asset_manifest.get("legacy_color_aliases", {}).get(notes_token, {})
                if "profile" in notes_alias and notes_alias["profile"] in color_profiles:
                    return notes_alias["profile"], notes_token
                if "color_token" in notes_alias:
                    return "legacy_uniform", notes_alias["color_token"]
                if notes_token in asset_manifest.get("light_color_tokens", []):
                    return "legacy_uniform", notes_token
            return "specify_palette", category

    if part.driver_color or part.passenger_color or part.center_color:
        return "custom", ""

    raw_token = _normalize_token(part.raw_color)
    alias = asset_manifest.get("legacy_color_aliases", {}).get(raw_token, {})
    if "profile" in alias and alias["profile"] in color_profiles:
        return alias["profile"], raw_token
    if "color_token" in alias:
        return "legacy_uniform", alias["color_token"]

    if raw_token in asset_manifest.get("light_color_tokens", []):
        return "legacy_uniform", raw_token

    default_profile = spec.get("default_color_profile", "")
    if default_profile and default_profile in color_profiles:
        return default_profile, raw_token

    return "none", raw_token


def resolve_color_token(
    profile_id: str,
    raw_color_token: str,
    slot_role: str,
    part,
    asset_manifest: dict,
) -> str:
    """Return the concrete color token for one render instance slot."""
    if profile_id == "none":
        return ""
    if profile_id == "custom":
        role_map = {
            "driver": _normalize_token(part.driver_color),
            "passenger": _normalize_token(part.passenger_color),
            "center": _normalize_token(part.center_color),
        }
        return role_map.get(slot_role) or role_map.get("center") or raw_color_token
    if profile_id == "legacy_uniform":
        return raw_color_token

    profile = asset_manifest.get("color_profiles", {}).get(profile_id, {})
    slot_tokens = profile.get("slot_tokens", {})
    return slot_tokens.get(slot_role) or slot_tokens.get("default") or raw_color_token
