#!/usr/bin/env python3
"""Run the declarative development-market bootstrap through the worker CLI."""

from __future__ import annotations

import sys

from app.main import main

if __name__ == "__main__":
    raise SystemExit(main(["bootstrap-dev-market", *sys.argv[1:]]))
