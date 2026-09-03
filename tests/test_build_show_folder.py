from types import SimpleNamespace

from dtm_buildsheet.app.services.build_state_service import (
    _find_onedrive_synced_folder,
    resolve_show_folder,
)


def _config():
    return SimpleNamespace(
        exports_enabled=True,
        exports_base_folder="Vehicle Builder Projects",
        exports_library_name="Company Files",
        exports_library_internal_name="Documents",
        company_library_name="Company Files",
        company_library_internal_name="Documents",
        sharepoint_site_id="site-id",
        shop_target_configured=True,
        shop_library_name="Shop Documents",
        shop_library_internal_name="ShopDocs",
    )


def test_show_folder_prefers_saved_shop_vehicle_path(monkeypatch):
    monkeypatch.setattr(
        "dtm_buildsheet.app.adapters.cloud.config.load_cloud_config_from_env",
        _config,
    )
    monkeypatch.setattr(
        "dtm_buildsheet.app.services.build_state_service._find_onedrive_synced_folder",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "dtm_buildsheet.app.services.build_state_service._get_named_drive_web_url",
        lambda *args: "https://tenant.sharepoint.com/sites/DTM/ShopDocuments",
    )

    result = resolve_show_folder({
        "agency": "Wrong fallback",
        "year": "1900",
        "shop_pdf_path": (
            "Shop Project Database/Lake County/2027/PIU - Patrol/"
            "2027 PIU - Patrol - Unit 12/2027 PIU - Patrol - Unit 12.pdf"
        ),
    })

    assert result == {
        "ok": True,
        "method": "browser",
        "url": (
            "https://tenant.sharepoint.com/sites/DTM/ShopDocuments/"
            "Shop%20Project%20Database/Lake%20County/2027/PIU%20-%20Patrol/"
            "2027%20PIU%20-%20Patrol%20-%20Unit%2012"
        ),
    }


def test_show_folder_rejects_nonportable_shop_path(monkeypatch):
    monkeypatch.setattr(
        "dtm_buildsheet.app.adapters.cloud.config.load_cloud_config_from_env",
        _config,
    )

    result = resolve_show_folder({"shop_pdf_path": "Build Photos/../Secrets/file.pdf"})

    assert result == {"ok": False, "error": "Saved Shop folder path is invalid"}


def test_show_folder_opens_exact_company_photo_folder(monkeypatch):
    monkeypatch.setattr(
        "dtm_buildsheet.app.adapters.cloud.config.load_cloud_config_from_env",
        _config,
    )
    monkeypatch.setattr(
        "dtm_buildsheet.app.services.build_state_service._find_onedrive_synced_folder",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "dtm_buildsheet.app.services.build_state_service._get_named_drive_web_url",
        lambda *args: "https://tenant.sharepoint.com/sites/DTM/CompanyFiles",
    )

    result = resolve_show_folder({
        "library_target": "company",
        "folder_path": (
            "Vehicle Project Database/Lake County/2027/Reference Photos & Videos"
        ),
    })

    assert result == {
        "ok": True,
        "method": "browser",
        "url": (
            "https://tenant.sharepoint.com/sites/DTM/CompanyFiles/"
            "Vehicle%20Project%20Database/Lake%20County/2027/Reference%20Photos%20%26%20Videos"
        ),
    }


def test_show_folder_rejects_nonportable_generic_folder_path(monkeypatch):
    monkeypatch.setattr(
        "dtm_buildsheet.app.adapters.cloud.config.load_cloud_config_from_env",
        _config,
    )

    result = resolve_show_folder({
        "library_target": "shop",
        "folder_path": "Shop Project Database/Lake County/../Other Agency",
    })

    assert result == {"ok": False, "error": "Saved cloud folder path is invalid"}


def test_exact_photo_folder_uses_web_fallback_instead_of_synced_library_root(
    tmp_path, monkeypatch,
):
    library = tmp_path / "Company Files"
    library.mkdir()
    monkeypatch.setattr(
        "dtm_buildsheet.app.services.build_state_service._onedrive_candidate_roots",
        lambda: [tmp_path],
    )

    assert _find_onedrive_synced_folder(
        "Company Files", "Documents", "Agency/2027/Reference Photos & Videos",
        exact=True,
    ) is None
    assert _find_onedrive_synced_folder(
        "Company Files", "Documents", "Agency/2027/Reference Photos & Videos",
    ) == library
