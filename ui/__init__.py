"""
ui — User Application package (UI-1: Application Foundation).

Contains only the presentation shell of the new User Application:

    ui/app.py          — QApplication creation / run entry point
    ui/main_window.py  — Main Window (navigation + content area + mode)
    ui/__main__.py     — `python -m ui` entry point

Boundaries (per AI_HANDOFF.md "User Application / UI Architecture & Roadmap"):

    * The UI creates no trading logic and never bypasses the existing Core;
      OrderEngine, DispatchCore, SafetyGate and M6-A..M6-E remain authoritative.
    * This package imports nothing from core/, brokers/, market/, models/ or
      main.py and performs no broker, TSETMC, credential or network access.
    * The legacy application in main.py (SymbolSearchWindow) is preserved
      unchanged for compatibility and is NOT imported by this package.

Foundation scope (UI-1): Main Window + Navigation placeholders
(Home / Accounts / Settings) + explicit NORMAL / DIAGNOSTIC mode state only.
No real functionality is implemented here (that starts at UI-2).
"""
