#!/usr/bin/env python3
"""Convenience shim so ``python cli.py`` still works.

The real CLI lives at :mod:`criminal_db.cli`.
"""
from criminal_db.cli import main


if __name__ == "__main__":
    main()
