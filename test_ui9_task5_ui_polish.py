"""
test_ui9_task5_ui_polish.py — offline guard tests for the UI-9.5 surfaces.

Two defect classes this task is meant to make detectable automatically:

    1. Hard-coded user-facing English literals on the surfaces touched here
       (the main window, its navigation, and the placeholder pages).
       User-facing text must come from ui/strings.py.

    2. Missing glyphs in the application font (the UI-9.3 defect, where
       U+2014 and U+2192 rendered as empty boxes). This test checks the
       actual font file the application uses (IRANSansX-Regular.ttf) by
       reading its cmap table directly with fontTools, so the check is
       deterministic, offline and not dependent on offscreen font resolution.

This file is offline, deterministic and fast. It has its OWN file-local
qapp fixture (in this repository the fixture is per-file) and does not
import main, brokers.* or core.* (C6). It is the ONLY new test file
authorized by UI-9.5.
"""

from __future__ import annotations

import os
import sys
from typing import Generator

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel

from ui import strings as STRINGS
from ui.main_window import MainWindow, NAVIGATION_ITEMS, PLACEHOLDER_ITEMS

HERE = os.path.dirname(os.path.abspath(__file__))
WINDIR = os.environ.get("windir", "C:\\Windows")
FONT_PATH = os.path.join(WINDIR, "Fonts", "IRANSansX-Regular.ttf")

# ---------------------------------------------------------------------------
# English-literal sweep
# ---------------------------------------------------------------------------

# A real "hard-coded English literal" has at least one token of 3+ ASCII
# letters. Deliberate Latin identifiers and format placeholders are NOT
# English literals. The tokens below are allowed to contain ASCII letters
# because each has a documented justification (page keys, technical IANA
# identifiers, format placeholders, digit-format helpers).
_ALLOWED_LATIN_TOKENS = frozenset(
    {
        # Page keys — must stay English; they are dict keys, not display text.
        STRINGS.NAV_HOME,
        STRINGS.NAV_ACCOUNTS,
        STRINGS.NAV_ORDER_CONFIGURATION,
        STRINGS.NAV_SETTINGS,
        # Format/template strings whose {placeholders} or IANA identifiers are
        # deliberate Latin technical tokens, not prose. See strings.py doc.
        STRINGS.NOTE_TIMEZONE,
        STRINGS.QUEUE_COUNT_FORMAT,
        STRINGS.SUMMARY_CLOCK,
        STRINGS.SUMMARY_INTERVAL,
        STRINGS.SUMMARY_NEXT_MOMENTS,
        STRINGS.SUMMARY_RUN_MOMENTS,
        STRINGS.SUMMARY_SKIPPED,
        STRINGS.SUMMARY_STATE,
        STRINGS.SUMMARY_WINDOW,
        STRINGS.SYNC_STALE,
        STRINGS.SYNC_OK_PREFIX,
        STRINGS.SYNC_OK_OFFSET,
        STRINGS.SYNC_OK_UNCERTAINTY,
        STRINGS.DIAGNOSTIC_BROKER_PREFIX,
        STRINGS.DIAGNOSTIC_BROKER_NONE,
        STRINGS.DIAGNOSTIC_ENTRY_PREFIX,
        STRINGS.DIAGNOSTIC_STAGE_PREFIX,
        # Digit-format helpers (return strings; Their *names* are English but
        # they are not *displayed* strings — exclude by token identity anyway).
        STRINGS.format_technical,
        STRINGS.format_persian_digits,
        STRINGS.format_grouped,
    }
)

_ENGLISH_WORD_RE = __import__("re").compile(rb"[A-Za-z]{3,}")


def _has_english_word(value: str) -> bool:
    """True if *value* contains a hard-coded English word (3+ ASCII letters)."""
    return bool(_ENGLISH_WORD_RE.search(value.encode("utf-8")))


# ---------------------------------------------------------------------------
# Fixture — file-local QApplication
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp() -> Generator[QApplication, None, None]:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    # Mirror create_app(): register the approved font and set the app font.
    if os.path.isfile(FONT_PATH):
        from PySide6.QtGui import QFontDatabase

        QFontDatabase.addApplicationFont(FONT_PATH)
    from ui.theme import primary_font

    app.setFont(primary_font())
    yield app


# ---------------------------------------------------------------------------
# 1. No user-facing English literal on the surfaces touched here
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "token_name,token_value",
    [
        (name, getattr(STRINGS, name))
        for name in sorted(STRINGS.__all__)
        if getattr(STRINGS, name) not in _ALLOWED_LATIN_TOKENS
    ],
    ids=[name for name in sorted(STRINGS.__all__) if getattr(STRINGS, name) not in _ALLOWED_LATIN_TOKENS],
)
def test_user_facing_string_is_persian(qapp, token_name: str, token_value: str) -> None:
    """No displayed user-facing string is a hard-coded English literal.

    Every user-facing token that is actually shown to the user is Persian
    (or a mechanical token such as "-", which has no ASCII letters at all).
    The tokens allowed to contain Latin are flagged in _ALLOWED_LATIN_TOKENS
    and skipped here, because each one has a documented justification.
    """
    assert not _has_english_word(token_value), (
        f"user-facing token {token_name!r} looks like a hard-coded English "
        f"literal: {token_value!r}"
    )


def test_main_window_renders_no_hardcoded_english(qapp) -> None:
    """The surfaces this task touches render no hard-coded English display text.

    Read back the actual displayed text of every widget the task touches and
    assert none contains a hard-coded English word. These must come from
    ui/strings.py (already asserted Persian above for the catalogue tokens).
    """
    window = MainWindow()
    try:
        checks: list[tuple[str, str]] = []

        checks.append(("WINDOW_TITLE", window.windowTitle()))

        for name in NAVIGATION_ITEMS:
            checks.append((f"NAV[{name!r}]", window.nav_buttons[name].text()))

        for name in PLACEHOLDER_ITEMS:
            panel = window.placeholder_pages[name]
            title_text = ""
            desc_text = ""
            for child in panel.findChildren(QLabel):
                if child.property("labelType") == "emptyTitle":
                    title_text = child.text()
                elif child.property("labelType") == "emptyDesc":
                    desc_text = child.text()
            checks.append((f"PLACEHOLDER[{name!r}] title", title_text))
            checks.append((f"PLACEHOLDER[{name!r}] desc", desc_text))

        checks.append(("MODE_LABEL", window.mode_label.text()))
        checks.append(("BUTTON_DIAGNOSTIC_MODE", window.mode_toggle.text()))
        checks.append(("TOOLTIP_DIAGNOSTIC_MODE", window.mode_toggle.toolTip()))

        for label, text in checks:
            assert not _has_english_word(text), (
                f"surface {label!r} renders a hard-coded English word: {text!r}"
            )
    finally:
        window.close()
        window.deleteLater()


# ---------------------------------------------------------------------------
# 2. Glyph coverage of the font the application actually uses
# ---------------------------------------------------------------------------

# The UI-9.3 defect class: characters that IRANSansX cannot draw and that
# rendered as empty boxes. The two headline ones are U+2014 and U+2192;
# this test asserts the font the app uses lacks them (so if someone later
# re-introduces such a character into a displayed string, the test catches
# it), and that every character the UI strings use today IS covered.
#
# fontTools reads the font file's cmap table directly — deterministic,
# offline, no QApplication paint device, no segfault. It is the same file
# the application uses for IRANSansX.

def _cmap_for_app_font():
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        pytest.skip("fontTools is not installed")

    if not os.path.isfile(FONT_PATH):
        pytest.skip(f"application font not found at {FONT_PATH}")
    font = TTFont(FONT_PATH, fontNumber=0)
    cmap = font.getBestCmap()
    if cmap is None:
        pytest.skip("font has no best cmap subtable")
    return cmap


@pytest.mark.parametrize(
    "codepoint,name",
    [
        (0x2014, "U+2014 em dash —"),
        (0x2192, "U+2192 rightwards arrow →"),
    ],
)
def test_defect_characters_are_missing_from_app_font(codepoint: int, name: str) -> None:
    """The UI-9.3 defect characters are genuinely absent from IRANSansX.

    If IRANSansX later gains a glyph for one of these, any displayed string
    that still uses it will be caught by the surface-string coverage check
    below (which asserts every UI-string character IS covered).
    """
    cmap = _cmap_for_app_font()
    assert codepoint not in cmap, (
        f"{name} (U+{codepoint:04X}) is present in IRANSansX — the UI-9.3 "
        f"defect class is no longer present for this codepoint"
    )


@pytest.mark.parametrize(
    "codepoint,name",
    [
        (0x2026, "U+2026 ellipsis …"),
        (0x200C, "U+200C ZWNJ"),
        (0x200D, "U+200D ZWJ"),
        (0x0627, "U+0627 alef"),
        (0x0648, "U+0648 waw"),
        (0x0631, "U+0631 re"),
        (0x0647, "U+0647 he"),
        (0x064A, "U+064A yeh (Arabic)"),
        (0x06CC, "U+06CC yeh (Persian)"),
        (0x067E, "U+067E peh"),
    ],
)
def test_known_covered_characters_are_present(codepoint: int, name: str) -> None:
    """Characters the UI relies on are present in IRANSansX (sanity trap)."""
    cmap = _cmap_for_app_font()
    assert codepoint in cmap, (
        f"{name} (U+{codepoint:04X}) is MISSING from IRANSansX — a displayed "
        f"UI character would render as an empty box"
    )


def test_every_ui_string_character_is_covered_by_app_font() -> None:
    """No character used in any ui/strings.py value lacks a glyph in IRANSansX.

    This is the general guard: if a future edit introduces a character that
    IRANSansX cannot draw into a user-facing string, this test fails. It is
    the complement of the "defect characters are missing" check above.
    """
    cmap = _cmap_for_app_font()
    missing: list[tuple[str, int, str]] = []
    for attr in sorted(STRINGS.__all__):
        value = getattr(STRINGS, attr)
        if not isinstance(value, str):
            continue
        for ch in value:
            if ord(ch) not in cmap:
                missing.append((attr, ord(ch), ch))
    assert not missing, (
        "ui/strings.py uses characters absent from IRANSansX: "
        + ", ".join(f"{attr!r} U+{cp:04X} {ch!r}" for attr, cp, ch in missing)
    )
