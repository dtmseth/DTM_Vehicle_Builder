from __future__ import annotations

import re
from pathlib import Path

# Characters that must not appear in a safe ID (path separators, null, etc.)
_UNSAFE_ID_RE = re.compile(r'[/\\:\x00]')

# Names that are suspicious even without separators
_RESERVED_NAMES = frozenset({
    ".", "..", "con", "prn", "aux", "nul",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
})


def validate_safe_id(value: str, label: str = "id") -> str:
    """Return *value* unchanged if it is a safe draft/project/preset identifier.

    Raises ValueError for:
    - empty string
    - absolute paths (start with / or a drive letter like C:)
    - path components (.. or . alone)
    - forward or back slashes, colons, or null bytes
    - Windows reserved device names
    """
    if not value or not value.strip():
        raise ValueError(f"Invalid {label}: must not be empty")
    stripped = value.strip()
    if Path(stripped).is_absolute():
        raise ValueError(f"Invalid {label}: must not be an absolute path")
    if _UNSAFE_ID_RE.search(stripped):
        raise ValueError(f"Invalid {label}: contains path separator or forbidden character")
    lower = stripped.lower()
    # Strip any extension before checking reserved names
    stem = lower.rsplit(".", 1)[0] if "." in lower else lower
    if stem in _RESERVED_NAMES or lower in _RESERVED_NAMES:
        raise ValueError(f"Invalid {label}: reserved name '{stripped}'")
    return stripped


def assert_within_root(path: Path, root: Path) -> Path:
    """Resolve *path* and verify it is under *root*.

    Returns the resolved Path on success; raises ValueError otherwise.
    """
    resolved = path.resolve()
    resolved_root = root.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        raise ValueError(
            f"Path '{resolved}' is outside the allowed root '{resolved_root}'"
        )
    return resolved
