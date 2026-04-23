from __future__ import annotations

import sys
from pathlib import Path

from .generator import generate_build_sheet
from .paths import ensure_workspace


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv
    paths = ensure_workspace()
    input_path = Path(args[1]).expanduser().resolve() if len(args) > 1 else None
    result = generate_build_sheet(input_path, paths)
    print(f"Wrote: {result.plan_path}")
    print(f"Wrote: {result.summary_path}")
    print(f"Wrote: {result.ppt_path}")
    print("")
    print(result.terminal_summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
