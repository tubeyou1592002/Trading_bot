"""
ui/__main__.py — `python -m ui` entry point.

Launches the new User Application shell (UI-1 Main Window only):

    python -m ui

The legacy main.py application (SymbolSearchWindow) is NOT started or
imported by this entry point.
"""

import sys

from ui.app import main

if __name__ == "__main__":
    sys.exit(main())
