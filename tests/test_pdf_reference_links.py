from __future__ import annotations

from pathlib import Path

import fitz

from dtm_buildsheet.app.services.pdf_reference_links import add_reference_photo_links


def _blank_pdf(path: Path, pages: int) -> None:
    document = fitz.open()
    for _ in range(pages):
        document.new_page(width=960, height=540)
    document.save(path)
    document.close()


def test_reference_links_cover_last_four_up_pages(tmp_path):
    pdf = tmp_path / "build.pdf"
    _blank_pdf(pdf, 5)
    targets = [f"Build Reference Photos/photo-{index}.jpg" for index in range(5)]

    result = add_reference_photo_links(pdf, targets)

    assert result == {"ok": True, "links_added": 5}
    document = fitz.open(pdf)
    assert [len(document[index].get_links()) for index in range(5)] == [0, 0, 0, 4, 1]
    assert document[3].get_links()[0]["file"].endswith("photo-0.jpg")
    document.close()


def test_reference_links_ignore_unsafe_targets(tmp_path):
    pdf = tmp_path / "build.pdf"
    _blank_pdf(pdf, 1)

    result = add_reference_photo_links(pdf, [
        "../secret.jpg",
        "/absolute.jpg",
        "Build Reference Photos/nested/photo.jpg",
    ])

    assert result == {"ok": True, "links_added": 0}
    document = fitz.open(pdf)
    assert document[0].get_links() == []
    document.close()


def test_reference_links_follow_adaptive_portrait_pagination(tmp_path):
    pdf = tmp_path / "build.pdf"
    _blank_pdf(pdf, 4)
    targets = [f"Build Reference Photos/photo-{index}.jpg" for index in range(4)]

    result = add_reference_photo_links(
        pdf,
        targets,
        sizes=[(800, 1200), (1200, 800), (1200, 800), (1200, 800)],
    )

    assert result == {"ok": True, "links_added": 4}
    document = fitz.open(pdf)
    assert [len(document[index].get_links()) for index in range(4)] == [0, 0, 3, 1]
    document.close()


def test_sharepoint_web_link_uses_preview_compatible_uri(tmp_path):
    pdf = tmp_path / "build.pdf"
    _blank_pdf(pdf, 1)

    result = add_reference_photo_links(
        pdf,
        ["Build Reference Photos/photo.jpg"],
        sizes=[(1200, 800)],
        web_urls=["https://tenant.sharepoint.com/photo.jpg"],
    )

    assert result == {"ok": True, "links_added": 1}
    document = fitz.open(pdf)
    assert document[0].get_links()[0]["uri"] == "https://tenant.sharepoint.com/photo.jpg"
    document.close()


def test_sharepoint_uri_replaces_overlapping_converted_ppt_link(tmp_path):
    pdf = tmp_path / "build.pdf"
    document = fitz.open()
    page = document.new_page(width=960, height=540)
    page.insert_link({
        "kind": fitz.LINK_LAUNCH,
        "from": fitz.Rect(30, 80, 930, 500),
        "file": "Build Reference Photos/photo.jpg",
    })
    document.save(pdf)
    document.close()

    result = add_reference_photo_links(
        pdf,
        ["Build Reference Photos/photo.jpg"],
        sizes=[(1200, 800)],
        web_urls=["https://tenant.sharepoint.com/photo.jpg"],
    )

    assert result == {"ok": True, "links_added": 1}
    document = fitz.open(pdf)
    assert [link.get("uri") for link in document[0].get_links()] == [
        "https://tenant.sharepoint.com/photo.jpg",
    ]
    document.close()
