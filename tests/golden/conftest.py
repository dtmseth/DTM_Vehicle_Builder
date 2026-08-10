from __future__ import annotations


def pytest_addoption(parser):
    parser.addoption(
        "--golden-record",
        action="store_true",
        default=False,
        help="Re-record golden-master digests instead of comparing (GOLDEN_MASTER_SPEC.md §6).",
    )
