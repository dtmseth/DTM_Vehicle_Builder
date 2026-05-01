#!/usr/bin/env python3
# Compatibility shim — internal code should import from .app directly.
from .app.server import PORT as PORT, main as main  # noqa: PLC0414

if __name__ == "__main__":
    main()
