"""PyInstaller entry point.

screenmagnet/__main__.py uses relative imports (package-relative, e.g.
`from .tray import ...`), so PyInstaller needs to freeze it as a package
import rather than a bare script -- this shim does that.
"""
from screenmagnet.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
