"""Guard runtime resources required by the frozen desktop application."""

from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_windows_zoneinfo_fallback_is_declared_and_bundled():
    """Windows needs tzdata because it has no system IANA zoneinfo database."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = project["project"]["dependencies"]
    spec = (ROOT / "packaging" / "pyinstaller" / "DTM_VehicleBuilder.spec").read_text(
        encoding="utf-8"
    )

    assert any(dependency.startswith("tzdata") for dependency in dependencies)
    assert 'collect_data_files("tzdata")' in spec
    assert '"tzdata.zoneinfo"' in spec
