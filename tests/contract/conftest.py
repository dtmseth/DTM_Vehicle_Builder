from __future__ import annotations


def pytest_addoption(parser):
    parser.addoption(
        "--contract-record",
        action="store_true",
        default=False,
        help="Re-record HTTP contract snapshots instead of comparing (§8.1 Step 1b).",
    )
