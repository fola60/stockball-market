"""Console entry point for `stockball-worker`; the command table lives in app.entrypoints.cli."""

from __future__ import annotations

from app.entrypoints.cli import main

__all__ = ["main"]

if __name__ == "__main__":
    raise SystemExit(main())
