"""
ui/app.py — UI-1 application entry point.

Clean entry point for creating and running the QApplication of the new
User Application shell:

    * create_app(argv) — build the QApplication (without exec),
    * main(argv)       — build the QApplication, construct ui.main_window.
                         MainWindow, show it and enter the Qt event loop.

`python -m ui` (ui/__main__.py) starts ONLY this new Main Window; the legacy
application in main.py (SymbolSearchWindow) is not started and not imported.

No broker, TSETMC, credential or network access happens here, and no
trading-core module is imported by the UI Foundation.
"""

import sys

from PySide6.QtWidgets import QApplication

from ui.main_window import ApplicationMode, MainWindow

__all__ = ["ApplicationMode", "MainWindow", "create_app", "main"]


def create_app(argv=None):
    """
    Create the QApplication of the User Application (without exec).

    Returns the QApplication instance.

    Raises RuntimeError if a QApplication already exists in this process
    (Qt allows only one QApplication instance per process).
    """
    if QApplication.instance() is not None:
        raise RuntimeError(
            "A QApplication already exists in this process; "
            "create_app() must be called before any QApplication is created."
        )
    if argv is None:
        argv = []
    app = QApplication(list(argv))
    app.setApplicationName("Trading Bot")
    return app


def main(argv=None):
    """
    Build and run the User Application shell.

    Creates the QApplication, constructs the Main Window, shows it and
    enters the Qt event loop. Returns the application exit code.
    """
    app = create_app(argv)
    window = MainWindow()
    window.show()
    return app.exec()
