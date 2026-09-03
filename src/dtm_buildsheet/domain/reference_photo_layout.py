"""Adaptive, renderer-independent layout for build-reference photo pages."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReferencePhotoPlacement:
    source_index: int
    left: float
    top: float
    width: float
    height: float


@dataclass(frozen=True)
class ReferencePhotoPage:
    placements: tuple[ReferencePhotoPlacement, ...]


def _is_portrait(size: tuple[int, int]) -> bool:
    width, height = size
    return height > width


def _page_source_indexes(sizes: list[tuple[int, int]]) -> list[list[int]]:
    """Preserve photo order while giving each portrait two grid slots."""
    pages: list[list[int]] = []
    current: list[int] = []
    used_slots = 0
    for index, size in enumerate(sizes):
        cost = 2 if _is_portrait(size) else 1
        if current and used_slots + cost > 4:
            pages.append(current)
            current = []
            used_slots = 0
        current.append(index)
        used_slots += cost
    if current:
        pages.append(current)
    return pages


def _placement(source_index: int, left: float, top: float, width: float, height: float):
    return ReferencePhotoPlacement(source_index, left, top, width, height)


def _layout_page(indexes: list[int], sizes: list[tuple[int, int]]) -> ReferencePhotoPage:
    portraits = [index for index in indexes if _is_portrait(sizes[index])]
    landscapes = [index for index in indexes if index not in portraits]
    placements: list[ReferencePhotoPlacement] = []
    gap = 0.025
    half_w = (1.0 - gap) / 2
    half_h = (1.0 - gap) / 2

    if len(portraits) == 2:
        placements.extend((
            _placement(portraits[0], 0, 0, half_w, 1),
            _placement(portraits[1], half_w + gap, 0, half_w, 1),
        ))
    elif len(portraits) == 1:
        portrait_left = 0.25 if not landscapes else 0
        placements.append(_placement(portraits[0], portrait_left, 0, half_w, 1))
        if len(landscapes) == 1:
            placements.append(_placement(landscapes[0], half_w + gap, 0, half_w, 1))
        elif len(landscapes) >= 2:
            placements.extend((
                _placement(landscapes[0], half_w + gap, 0, half_w, half_h),
                _placement(landscapes[1], half_w + gap, half_h + gap, half_w, half_h),
            ))
    elif len(landscapes) == 1:
        placements.append(_placement(landscapes[0], 0, 0, 1, 1))
    elif len(landscapes) == 2:
        placements.extend((
            _placement(landscapes[0], 0, 0, half_w, 1),
            _placement(landscapes[1], half_w + gap, 0, half_w, 1),
        ))
    else:
        for slot, source_index in enumerate(landscapes[:4]):
            placements.append(_placement(
                source_index,
                (half_w + gap) if slot % 2 else 0,
                (half_h + gap) if slot >= 2 else 0,
                half_w,
                half_h,
            ))
    placements.sort(key=lambda item: indexes.index(item.source_index))
    return ReferencePhotoPage(tuple(placements))


def plan_reference_photo_pages(sizes: list[tuple[int, int]]) -> list[ReferencePhotoPage]:
    """Plan pages where a portrait always occupies a full two-row column."""
    normalized = [
        (max(1, int(width or 1)), max(1, int(height or 1)))
        for width, height in sizes
    ]
    return [_layout_page(indexes, normalized) for indexes in _page_source_indexes(normalized)]
