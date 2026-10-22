"""
ui/order_configuration_page.py — UI-3.1/3.2A Order Configuration page.

Presentation of the order-configuration form:

    * Symbol       — editable input with REAL debounced symbol search
                     (UI-3.2A): typing triggers (after a 300 ms debounce,
                     the legacy application's existing pattern) a
                     background ``SymbolResolver.search()`` run on a
                     QThread; the resolver object is handed in lazily so
                     plain construction stays fully offline.
                     Selection stores ONLY a real resolver-produced
                     models.instrument.Instrument — the UI never parses
                     display text back into identity, never guesses
                     ``ins_code`` and never builds an instrument.
    * Symbol info  — display area for the selected instrument's
                     information, fed only from that real Instrument.
    * Symbol Status— display placeholder: "Not available" without a
                     verified source; NEVER shown as tradable/permitted
                     (real trading state is a LATER task — never touched
                     here).
    * Trading State — UI-3.2B: after a REAL instrument selection the
                     status is read from the EXISTING project path
                     (core.trading_state_query.TradingStateQuery →
                     provider.get_instrument → broker.get_trading_state
                     → TradingState) on a background QThread and
                     rendered ONLY from the returned ``TradingState``:
                     قابل معامله / غیرقابل معامله / نامشخص. Fail-closed:
                     TradingStateUnavailable and UNVERIFIED are shown as
                     نامشخص — never a crash, never "tradable". The raw
                     broker status mapping is never duplicated in the UI;
                     the state is never guessed from the symbol text,
                     and a changed/cleared symbol always drops the
                     previous instrument's state. A colour-coded status
                     circle is shown next to the symbol field; the full
                     Persian market status is available only through its
                     tooltip, rendered from the normalized MarketStatus
                     carried by that same TradingState.
    * Side         — Buy / Sell radio pair bound to the real project
                     constants models.order.BUY / models.order.SELL
    * Price        — numeric input (basic input-level validation only)
    * Quantity     — numeric input (basic input-level validation only)
    * Base Amount  — price * quantity (display only; NOT the final amount)
    * Fee          — placeholder: "Not available" (no fee contract yet;
                     UI-3.3 scope)
    * Final Amount — placeholder: "Not available" (never fabricated)

    * Active account — read verbatim from the existing AccountStore
                     (UI-2.1); never guessed from an index/symbol/broker;
                     clearly shown when no account is active.
    * Order Queue  — UI-4: a real "Add to Queue" action that prepares ONE
                      models.order.Order (real nsc_id resolved through the
                      broker provider off the GUI thread) and appends it
                      to the EXISTING core.order_queue.OrderQueue together
                      with the active account/broker binding — plus a
                      visible queue list rendered ONLY from
                      ``OrderQueue.list_pending()`` (the exact queued
                      objects, never clones).
    * Test Button  — UI-5 Task 1: a UI-ONLY toggle next to the queue
                      controls. OFF -> "Test", ON -> "Test (On)". It holds
                      ONE UI-local boolean (Test Mode, default OFF) and is
                      disabled while the queue is empty or the required
                      active account / selected instrument is missing. It
                      must NEVER execute, dispatch, or submit an order —
                      no DispatchIntegration/DispatchCore/OrderEngine, no
                      broker call, no network activity (Task 2 owns
                      execution).
    * Order Log      — UI-5 Task 4 (Stage 3): a read-only seven-column
                      table (زمان ارسال / حساب / نماد / توضیح / زمان دریافت
                      توسط کارگزاری / زمان ثبت در هسته معاملاتی / وضعیت صف)
                      with ONE row appended per SENT order, in send order,
                      rendered only from the in-memory ``ui.user_log.OrderLog``.
                      Stage 3 Task 3: when a REAL matching-engine registration
                      event arrives (through the existing feedback signal bound
                      via the injected feedback-binder factory), the row of the
                      EXACT matching order is stamped with the event's real
                      timestamp in «زمان ثبت در هسته معاملاتی» and rendered
                      highlighted (green). Unknown decisionIds create/change
                      nothing; the id itself is never displayed.
                      Stage 3 Task 4: the same bound feedback object also
                      carries the EXISTING queue-position feedback signal; its
                      value fills the row's «وضعیت صف» cell through the same
                      decisionId correlation. No queue-position logic is
                      implemented here — the page only consumes what the
                      existing Stage 2 path already computed.
    * Diagnostic section — UI-6 Task 1: ONE minimal, REAL diagnostic
                      section (the per-order execution verdicts of the last
                      Test pass, built ONLY from the REAL
                      ``OrderExecutionResult`` objects that pass already
                      produced — no new measurement, no fabricated value).
                      This is the display boundary the mode governs: the
                      section is hidden in NORMAL mode (the application
                      default) and may be shown in DIAGNOSTIC mode. The mode
                      state itself stays on ``MainWindow`` (the existing
                      ``ApplicationMode`` holder); the page only applies the
                      visibility that state asks for.

Stale-result protection (UI-3.2A): every search carries a monotonically
increasing sequence number; only the result of the LATEST sequence may
update the symbol combo's popup — an older, late-finishing result is
discarded.

Stale-result protection (UI-4): a resolved nsc_id belongs to one
(ins_code, broker_name) pair only — a symbol change or an account
switch always drops it (fail-closed) and never binds another broker's
identity to the new selection.

Boundaries: no OrderEngine, DispatchCore, SafetyGate, BrokerManager
run for ordering, no Broker API call from the UI, and no direct TSETMC
access from the UI; the only market seam is the real ``SymbolResolver``
(search/resolve) run on a background thread, the only state seam is the
real ``TradingStateQuery`` (read-only) on a background thread, the only
identity seam is the broker ``InstrumentProvider.get_nsc_id(ins_code)``
(read-only, background thread) and the only holder is the existing
``OrderQueue`` (lazy — the first queue access, never at construction).
The UI creates an ``Order`` ONLY on the explicit Add-to-Queue action,
always fail-closed: without a selected Instrument, side, price,
quantity, resolved nsc_id and an active account nothing is queued.
"""

import math
import threading
import inspect
from datetime import datetime, timedelta
from pathlib import Path

from models.order import BUY, SELL, Order
from models.trading_state import (
    MARKET_STATUS_GREEN,
    MarketStatus,
    TradingState,
    TradingStateUnavailable,
    market_status_label,
)

from PySide6.QtCore import QThread, QTimer, Qt, Signal, QDateTime, QSize
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QDialog,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui import strings as STRINGS
from ui.theme import GEOMETRY, PALETTE, SPACING

from ui.market_clock import (
    MarketClockService,
    MarketClockWorker,
    describe_clock,
    format_offset,
    format_uncertainty,
    SCHEDULE_SYNC_MAX_AGE_SECONDS,
    TEHRAN_TIMEZONE,
    ClockSource,
)
from ui.order_config_state import (
    SYMBOL_STATUS_NOT_AVAILABLE,
    OrderConfigError,
    OrderConfiguration,
)
from ui.schedule_dispatcher import (
    EXECUTION_INTERVAL_LABEL,
    EXECUTION_INTERVAL_PLACEHOLDER,
    DispatchIntervalError,
    DispatchTarget,
    DispatchTargetSetError,
    PeriodicScheduleDispatcher,
    parse_execution_interval_ms,
)
from ui.schedule_settings import (
    APPLY_BUTTON_LABEL,
    COUNTDOWN_LABEL_NO_UPCOMING,
    COUNTDOWN_LABEL_STOPPED,
    COUNTDOWN_LABEL_UNAVAILABLE,
    END_INPUT_LABEL,
    INTERVAL_INPUT_LABEL,
    INTERVAL_INPUT_PLACEHOLDER,
    SCHEDULE_GROUP_TITLE,
    SCHEDULE_UNAVAILABLE,
    SCHEDULE_STATE_CONFIG,
    SCHEDULE_STATE_COUNTING,
    SCHEDULE_STATE_EXPIRED,
    SCHEDULE_STATE_START_NOW,
    SCHEDULE_STATE_STOPPED,
    SCHEDULE_STATE_WAITING,
    START_INPUT_LABEL,
    STOP_BUTTON_LABEL,
    SYNC_BUTTON_LABEL,
    SYNC_BUTTON_LABEL_BUSY,
    SYNC_BUTTON_LABEL_FAILED,
    SYNC_STATE_FAILED,
    SYNC_STATE_IN_PROGRESS,
    SYNC_STATE_NEVER,
    TIME_INPUT_PLACEHOLDER,
    TIMEZONE_NOTE,
    ScheduleState,
    ScheduleValidationError,
    assess_schedule_window,
    build_dispatch_timing,
    build_schedule_summary,
    describe_summary,
    generate_schedule_times,
    parse_schedule_inputs,
)
from ui.symbol_search_worker import (
    SYMBOL_SEARCH_DEBOUNCE_MS,
    SymbolResolveWorker,
    SymbolSearchWorker,
)
from ui.trading_state_worker import TradingStateWorker
from ui.user_log import (
    COLUMN_QUEUE_STATUS,
    EMPTY_CELL,
    ORDER_LOG_COLUMNS,
    OrderLog,
    OrderLogRow,
)

# User-facing side labels — mapped 1:1 to the real project constants.
SIDE_LABELS = ((BUY, "خرید"), (SELL, "فروش"))

# Result identity travels inside Qt.UserRole — display text is NEVER
# parsed back into symbol/ins_code.
RESULT_DATA_ROLE = Qt.UserRole

# The search generation a row belongs to — a row from a superseded
# generation (the user already retyped) can never be resolved into a
# selection, even if the caller keeps a reference to the old item.
RESULT_SEQUENCE_ROLE = Qt.UserRole + 1

# Limit-arrow assets. Each arrow is its own SVG under ui/assets/icons —
# the up arrow is the theme success green, the down arrow the danger red.
_ICONS_DIR = Path(__file__).resolve().parent / "assets" / "icons"
_ARROW_UP_ICON = _ICONS_DIR / "arrow-up.svg"
_ARROW_DOWN_ICON = _ICONS_DIR / "arrow-down.svg"

_TRADING_STATUS_GREEN_ICON = _ICONS_DIR / "trading-status-green.svg"
_TRADING_STATUS_RED_ICON = _ICONS_DIR / "trading-status-red.svg"
_TRADING_STATUS_NEUTRAL_ICON = _ICONS_DIR / "trading-status-neutral.svg"
_MARKET_STATUS_ICONS = {
    PALETTE["success"]: _TRADING_STATUS_GREEN_ICON,
    PALETTE["danger"]: _TRADING_STATUS_RED_ICON,
    PALETTE["textMuted"]: _TRADING_STATUS_NEUTRAL_ICON,
}
_TRADING_STATUS_ICON_SIZE = SPACING["lg"]

PRICE_LIMIT_MAX = "max"
PRICE_LIMIT_MIN = "min"

# The three explicit, separated search states.
SEARCH_STATE_IDLE = ""
SEARCH_STATE_SEARCHING = STRINGS.SEARCH_SEARCHING
SEARCH_STATE_NO_RESULTS = STRINGS.SEARCH_NO_RESULTS


class _SymbolSuggestionRow:
    """Read-only row view over one suggestion in the symbol combo."""

    def __init__(self, combo, index):
        self._combo = combo
        self._index = index

    def data(self, role):
        return self._combo.itemData(self._index, role)

    def text(self):
        return self._combo.itemText(self._index)

    def setSelected(self, selected):  # noqa: N802 — Qt-style name
        # Suggestions live in the combo popup and are selected through
        # the combo itself; kept for compatibility with callers that used
        # the old QListWidget item API.
        return None


class _SymbolSuggestionList:
    """
    Compatibility view over the symbol combo's suggestion rows.

    The old standalone QListWidget is gone; suggestions now live in the
    editable combo's popup. This view keeps the former row-level read API
    available without creating a second visible results widget.
    """

    def __init__(self, combo):
        self._combo = combo

    def count(self):
        return self._combo.count()

    def item(self, index):
        return _SymbolSuggestionRow(self._combo, index)

    def clear(self):
        self._combo.clear()

    def setEnabled(self, enabled):  # noqa: N802 — Qt-style name
        self._combo.setEnabled(enabled)

    def isEnabled(self):  # noqa: N802 — Qt-style name
        return self._combo.isEnabled()


# UI-7 Task 2: how often the DISPLAY of the sync freshness line is
# re-rendered while a reading ages. This is display-only — it never
# starts a request — and it is deliberately shorter than the schedule
# freshness limit so the "expired" wording appears promptly.
SYNC_FRESHNESS_TICK_MS = 1000

# UI-3.2B — user-facing trading-state labels, rendered ONLY from the
# real ``TradingState`` the existing project path returned. The status
# is never guessed from the symbol text and the raw broker mapping
# stays inside the Core/broker path (Decision 020) — the UI renders
# only the three verdicts below. Fail-closed: an unavailable/unverified
# state is ALWAYS shown as unknown, never as tradable.
STATUS_LABEL_TRADABLE = "قابل معامله"
STATUS_LABEL_NOT_TRADABLE = "غیرقابل معامله"
STATUS_LABEL_UNKNOWN = "نامشخص"

# The status display before any query ran for the current selection.
STATUS_PENDING_LABEL = "در حال دریافت…"


def _market_status_color(status):
    if status in MARKET_STATUS_GREEN:
        return PALETTE["success"]
    if isinstance(status, MarketStatus):
        return PALETTE["danger"]
    return PALETTE["textMuted"]


def _market_status_icon_path(status):
    return _MARKET_STATUS_ICONS[_market_status_color(status)]


def _market_status_pixmap(status):
    color = QColor(_market_status_color(status))
    source = QIcon(str(_market_status_icon_path(status))).pixmap(
        QSize(_TRADING_STATUS_ICON_SIZE, _TRADING_STATUS_ICON_SIZE)
    )
    image = source.toImage().convertToFormat(QImage.Format_ARGB32)
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixelColor(x, y)
            if pixel.alpha() == 0:
                continue
            image.setPixelColor(
                x,
                y,
                QColor(color.red(), color.green(), color.blue(), pixel.alpha()),
            )
    return QPixmap.fromImage(image)


def _market_status_title(state):
    if isinstance(state, TradingState):
        title = state.market_status_title
        if isinstance(title, str) and title.strip():
            return title.strip()
        label = market_status_label(state.market_status)
        if label:
            return label
    return STATUS_LABEL_UNKNOWN


# UI-4 — the visible queue row's data role carries the EXACT
# QueueEntry object; the display is never parsed back into an identity
# and the order is never reconstructed for rendering.
QUEUE_ENTRY_ROLE = Qt.UserRole + 2

# UI-4 — user-facing queue feedback. Status is plain text rendered on
# the page (no message box on a path that must stay fail-closed and
# deterministic offscreen).
QUEUE_STATUS_EMPTY = STRINGS.QUEUE_STATUS_EMPTY
QUEUE_STATUS_NO_ACCOUNT = STRINGS.QUEUE_STATUS_NO_ACCOUNT
QUEUE_STATUS_NO_SYMBOL = STRINGS.QUEUE_STATUS_NO_SYMBOL
QUEUE_STATUS_INCOMPLETE = STRINGS.QUEUE_STATUS_INCOMPLETE
QUEUE_STATUS_NO_IDENTITY = STRINGS.QUEUE_STATUS_NO_IDENTITY
QUEUE_STATUS_BROKER_STALE = STRINGS.QUEUE_STATUS_BROKER_STALE
QUEUE_STATUS_QUEUED = STRINGS.QUEUE_STATUS_QUEUED

# UI-5 Task 3 — per-order Test results. Only these three user-facing
# statuses may ever be rendered; the raw per-order mode/message is never
# displayed (a Trace ID, latency value, M6-A…M6-E label, endpoint, nscId /
# tseId, raw Broker response, exception or internal id must never surface).
# Fail-closed: nothing except an actually-successful result is ever shown
# as "موفق".
RESULT_STATUS_SUCCESS = "\u0645\u0648\u0641\u0642"
RESULT_STATUS_BLOCKED = "\u0645\u0633\u062f\u0648\u062f\u0634\u062f\u0647"
RESULT_STATUS_FAILED = "\u0646\u0627\u0645\u0648\u0641\u0642"

# Fixed, user-facing reasons — one per status, never fabricated from a raw
# result message.
RESULT_REASON_SUCCESS = "\u0633\u0641\u0627\u0631\u0634 \u0628\u0627 \u0645\u0648\u0641\u0642\u06cc\u062a \u0634\u0628\u06cc\u0647\u200c\u0633\u0627\u0632\u06cc \u0634\u062f"
RESULT_REASON_BLOCKED = "\u0627\u062c\u0631\u0627 \u0645\u062a\u0648\u0642\u0641 \u0634\u062f"
RESULT_REASON_FAILED = "\u0627\u062c\u0631\u0627\u06cc \u0633\u0641\u0627\u0631\u0634 \u0646\u0627\u0645\u0648\u0641\u0642 \u0628\u0648\u062f"

# Empty state of the Test Results area before the first Test run.
# The wording lives in ui.strings; re-exported here because it is part
# of this module's existing public surface.
RESULT_EMPTY_STATE = STRINGS.RESULT_EMPTY_STATE

# Fail-closed placeholders for a per-order result row: a symbol the UI has
# no record of (never a technical nscId / tseId) and an unknown side label.
RESULT_SYMBOL_UNKNOWN = "-"


def _symbol_status_display(status):
    """Render a symbol-status *token* for humans (UI-9.3).

    ``config.symbol_status()`` returns machine-checked English tokens that the
    tests compare against; only the rendered text is Persian.
    """
    if status == SYMBOL_STATUS_NOT_AVAILABLE:
        return STRINGS.SYMBOL_STATUS_NOT_AVAILABLE_DISPLAY
    return status

# UI-5 Task 4 (Stage 3) — the user-facing order log table.
# The seven columns and their order live in ui.user_log.ORDER_LOG_COLUMNS; the
# rows come from the in-memory ui.user_log.OrderLog, one row appended per
# SENT order in send order. Information that does not exist yet is rendered
# as "—" (never invented). The feedback consumers are the Stage 3 Task 3
# trading-core registration stamp (a real matching-engine registration event
# resolved through the page's decisionId correlation, bound via the injected
# feedback-binder factory) and the Stage 3 Task 4 queue-status value (the
# EXISTING queue-position feedback signal of the SAME bound object). No queue
# logic is implemented here — the page only consumes what the existing Stage
# 2 path already computed.
ORDER_LOG_GROUP_TITLE = STRINGS.GROUP_ORDER_LOG

# UI-9 Task 2b — title of the group box that holds the queue status line in
# the scheduling column. English for now: Persian localization is UI-9.3,
# which must include this string in its translation list.
QUEUE_STATUS_GROUP_TITLE = STRINGS.GROUP_QUEUE_STATUS

# UI-9 Task 2 — how many Order Log rows stay visible before the table
# scrolls. A row is GEOMETRY["rowHeight"] tall, so this is expressed as a
# count and the height is derived, keeping the layout free of magic pixels.
ORDER_LOG_MIN_VISIBLE_ROWS = 4

# UI-5 Task 4 Stage 3 Task 3 — the highlight of a row whose order was REALLY
# registered in the trading core: a genuine matching-engine registration
# event arrived for that exact order and was stamped on the row. The highlight
# is derived ONLY from the row's ``registered_in_core`` flag (model state set
# by the real event) — never from a timer, a guess or any other outcome.
#
# UI-9 Task 2: the original value (#d9f2d9) was a very light mint, which is
# unreadable as a cell BACKGROUND under the dark theme's light text. It is
# now a dark success tint that keeps the same "this row succeeded" meaning
# while letting the theme's light text stay legible on top of it. The tests
# import this constant by name, so the contract is unchanged.
CORE_REGISTERED_ROW_COLOR = "#123524"


# ----------------------------------------------------------------------
# UI-6 Task 1 — Diagnostic Mode display boundary (minimal, real)
# ----------------------------------------------------------------------
# The application ships in NORMAL mode and MainWindow owns the single
# ApplicationMode state (ui.main_window.ApplicationMode). This page owns
# only the DISPLAY BOUNDARY of diagnostic information: the section below
# is hidden in NORMAL mode and may be shown in DIAGNOSTIC mode. Its only
# content is REAL diagnostic output the page already produces — the
# per-order execution verdicts of the last Test pass, derived from the
# actual ``OrderExecutionResult`` objects (core models, not invented UI
# text). No latency measurement, Trace ID, endpoint or broker payload is
# added here (later UI-6 tasks).
DIAGNOSTIC_SECTION_TITLE = STRINGS.GROUP_DIAGNOSTIC

# Head of every diagnostic entry: the user-visible 1-based position of the
# order in the last Test pass (its index in the existing per-order result
# rows), never a technical id.
DIAGNOSTIC_ENTRY_PREFIX = STRINGS.DIAGNOSTIC_ENTRY_PREFIX

# The verdict line comes from the EXISTING fail-closed result labels of
# Task 3 (موفق / مسدودشده / ناموفق) — the same ``_result_status_label``
# the Test Results area renders. No new verdict vocabulary is created.
DIAGNOSTIC_VERDICT_PREFIX = STRINGS.DIAGNOSTIC_VERDICT_PREFIX

# Diagnostic empty state — a real statement about the absence of a Test
# pass, not a fabricated value.
DIAGNOSTIC_EMPTY_STATE = STRINGS.DIAGNOSTIC_EMPTY_STATE

# UI-6 Task 2 — the Trace ID line of the diagnostic section. The trace id
# is the EXISTING dispatch-level id the Core already builds
# (``DispatchResult.trace_id`` of THIS run — no second id is ever created
# here). It belongs to the whole dispatch, so it is a section-level line,
# never attributed to any single order or log row. Fail-closed rendering:
# a missing/blank/foreign trace id renders the real unavailable marker —
# never a substitute id (``execution_id`` is a DIFFERENT identifier and is
# never shown in its place).
DIAGNOSTIC_TRACE_LABEL = STRINGS.DIAGNOSTIC_TRACE_LABEL
DIAGNOSTIC_TRACE_UNAVAILABLE = "-"  # ناموجود / نامشخص

# UI-6 Task 3 — latency/execution diagnostics of the EXISTING Block 8
# report (``DispatchLatencyReport`` of THIS run). The UI only RENDERS the
# report's own measurements — it never measures, re-derives, sums unlike
# categories or invents a value. Each category keeps its own name and
# scope; ns values are displayed converted to ms (display-only).
DIAGNOSTIC_LATENCY_TOTAL_LABEL = STRINGS.DIAGNOSTIC_LATENCY_TOTAL_LABEL
DIAGNOSTIC_VALUE_UNAVAILABLE = "\u0646\u0627\u0645\u0648\u062c\u0648\u062f"

# The four internal dispatch stages (Block 8 Task 8.2 — exactly these).
DIAGNOSTIC_LATENCY_STAGES = (
    "plan_item",
    "plan_account",
    "instrument_resolution",
    "order_engine_path",
)
DIAGNOSTIC_LATENCY_STAGE_PREFIX = STRINGS.DIAGNOSTIC_STAGE_PREFIX

# Broker/API round trip — the FULL measured call, never "network latency".
DIAGNOSTIC_LATENCY_BROKER_PREFIX = STRINGS.DIAGNOSTIC_BROKER_PREFIX
DIAGNOSTIC_LATENCY_BROKER_NONE = STRINGS.DIAGNOSTIC_BROKER_NONE

# Application/Broker split values — rendered only as the record itself
# carries them; a cross-clock ``None`` stays ناموجود (never estimated,
# never 0).
DIAGNOSTIC_LATENCY_APP_SIDE = (
    "Order {order} - \u0632\u0645\u0627\u0646 \u0633\u0645\u062a \u0628\u0631\u0646\u0627\u0645\u0647 (application_side): "
)
DIAGNOSTIC_LATENCY_APP_BEFORE = (
    "Order {order} - \u0628\u0631\u0646\u0627\u0645\u0647 \u0642\u0628\u0644 \u0627\u0632 Broker (application_before_broker): "
)
DIAGNOSTIC_LATENCY_APP_AFTER = (
    "Order {order} - \u0628\u0631\u0646\u0627\u0645\u0647 \u0628\u0639\u062f \u0627\u0632 Broker (application_after_broker): "
)
DIAGNOSTIC_LATENCY_APP_FIELDS = (
    (DIAGNOSTIC_LATENCY_APP_SIDE, "application_side_ns"),
    (DIAGNOSTIC_LATENCY_APP_BEFORE, "application_before_broker_ns"),
    (DIAGNOSTIC_LATENCY_APP_AFTER, "application_after_broker_ns"),
)


def _ns_to_ms_text(value):
    """
    Display-only conversion of a REAL measured ns value to ms text.

    Pure representation of a value the report already carries — no
    measurement, no rounding of the stored data, no derived arithmetic.
    Anything but a real number (``None``, bool, ...) yields ``None`` so the
    renderer can show the unavailable marker instead of a fabricated 0.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return f"{value / 1_000_000:.3f} ms"

def _epoch_to_local_datetime(value):
    """
    The local ``datetime`` of a REAL epoch-seconds feedback timestamp.

    Accepts int/float epoch seconds (the feedback path's ``time.time()``
    values). Anything else — ``None``, bool, non-numeric — returns ``None``
    (fail-closed: no fabricated time). The conversion is a pure
    representation of the received moment; no clock is read here.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value)
    except (OverflowError, OSError, ValueError):
        return None


def _result_status_label(result):
    """
    User-facing per-order verdict from the REAL ``OrderExecutionResult``.

    Fail-closed: ``success is True`` is the ONLY thing that may render as
    ``موفق``; an explicit preflight ``BLOCKED`` renders as ``مسدودشده``; any
    other outcome (failure, ``ERROR``, missing/unknown result) renders as
    ``ناموفق``. No per-order message/mode is ever shown raw.
    """
    if getattr(result, "success", None) is True:
        return RESULT_STATUS_SUCCESS
    if getattr(result, "mode", None) == "BLOCKED":
        return RESULT_STATUS_BLOCKED
    return RESULT_STATUS_FAILED


def _result_reason_for_status(status):
    """Fixed, user-facing reason string for one rendered status."""
    if status == RESULT_STATUS_SUCCESS:
        return RESULT_REASON_SUCCESS
    if status == RESULT_STATUS_BLOCKED:
        return RESULT_REASON_BLOCKED
    return RESULT_REASON_FAILED


def _account_record_or_none(account_store, account_id):
    """
    The existing ``AccountRecord`` for ``account_id``, or ``None``.

    ``AccountStore.get`` raises ``AccountStoreError`` for an unknown id and
    never guesses or substitutes one. Dispatch validation needs to tell an
    unknown account apart from a real one, so the store's own error is
    turned into the ``None`` here - and ONLY here. The account is still
    never invented or resolved from anything else.
    """
    try:
        return account_store.get(account_id)
    except ValueError:  # AccountStoreError — never guess an account
        return None


def _default_order_identity_resolver(
    account_store, broker_manager=None, account_id=None, broker_name=None
):
    """
    Lazily build the REAL broker ``InstrumentProvider`` that maps a
    TSETMC ``ins_code`` to a broker ``nscId``.

    The provider of the ACTIVE account's broker is used — the binding is
    never guessed and never fabricated. Nothing is built when no account
    is active (fail-closed: the caller treats it as "no identity"). The
    import is deferred so every page construction stays fully offline;
    the provider itself performs no network call here.
    """
    if account_store is None or broker_manager is None:
        return None
    if account_id is None or broker_name is None:
        active_id = account_store.active_account_id()
        if not active_id:
            return None
        try:
            record = account_store.get(active_id)
        except ValueError:  # AccountStoreError — never guess an identity
            return None
        account_id, broker_name = record.account_id, record.broker_name
    return broker_manager.get_instrument_provider_for_account(
        account_id, broker_name
    )


class _OrderIdentityWorker(QThread):
    """
    Resolves the broker ``nscId`` of one selected Instrument on a
    background thread, through the EXISTING read-only provider seam
    (``InstrumentProvider.get_nsc_id(ins_code)``).

    ``resolver_factory()`` must return the real provider (production) or
    a stub provider (tests). Plain ``run()`` thread: finishes by itself,
    fully deterministic. Anything unexpected — a failing factory, a
    missing resolver or a provider without a mapping — is reported as a
    failure; the string result is never fabricated in the UI.
    """

    # (ins_code, nsc_id) — the nsc_id string travels as ``object`` so it
    # is passed BY REFERENCE (no marshalling/copying of identity).
    identity_succeeded = Signal(object, str, object)
    # (ins_code, message) — resolution failed (no identity available).
    identity_failed = Signal(object, str, str)

    def __init__(self, ins_code, resolver_factory, parent=None, identity=None):
        super().__init__(parent)
        self.ins_code = ins_code
        self._resolver_factory = resolver_factory
        self.identity = identity

    def run(self):
        try:
            resolver = self._resolver_factory()
        except Exception as exc:  # noqa: BLE001 — failure must never crash the UI
            self.identity_failed.emit(self.identity, self.ins_code, str(exc))
            return
        if resolver is None:
            # Fail-closed: no real identity source (e.g. no active
            # account → no broker). Nothing may be guessed/emitted.
            self.identity_failed.emit(
                self.identity, self.ins_code, "no broker identity resolver available"
            )
            return
        try:
            nsc_id = resolver.get_nsc_id(self.ins_code)
        except Exception as exc:  # noqa: BLE001 — failure must never crash the UI
            self.identity_failed.emit(self.identity, self.ins_code, str(exc))
            return
        if not isinstance(nsc_id, str) or not nsc_id:
            nsc_id = None
        self.identity_succeeded.emit(self.identity, self.ins_code, nsc_id)


def _parse_exact_integral_text(text):
    """Parse an ASCII integer or integral decimal string without truncating."""
    text = text.strip()
    if not text or not text.isascii():
        return None
    whole, dot, fraction = text.partition(".")
    if dot:
        if not fraction or not fraction.isdigit():
            return None
        if any(char != "0" for char in fraction):
            return None
    if not whole or not whole.isdigit():
        return None
    return int(whole)


def _valid_limit(value, *, allow_zero=True):
    """An exact integer limit, or ``None`` (never rounded or guessed).

    The market layer normalizes the Loader's values to ``int``, but this
    guard accepts the raw forms too so a valid response is not rejected
    twice by two different validators: integral ``float`` values such as
    ``7630.0`` and integral-decimal strings such as ``"7630.0"`` are exact;
    fractional numbers, negatives, empty/unknown strings and booleans are
    invalid. Price limits must be strictly positive; quantity minimums may
    legitimately be zero.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        number = int(value)
    elif isinstance(value, str):
        number = _parse_exact_integral_text(value)
        if number is None:
            return None
    else:
        return None
    if number < 0 or (number == 0 and not allow_zero):
        return None
    return number


class _PriceLimitsWorker(QThread):
    """Fetch the TSETMC daily allowed price range off the GUI thread."""

    limits_succeeded = Signal(object, str, object)
    limits_failed = Signal(object, str, str)

    def __init__(self, ins_code, limits_factory, request_id, parent=None):
        super().__init__(parent)
        self.ins_code = ins_code
        self._limits_factory = limits_factory
        self.request_id = request_id

    def run(self):
        try:
            client = self._limits_factory()
            if client is None:
                raise RuntimeError("price limits client is unavailable")
            limits = client.get_price_limits(self.ins_code)
        except Exception as exc:  # noqa: BLE001 — failure must never crash the UI
            self.limits_failed.emit(self.request_id, self.ins_code, str(exc))
            return
        self.limits_succeeded.emit(self.request_id, self.ins_code, limits)


class _QuantityLimitsWorker(QThread):
    """Fetch account-scoped BrokerInstrument quantity limits off the GUI thread."""

    limits_succeeded = Signal(object, str, object)
    limits_failed = Signal(object, str, str)

    def __init__(
        self, ins_code, provider_factory, request_id, parent=None
    ):
        super().__init__(parent)
        self.ins_code = ins_code
        self._provider_factory = provider_factory
        self.request_id = request_id

    def run(self):
        try:
            provider = self._provider_factory()
            if provider is None:
                raise RuntimeError("account instrument provider is unavailable")
            result = provider.get_instrument(self.ins_code)
        except Exception as exc:  # noqa: BLE001 — failure must never crash the UI
            self.limits_failed.emit(self.request_id, self.ins_code, str(exc))
            return
        if isinstance(result, (tuple, list)) and len(result) == 2:
            broker_instrument = result[1]
        else:
            broker_instrument = result
        if broker_instrument is None:
            self.limits_failed.emit(
                self.request_id, self.ins_code, "broker instrument is unavailable"
            )
            return
        self.limits_succeeded.emit(
            self.request_id, self.ins_code, broker_instrument
        )


class _BuyPreviewWorker(QThread):
    """Read-only Agaah buy preview; all service/network calls run here."""

    succeeded = Signal(object, object, object)
    failed = Signal(object, str)

    def __init__(self, request_id, snapshot, calculate, parent=None):
        super().__init__(parent)
        self.request_id = request_id
        self.snapshot = snapshot
        self._calculate = calculate

    def run(self):
        try:
            result = self._calculate(self.snapshot)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(self.request_id, str(exc))
            return
        self.succeeded.emit(self.request_id, self.snapshot, result)


class OrderConfigurationPage(QWidget):
    """
    Order Configuration page (form and state only — no execution).
    """

    def __init__(
        self,
        account_store,
        config=None,
        order_queue=None,
        parent=None,
    ):
        super().__init__(parent)

        self.store = account_store
        self.config = config if config is not None else OrderConfiguration()
        self.symbol_text = ""

        # --- UI-3.2A: real symbol search state -------------------------
        self._resolver_factory = None  # set via set_resolver_factory()
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(SYMBOL_SEARCH_DEBOUNCE_MS)
        self._debounce_timer.timeout.connect(self._start_symbol_search)
        self._search_sequence = 0          # generation of the latest search
        self._active_search_threads = []   # live worker threads (tests wait on them)
        self._latest_results = []          # the real resolver result objects
        self._updating_symbol_suggestions = False
        self._searching = False
        self._search_thread = None
        self._search_worker = None
        self._resolve_thread = None
        self._resolve_worker = None

        # --- UI-3.2B: real trading-state display state -----------------
        self._trading_state_factory = None  # set via set_trading_state_query_factory()
        self._trading_state_thread = None
        self._trading_state_worker = None
        self._trading_state_instrument = None  # ins_code the shown state belongs to
        self._trading_state_account_scope = None
        self._trading_state_shown = None       # last TradingState actually rendered

        # --- UI-4: queue + order-identity state ------------------------
        # The EXISTING core OrderQueue is injected by tests (constructor
        # seams, like the resolver/query factories); production keeps
        # ``None`` and the page lazily builds the real queue on the FIRST
        # real Add-to-Queue action (never at construction — offline).
        self._injected_order_queue = order_queue
        self._default_queue = None
        # The nsc_id resolved for the CURRENT (ins_code, broker_name)
        # pair — captured OFF the GUI thread at selection time, so the
        # Add-to-Queue action itself never touches the network.
        self._order_identity_factory = None  # set via set_order_identity_factory()
        self._order_identity_thread = None
        self._order_identity_worker = None
        self._order_identity_instrument = None  # ins_code the nsc_id belongs to
        self._order_identity_broker = None      # broker the nsc_id belongs to
        self._order_identity_account = None
        self._order_identity_scope = None
        self._order_nsc_id = None               # the resolved broker nscId

        # --- Limit arrows: TSETMC price bounds + broker quantity bounds ---
        self._price_limits_factory = None
        self._price_limits_thread = None
        self._price_limits_worker = None
        self._price_limits_request_id = 0
        self._price_limits_scope = None
        self._quantity_limits_factory = None
        self._quantity_limits_thread = None
        self._quantity_limits_worker = None
        self._quantity_limits_request_id = 0
        self._quantity_limits_scope = None
        self._buy_preview_factory = None
        self._buy_preview_request_id = 0
        self._buy_preview_worker = None
        self._buy_preview_thread = None
        self._buy_preview_dialog = None
        self._buy_preview_result = None
        self._auto_amount_request_id = 0
        self._auto_amount_worker = None
        self._auto_amount_thread = None
        self._auto_amount_timer = QTimer(self)
        self._auto_amount_timer.setSingleShot(True)
        self._auto_amount_timer.setInterval(250)
        self._auto_amount_timer.timeout.connect(self._start_auto_amount)

        # ---------------------------------------------
        # UI-9 Task 2 — page shell: scroll + two columns + bottom tables
        # ---------------------------------------------
        #
        # STRUCTURE CONTRACT (do not break):
        #   * ``OrderConfigurationPage`` stays a plain QWidget and the very
        #     same object is still what MainWindow adds to ``content_area``
        #     (constraint C4: content_area.count() must stay 4).
        #   * The scroll area is INNER: the page root keeps a bare
        #     QVBoxLayout holding exactly one QScrollArea.
        #   * Every spacing/margin value below comes from ui/theme.py
        #     tokens — there are no magic numbers in this layout.
        _pad = SPACING["md"]
        _gap = SPACING["lg"]

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # The inner scroll area. setWidgetResizable(True) makes the
        # content track the viewport width, so the two columns always
        # fill the page instead of collapsing to their minimum width.
        self._page_scroll = QScrollArea(self)
        self._page_scroll.setWidgetResizable(True)
        self._page_scroll.setFrameShape(QFrame.NoFrame)
        self._page_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAsNeeded
        )
        root_layout.addWidget(self._page_scroll)

        page_content = QWidget()
        page_content.setObjectName("ui9PageContent")
        content_layout = QVBoxLayout(page_content)
        content_layout.setContentsMargins(_pad, _pad, _pad, _pad)
        content_layout.setSpacing(_gap)
        self._page_scroll.setWidget(page_content)

        # --- Top row: two EQUAL columns ---------------------------
        # Left column  = order information (account, order form,
        #               symbol info, amounts)
        # Right column = scheduling (schedule + countdown) and the
        #               queue status line
        top_row = QHBoxLayout()
        top_row.setSpacing(_gap)

        order_column = QWidget()
        order_column.setObjectName("ui9OrderColumn")
        order_column_layout = QVBoxLayout(order_column)
        order_column_layout.setContentsMargins(0, 0, 0, 0)
        order_column_layout.setSpacing(_gap)

        schedule_column = QWidget()
        schedule_column.setObjectName("ui9ScheduleColumn")
        schedule_column_layout = QVBoxLayout(schedule_column)
        schedule_column_layout.setContentsMargins(0, 0, 0, 0)
        schedule_column_layout.setSpacing(_gap)

        # A true 50/50 split. Equal stretch alone is NOT enough: the order
        # column has a much larger minimum width (636px vs 582px measured),
        # so the layout would keep it 52px wider. The Ignored horizontal
        # policy tells the layout to ignore those differing size hints and
        # divide the row evenly, which is what "two equal columns" means.
        for _column in (order_column, schedule_column):
            _column.setSizePolicy(
                QSizePolicy.Ignored, QSizePolicy.Preferred
            )

        # Equal stretch on both columns -> a true 50/50 split.
        top_row.addWidget(order_column, 1)
        top_row.addWidget(schedule_column, 1)
        content_layout.addLayout(top_row)

        # --- Bottom area: the tables ------------------------------
        # Order Queue and Test Results side by side, then Order Log
        # full width beneath them, then the Diagnostic section last.
        tables_row = QHBoxLayout()
        tables_row.setSpacing(_gap)

        # ---------------------------------------------
        # Active account (from the existing UI-2.1 store)
        # ---------------------------------------------

        account_group = QGroupBox(STRINGS.GROUP_ACTIVE_ACCOUNT, self)
        account_group.setObjectName("activeAccountGroup")
        self.active_account_group = account_group
        account_layout = QHBoxLayout(account_group)
        account_layout.setContentsMargins(SPACING["md"], SPACING["sm"], SPACING["md"], SPACING["sm"])
        account_layout.setSpacing(SPACING["sm"])
        self.active_account_label = QLabel(self._active_account_text(), account_group)
        self.active_account_label.setWordWrap(False)
        self.active_account_label.setMinimumHeight(self.active_account_label.sizeHint().height())
        self.active_account_label.setMinimumWidth(0)
        # Ignored lets the trailing stretch consume the entire row on some
        # Qt styles, leaving this label with width 0. Expanding keeps the
        # text visible while the fixed group height prevents vertical growth.
        self.active_account_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        account_layout.addWidget(self.active_account_label, 1)
        account_group.setMinimumHeight(account_group.sizeHint().height())
        account_group.setMaximumHeight(account_group.sizeHint().height())
        # UI-9 Task 2: the order-information column (left of the two).
        order_column_layout.addWidget(account_group)

        # ---------------------------------------------
        # Order Configuration group
        # ---------------------------------------------

        form_group = QGroupBox(STRINGS.GROUP_ORDER_CONFIGURATION, self)
        # The order panel is the only widget carrying the side-keyed halo;
        # the object name scopes the local stylesheet below to this panel.
        form_group.setObjectName("orderConfigPanel")
        self.form_group = form_group
        self._order_panel_glow = None
        form_grid = QGridLayout(form_group)

        # --- Symbol ---------------------------------------------
        form_grid.addWidget(QLabel(STRINGS.LABEL_SYMBOL, form_group), 0, 0)
        self.symbol_input = QComboBox(form_group)
        self.symbol_input.setObjectName("symbolInput")
        self.symbol_input.setEditable(True)
        # Reuse the shared dark-theme chevron asset/property from
        # ui/theme.py — no page-local icon path is introduced.
        self.symbol_input.setProperty("chevron", True)
        self.symbol_input.lineEdit().setPlaceholderText(STRINGS.PLACEHOLDER_SYMBOL)
        self.symbol_input.lineEdit().textChanged.connect(self._on_symbol_edited)
        self.symbol_input.lineEdit().textChanged.connect(self._invalidate_buy_preview)
        self.symbol_input.lineEdit().textChanged.connect(self._invalidate_auto_amount)
        # Suggestions are selected through the combo's own popup; the
        # activated signal fires for mouse and keyboard selection.
        self.symbol_input.activated.connect(self._on_symbol_activated)
        symbol_field = QWidget(form_group)
        symbol_field.setObjectName("symbolNameField")
        symbol_field.setAttribute(Qt.WA_TranslucentBackground, True)
        symbol_field.setStyleSheet(
            "QWidget#symbolNameField { background-color: transparent; border: 0px; }"
        )
        symbol_field_layout = QVBoxLayout(symbol_field)
        symbol_field_layout.setContentsMargins(0, 0, 0, 0)
        symbol_field_layout.setSpacing(SPACING["xs"])
        symbol_field_layout.addWidget(self.symbol_input)
        self.symbol_name_label = QLabel("-", form_group)
        self.symbol_name_label.setObjectName("selectedSymbolName")
        self.symbol_name_label.setStyleSheet(
            "QLabel#selectedSymbolName { background-color: transparent; border: 0px; padding: 0px; }"
        )
        self.symbol_name_label.setContentsMargins(0, 0, 0, 0)
        self.symbol_name_label.setWordWrap(False)
        self.symbol_name_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        symbol_field_layout.addWidget(self.symbol_name_label)
        form_grid.addWidget(symbol_field, 0, 1)

        # --- Trading-state icon next to the selected symbol ---
        self.trading_state_icon = QLabel(form_group)
        self.trading_state_icon.setObjectName("tradingStateIcon")
        self.trading_state_icon.setFixedSize(
            _TRADING_STATUS_ICON_SIZE, _TRADING_STATUS_ICON_SIZE
        )
        self.trading_state_icon.setAlignment(Qt.AlignCenter)
        self.trading_state_icon.hide()
        self.market_status_icon = self.trading_state_icon
        form_grid.addWidget(self.trading_state_icon, 0, 2)

        # --- Search state (suggestions live in the combo popup) ---
        self.search_status_label = QLabel(SEARCH_STATE_IDLE, form_group)
        form_grid.addWidget(self.search_status_label, 0, 3)

        # --- Side ---------------------------------------------
        form_grid.addWidget(QLabel(STRINGS.LABEL_SIDE, form_group), 1, 0)
        side_row = QWidget(form_group)
        side_layout = QHBoxLayout(side_row)
        side_layout.setContentsMargins(0, 0, 0, 0)
        self.side_buttons = {}
        for side_value, label in SIDE_LABELS:
            button = QRadioButton(label, side_row)
            button.clicked.connect(
                lambda checked=False, s=side_value: self._on_side_selected(s)
            )
            # UI-10: the BUY/SELL text is colour-coded through the theme —
            # the success token for BUY, the danger token for SELL. Pure
            # presentation: keys, labels and the click behaviour are
            # unchanged.
            button.setProperty(
                "variant", "buy" if side_value == BUY else "sell"
            )
            self.side_buttons[side_value] = button
            side_layout.addWidget(button)
        side_layout.addStretch(1)
        form_grid.addWidget(side_row, 1, 1)
        # UI-10: BUY is the preselected side. The state goes through the
        # existing config setter (never a direct attribute write), and the
        # radio reflects the same default, so config.side == BUY right
        # after construction.
        self.side_buttons[BUY].setChecked(True)
        self.config.set_side(BUY)
        # BUY is the default side, so the panel starts with its green halo.
        self._apply_order_panel_halo(BUY)
        self.calculator_button = QPushButton(form_group)
        self.calculator_button.setObjectName("buyPreviewCalculatorButton")
        self.calculator_button.setIcon(QIcon(str(_ICONS_DIR / "calculator.svg")))
        self.calculator_button.setIconSize(QSize(SPACING["xl"], SPACING["xl"]))
        self.calculator_button.setFixedSize(GEOMETRY["controlHeight"], GEOMETRY["controlHeight"])
        self.calculator_button.setToolTip("محاسبه پیش‌نمایش خرید آگاه")
        self.calculator_button.clicked.connect(self._open_buy_preview)
        form_grid.addWidget(self.calculator_button, 1, 2)

        # --- Price ---------------------------------------------
        form_grid.addWidget(QLabel(STRINGS.LABEL_PRICE, form_group), 2, 0)
        self.price_input = QLineEdit(form_group)
        self.price_input.setPlaceholderText(STRINGS.PLACEHOLDER_PRICE)
        self.price_input.editingFinished.connect(self._on_price_changed)
        self.price_input.textChanged.connect(self._invalidate_buy_preview)
        self.price_input.textChanged.connect(self._schedule_auto_amount)
        form_grid.addWidget(self.price_input, 2, 1)

        price_limit_row = QWidget(form_group)
        price_limit_layout = QHBoxLayout(price_limit_row)
        price_limit_layout.setContentsMargins(0, 0, 0, 0)
        price_limit_layout.setSpacing(SPACING["xs"])
        self.price_max_button = self._make_limit_arrow(
            _ARROW_UP_ICON,
            STRINGS.TOOLTIP_PRICE_MAX,
            "priceMaxButton",
        )
        self.price_max_button.clicked.connect(
            lambda checked=False: self._request_price_limit(PRICE_LIMIT_MAX)
        )
        self.price_min_button = self._make_limit_arrow(
            _ARROW_DOWN_ICON,
            STRINGS.TOOLTIP_PRICE_MIN,
            "priceMinButton",
        )
        self.price_min_button.clicked.connect(
            lambda checked=False: self._request_price_limit(PRICE_LIMIT_MIN)
        )
        price_limit_layout.addWidget(self.price_max_button)
        price_limit_layout.addWidget(self.price_min_button)
        form_grid.addWidget(price_limit_row, 2, 2)

        # --- Quantity ---------------------------------------------
        form_grid.addWidget(QLabel(STRINGS.LABEL_QUANTITY, form_group), 3, 0)
        self.quantity_input = QLineEdit(form_group)
        self.quantity_input.setPlaceholderText(STRINGS.PLACEHOLDER_QUANTITY)
        self.quantity_input.editingFinished.connect(self._on_quantity_changed)
        self.quantity_input.textChanged.connect(self._schedule_auto_amount)
        form_grid.addWidget(self.quantity_input, 3, 1)

        quantity_limit_row = QWidget(form_group)
        quantity_limit_layout = QHBoxLayout(quantity_limit_row)
        quantity_limit_layout.setContentsMargins(0, 0, 0, 0)
        quantity_limit_layout.setSpacing(SPACING["xs"])
        self.quantity_max_button = self._make_limit_arrow(
            _ARROW_UP_ICON,
            STRINGS.TOOLTIP_QUANTITY_MAX,
            "quantityMaxButton",
        )
        self.quantity_max_button.clicked.connect(
            lambda checked=False: self._request_quantity_limit(PRICE_LIMIT_MAX)
        )
        self.quantity_min_button = self._make_limit_arrow(
            _ARROW_DOWN_ICON,
            STRINGS.TOOLTIP_QUANTITY_MIN,
            "quantityMinButton",
        )
        self.quantity_min_button.clicked.connect(
            lambda checked=False: self._request_quantity_limit(PRICE_LIMIT_MIN)
        )
        quantity_limit_layout.addWidget(self.quantity_max_button)
        quantity_limit_layout.addWidget(self.quantity_min_button)
        form_grid.addWidget(quantity_limit_row, 3, 2)

        # --- Add to Queue (UI-4) --------------------------------
        # Prepares ONE real Order (via the resolved nsc_id + the active
        # account binding) and appends it to the EXISTING OrderQueue.
        self.add_to_queue_button = QPushButton(STRINGS.BUTTON_ADD_TO_QUEUE, form_group)
        # UI-9 Task 2 — visual variant only; text, signal and enablement
        # logic are untouched.
        self.add_to_queue_button.setProperty("variant", "primary")
        self.add_to_queue_button.clicked.connect(self._on_add_to_queue)
        form_grid.addWidget(self.add_to_queue_button, 4, 0, 1, 2)

        # --- Test Button (UI-5 Task 1) ------------------------------
        # UI-only toggle: OFF -> "Test", ON -> "Test (On)".
        # No execution, no dispatch, no broker/network activity.
        # Starts DISABLED: at construction there is nothing queued yet
        # (the lazy core.queue import must never run at construction).
        # The enable/disable refresh runs only on real UI flows.
        self.test_button = QPushButton(STRINGS.BUTTON_TEST, form_group)
        self.test_button.setCheckable(True)
        self.test_button.setEnabled(False)
        self.test_button.clicked.connect(self._on_test_toggled)
        form_grid.addWidget(self.test_button, 4, 2)

        # --- Inline validation error (UI-9.4) ------------------------
        # ONE message line for the whole order form, directly under it.
        # It replaces the three former blocking QMessageBox pop-ups
        # (side / price / quantity) with an in-place message, so a bad
        # value no longer opens a modal window. Its colour comes from
        # the ui/theme.py danger role (the "role" property below) — no
        # colour or spacing is invented here. It is empty and hidden
        # while there is nothing to report, so the normal layout is
        # unchanged.
        self.validation_error_label = QLabel("", form_group)
        self.validation_error_label.setProperty("role", "danger")
        self.validation_error_label.setWordWrap(True)
        self.validation_error_label.setVisible(False)
        form_grid.addWidget(self.validation_error_label, 5, 0, 1, 4)

        # Internal Test Mode state — UI-local only, initialized OFF.
        self._test_mode = False

        # --- UI-5 Task 2: dry-run execution wiring (offline until used) ---
        # The Test action runs its pending entries through the EXISTING
        # execution chain via the runner seam below. The runner is injected
        # like every other lazy seam (resolver / trading-state / queue): no
        # runner is built here, so construction and plain toggling stay
        # fully offline and never import Core/Broker modules. Production
        # MainWindow wires a lazy real runner; tests inject a fake one.
        self._test_runner_factory = None  # set via set_test_runner_factory()
        self._test_runner_instance = None
        # Outcome of the last Test action (Task 3 consumes these).
        self._last_test_run = None    # (plan, execution_id, result)
        self._last_test_entries = None
        self._last_test_error = None
        # UI-5 Task 3 — the per-order results of the last successful Test
        # run, aligned 1:1 to ``_last_test_entries`` (queue order). ``None``
        # when the wired runner exposed no per-order results (display then
        # fails closed per row — never fabricated).
        self._last_order_results = None
        # UI-6 Task 3: THIS run's EXISTING Block 8 report (the runner's
        # own ``last_report`` — taken only from the completed run; cleared
        # when an issue attempt fails so a previous run's timings are
        # never presented as the new run's).
        self._last_latency_report = None
        # UI-layer symbol map for one queued Order: captured at the exact
        # Add-to-Queue action from the selected REAL Instrument, keyed by the
        # order object's identity. ``Order`` has no symbol field and nscId /
        # tseId must never reach a result row, so the symbol the user picked
        # is kept here in the UI layer only.
        self._order_symbols = {}
        self._order_authorizer_factory = None

        # --- UI-5 Task 4 Stage 3 Task 3: matching-engine (trading core)
        # registration feedback state. The page binds to the EXISTING
        # order-feedback path ONLY through the injected factory seam below
        # (never at construction — offline contracts preserved; no feedback
        # module is ever imported or named here).
        self._feedback_binder_factory = None  # set via set_feedback_binder_factory()
        # Block 9 Task 9B: bindings are per account. The page connects to the
        # feedback runtime of each exact (account_id, broker_name) it sends
        # for; an event delivered on one account's runtime can only ever
        # resolve a row of that same account.
        self._feedback_binders = {}
        # The most recently bound runtime (single-account compatibility).
        self._feedback_binder = None
        # decisionId correlation (the Stage 1 binding, filled at append time):
        # the exact sent Order object (by identity, like _order_symbols) ->
        # its real decisionId, and the ACCOUNT-SCOPED reverse map
        # ``(account_id, broker_name, decision_id) -> order``. Pure routing
        # state — never rendered, never displayed.
        self._decision_id_by_order = {}
        self._order_by_decision_key = {}
        # Stage 3 Task 4 — the id() identities of the orders a REAL send
        # produced and correlated (mirrors the append loop). A queue-status
        # event is only ever routed to an order this set holds: an order
        # the page's own send path produced, never an invented one.
        self._queued_order_ids = set()
        # Stage 3 Task 4 — the queue-status DISPLAY state of the page's UI
        # layer, keyed by the exact sent order's ``id(order)`` identity.
        # The value is ONLY what the EXISTING Stage 2 feedback signal
        # delivered (verbatim, as display text). It is UI-layer state:
        # ``OrderLog`` stays append-only with its Task 3 contract intact
        # and the model never stores or invents a queue value. A cell whose
        # order holds no entry renders ``—`` (fail-closed).
        self._queue_status_text_by_order = {}

        # --- UI-6 Task 1: diagnostic-section visibility state ---------
        # The single display-boundary flag of this page. NORMAL (the
        # application default) keeps the section hidden; it may be shown
        # only when the application mode is DIAGNOSTIC (MainWindow calls
        # ``apply_mode`` on this page on every mode change).
        self._diagnostic_section_visible = False

        # --- UI-7 Task 1: clock + schedule state ------------------------
        # The clock service and its worker are created lazily so that
        # constructing this page stays offline (no ``requests``, no market
        # or core import until a clock refresh or an Apply actually runs).
        self._clock_service = None
        self._clock_service_factory = None
        self._clock_transport = None
        self._clock_worker = None
        self._clock_thread = None
        self._clock_status = None
        self._pending_schedule = None
        self._schedule_parsed = None
        self._schedule_timing = None
        self._schedule_times = ()
        self._schedule_assessment = None

        # --- UI-7 Task 2: schedule lifecycle + countdown -----------------
        # Locked time base for the active schedule (set at Apply time).
        # Once locked, subsequent syncs, system-clock steps and clock
        # service rebuilds do NOT affect the active schedule: the anchors
        # captured here are the ones the countdown advances from.
        self._locked_clock_source: Optional[ClockSource] = None
        self._locked_applied_offset: Optional[timedelta] = None
        self._locked_uncertainty: Optional[timedelta] = None
        self._locked_market_time: Optional[datetime] = None
        self._locked_sync_time: Optional[datetime] = None
        self._locked_base_time: Optional[datetime] = None
        self._locked_mono_anchor: Optional[float] = None
        self._locked_last_now: Optional[datetime] = None

        # Schedule state machine (see ui.schedule_settings for labels)
        self._schedule_state: str = SCHEDULE_STATE_CONFIG
        self._countdown_timer: Optional[QTimer] = None
        # --- UI-7 Task 3: periodic dispatch -------------------------------
        # The frozen send set + its destinations, fixed at Apply. Each due
        # moment the dispatcher fans one send out per destination broker.
        self._dispatcher: Optional[PeriodicScheduleDispatcher] = None
        self._dispatch_interval_ms: Optional[float] = None
        self._pending_dispatch_interval_ms: Optional[float] = None
        self._dispatch_cursor: int = 0
        self._dispatch_turns = ()
        self._dispatch_turns_lock = threading.Lock()
        # The ms-cadence dispatch loop runs on this worker thread, so no
        # send and no wait for a broker answer ever blocks the UI thread.
        self._dispatch_thread = None
        self._dispatch_stop_event = None
        # UI-7 Task 2: a LIGHT display-only timer that re-renders the sync
        # freshness line. It never syncs, never touches the locked time
        # base and never moves the countdown — see
        # ``_refresh_sync_freshness_display``.
        self._sync_freshness_timer: Optional[QTimer] = None
        self._countdown_target: Optional[datetime] = None  # next run moment
        # The START_NOW state is a one-shot notice: shown once for a past
        # start, never re-entered by a later tick.
        self._start_now_shown: bool = False
        # While True every order/queue/schedule control of this page is
        # locked; only the Stop action (the Apply button, relabelled) is
        # active.
        self._schedule_locked: bool = False

        # Startup sync is triggered by MainWindow AFTER the window is
        # shown and the event loop is running — never by this page's own
        # visibility, and never during construction (offline contract).
        self._startup_sync_done: bool = False

        order_column_layout.addWidget(form_group)

        # ---------------------------------------------
        # Symbol information / status display area
        # ---------------------------------------------

        self.symbol_status_label = QLabel(
            f"{STRINGS.LABEL_SYMBOL_STATUS_PREFIX}{STRINGS.SYMBOL_STATUS_NOT_AVAILABLE_DISPLAY}", self
        )
        self.trading_state_label = QLabel("-", self)

        # ---------------------------------------------
        # Amounts group
        # ---------------------------------------------

        amounts_group = QGroupBox(STRINGS.GROUP_AMOUNTS, self)
        amounts_form = QFormLayout(amounts_group)

        self.base_amount_label = QLabel("-", amounts_group)
        self.fee_label = QLabel(STRINGS.VALUE_NOT_AVAILABLE, amounts_group)
        self.final_amount_label = QLabel(STRINGS.VALUE_NOT_AVAILABLE, amounts_group)

        amounts_form.addRow(STRINGS.LABEL_BASE_AMOUNT, self.base_amount_label)
        amounts_form.addRow(STRINGS.LABEL_FEE, self.fee_label)
        amounts_form.addRow(STRINGS.LABEL_FINAL_AMOUNT, self.final_amount_label)
        self.amount_warning_label = QLabel("", amounts_group)
        self.amount_warning_label.setProperty("role", "danger")
        self.amount_warning_label.setStyleSheet(f"color: {PALETTE['danger']};")
        self.amount_warning_label.setWordWrap(True)
        amounts_form.addRow(self.amount_warning_label)

        order_column_layout.addWidget(amounts_group)

        # ---------------------------------------------
        # Order Queue display (UI-4)
        # ---------------------------------------------

        queue_group = QGroupBox(STRINGS.GROUP_ORDER_QUEUE, self)
        queue_layout = QVBoxLayout(queue_group)

        self.queue_status_label = QLabel(QUEUE_STATUS_EMPTY, self)
        # UI-9 Task 2b: the status label now lives in its OWN bordered group
        # box ("Queue Status") placed in the scheduling column, matching the
        # mockup. The group box is created and added to the column in the
        # final assembly, so it renders BELOW the Schedule group. The label
        # attribute, its word-wrap, its muted property and every setText()
        # call site are unchanged.

        # Visible pending-orders list — rendered ONLY from the existing
        # ``OrderQueue.list_pending()`` at refresh time; left untouched
        # at construction so no queue/core import ever runs offline.
        self.queue_list = QListWidget(queue_group)
        self.queue_list.setMaximumHeight(140)
        self.queue_list.setUniformItemSizes(True)
        self.queue_list.setSpacing(SPACING["xs"])
        queue_layout.addWidget(self.queue_list)

        self.queue_count_label = QLabel(STRINGS.QUEUE_COUNT_LABEL, queue_group)
        queue_layout.addWidget(self.queue_count_label)

        # UI-9 Task 2: the queue STATUS line moves to the scheduling
        # column (per the 2.2 layout table); the queue GROUP itself goes to
        # the bottom tables row. queue_list stays a direct child of this
        # group box — no container is inserted between a list and its
        # group (C5). The status label itself is appended to the scheduling
        # column in the final assembly, so it renders BELOW the schedule.

        # ---------------------------------------------
        # Test Results display (UI-5 Task 3)
        # ---------------------------------------------

        results_group = QGroupBox(STRINGS.GROUP_TEST_RESULTS, self)
        results_layout = QVBoxLayout(results_group)

        self.result_status_label = QLabel(RESULT_EMPTY_STATE, results_group)
        results_layout.addWidget(self.result_status_label)

        # Visible per-order result rows — rendered ONLY by the single final
        # refresh of the last Test action (one refresh per run; a later run
        # fully replaces the previous rows; no result history is kept).
        self.result_list = QListWidget(results_group)
        self.result_list.setMaximumHeight(140)
        self.result_list.setUniformItemSizes(True)
        self.result_list.setSpacing(SPACING["xs"])
        results_layout.addWidget(self.result_list)

        # UI-9 Task 2: Order Queue and Test Results side by side.
        tables_row.addWidget(queue_group, 1)
        tables_row.addWidget(results_group, 1)

        # ---------------------------------------------
        # Schedule configuration (UI-7 Task 1)
        # ---------------------------------------------
        # Start Time / End Time / Interval inputs plus the Apply Schedule
        # action, the clock-source status line, and the confirmation
        # summary. Nothing here starts a schedule, counts down, or sends an
        # order: the countdown lifecycle is UI-7 Task 2 and wiring due
        # times to the send path is UI-7 Task 3.

        self.schedule_group = QGroupBox(SCHEDULE_GROUP_TITLE, self)
        schedule_form = QFormLayout(self.schedule_group)

        # UI-10: this row is the LIVE MARKET CLOCK. The attribute keeps its
        # UI-7 name (C7: nothing renamed); it now renders the current
        # market-synced Tehran time (HH:MM:SS, never milliseconds) instead
        # of the timezone note. The timezone itself stays visible in the
        # schedule summary (NOTE_TIMEZONE) and in the clock status row.
        self.schedule_timezone_label = QLabel("", self.schedule_group)
        schedule_form.addRow(STRINGS.LABEL_CLOCK, self.schedule_timezone_label)

        self.schedule_start_input = QLineEdit(self.schedule_group)
        self.schedule_start_input.setPlaceholderText(TIME_INPUT_PLACEHOLDER)
        # UI-10: pre-filled defaults — real field values, accepted by the
        # existing validators unchanged (08:44:58 < 08:45:05, interval is a
        # positive whole number of seconds; 0 stays illegal).
        self.schedule_start_input.setText("08:44:58")
        schedule_form.addRow(START_INPUT_LABEL, self.schedule_start_input)

        self.schedule_end_input = QLineEdit(self.schedule_group)
        self.schedule_end_input.setPlaceholderText(TIME_INPUT_PLACEHOLDER)
        self.schedule_end_input.setText("08:45:05")
        schedule_form.addRow(END_INPUT_LABEL, self.schedule_end_input)

        self.schedule_interval_input = QLineEdit(self.schedule_group)
        self.schedule_interval_input.setPlaceholderText(INTERVAL_INPUT_PLACEHOLDER)
        # UI-10 default is 1 — the smallest LEGAL value. The Product
        # Owner's "0" is forbidden by _parse_interval (a zero gap would
        # degenerate the schedule into a burst) and that rule is NOT
        # changed here. Burst cadence is the dispatch interval below.
        self.schedule_interval_input.setText("1")
        schedule_form.addRow(INTERVAL_INPUT_LABEL, self.schedule_interval_input)

        # UI-7 Task 3: the DISPATCH interval, in MILLISECONDS. The unit is
        # explicit in the label and the placeholder so a millisecond value
        # can never be read as a second value.
        self.dispatch_interval_input = QLineEdit(self.schedule_group)
        self.dispatch_interval_input.setPlaceholderText(
            EXECUTION_INTERVAL_PLACEHOLDER
        )
        # UI-10 default: the "send like a burst every 100 ms" cadence the
        # Product Owner asked for is EXACTLY this existing field.
        self.dispatch_interval_input.setText("100")
        schedule_form.addRow(
            EXECUTION_INTERVAL_LABEL, self.dispatch_interval_input
        )

        schedule_buttons = QWidget(self.schedule_group)
        schedule_buttons_layout = QHBoxLayout(schedule_buttons)
        schedule_buttons_layout.setContentsMargins(0, 0, 0, 0)
        schedule_buttons_layout.setSpacing(SPACING["sm"])

        # UI-7 Task 2: ONE button. Before a schedule is accepted it is
        # "Apply Schedule"; after acceptance it becomes "Stop Schedule"
        # and is the ONLY enabled button of the order/queue/schedule set.
        self.apply_schedule_button = QPushButton(
            APPLY_BUTTON_LABEL, schedule_buttons
        )
        # UI-9 Task 2 — the Apply/Stop button is the scheduling column's
        # main action, so it carries the "primary" theme variant (blue).
        # The Apply->Stop label swap itself is existing UI-7 logic and is
        # NOT changed here.
        self.apply_schedule_button.setProperty("variant", "primary")
        self.apply_schedule_button.clicked.connect(
            self._on_schedule_button_clicked
        )
        schedule_buttons_layout.addWidget(self.apply_schedule_button)

        self.refresh_clock_button = QPushButton(STRINGS.BUTTON_REFRESH_CLOCK, schedule_buttons)
        self.refresh_clock_button.clicked.connect(self._on_refresh_clock)
        schedule_buttons_layout.addWidget(self.refresh_clock_button)

        # UI-7 Task 2 — manual sync button
        self.sync_clock_button = QPushButton(SYNC_BUTTON_LABEL, schedule_buttons)
        self.sync_clock_button.clicked.connect(self._on_sync_clock)
        self.sync_clock_button.setToolTip(STRINGS.TOOLTIP_FORCE_SYNC)
        schedule_buttons_layout.addWidget(self.sync_clock_button)

        schedule_form.addRow(schedule_buttons)

        self.clock_status_label = QLabel(SCHEDULE_UNAVAILABLE, self.schedule_group)
        self.clock_status_label.setWordWrap(True)
        # UI-10: relabelled «وضعیت ساعت» so the form does not carry two rows
        # called «ساعت». Attribute, value and behaviour are unchanged.
        schedule_form.addRow(STRINGS.LABEL_CLOCK_STATUS, self.clock_status_label)

        # UI-10: one initial render so the clock row shows a real time the
        # moment the page is built (the 1-second display timer starts later,
        # with the sync-freshness display after the first sync attempt).
        self._refresh_market_clock_row()

        # UI-7 Task 2 — the RESULT of the last sync: source, estimated
        # offset, uncertainty band and freshness. Never millisecond-precise.
        self.sync_status_label = QLabel(SYNC_STATE_NEVER, self.schedule_group)
        self.sync_status_label.setWordWrap(True)
        schedule_form.addRow(STRINGS.LABEL_SYNC, self.sync_status_label)

        # UI-7 Task 2 — lifecycle state (configuring / waiting / counting /
        # starting once / stopped / expired).
        self.schedule_state_label = QLabel(
            SCHEDULE_STATE_CONFIG, self.schedule_group
        )
        self.schedule_state_label.setWordWrap(True)
        # UI-9 Task 2 — the scheduling state reads as a prominent status.
        self.schedule_state_label.setStyleSheet(
            f"font-size: {GEOMETRY['statusFontPt']}pt;"
            f" font-weight: bold; color: {PALETTE['accent']};"
        )
        schedule_form.addRow(STRINGS.LABEL_STATE, self.schedule_state_label)

        # UI-7 Task 2 — countdown display for active schedule
        self.countdown_label = QLabel(SCHEDULE_UNAVAILABLE, self.schedule_group)
        self.countdown_label.setWordWrap(True)
        # UI-9 Task 2 — the countdown must be visually prominent: larger
        # and in the accent colour, with a monospace face so the ticking
        # digits stay aligned. Colours/sizes come from ui/theme.py tokens.
        self.countdown_label.setStyleSheet(
            f"font-family: monospace; font-size: {GEOMETRY['countdownFontPt']}pt;"
            f" font-weight: bold; color: {PALETTE['accent']};"
        )
        schedule_form.addRow(STRINGS.LABEL_COUNTDOWN, self.countdown_label)

        self.schedule_summary_label = QLabel(SCHEDULE_UNAVAILABLE, self.schedule_group)
        self.schedule_summary_label.setWordWrap(True)
        schedule_form.addRow(STRINGS.LABEL_SUMMARY, self.schedule_summary_label)

        # UI-9 Task 2: the scheduling column (right of the two).
        schedule_column_layout.addWidget(self.schedule_group)
        # The queue status line sits under the schedule (2.2), styled as a
        # muted status line.
        self.queue_status_label.setWordWrap(True)
        self.queue_status_label.setProperty("muted", "true")

        # ---------------------------------------------
        # Diagnostic section (UI-6 Tasks 1-3) — REAL content, mode-gated
        # ---------------------------------------------
        # ONE minimal diagnostic section proving the display boundary: in
        # NORMAL mode it is hidden; in DIAGNOSTIC mode it may be shown.
        # Its content is real — the per-order execution verdicts of the
        # last Test pass (from the actual OrderExecutionResult objects),
        # the dispatch-level Trace ID (UI-6 Task 2) and the latency/
        # execution diagnostics of THIS run's EXISTING Block 8 report
        # (UI-6 Task 3: total dispatch, internal stages, Broker/API round
        # trips, application split — rendered, never re-measured). No
        # technical payload is ever attached to the list items.

        self.diagnostic_section = QGroupBox(
            DIAGNOSTIC_SECTION_TITLE, self
        )
        diagnostic_layout = QVBoxLayout(self.diagnostic_section)

        # UI-6 Task 2: the dispatch-level Trace ID line. ONE section-level
        # label (the trace belongs to the whole dispatch, never to a single
        # order/log row), rendered ONLY from the run's real
        # ``DispatchResult.trace_id`` and shown ONLY while the section is
        # visible (DIAGNOSTIC mode) — the label inherits the section's
        # visibility, so NORMAL never discloses it.
        self.trace_id_label = QLabel(
            DIAGNOSTIC_TRACE_LABEL + DIAGNOSTIC_TRACE_UNAVAILABLE,
            self.diagnostic_section,
        )
        diagnostic_layout.addWidget(self.trace_id_label)

        # UI-6 Task 3: the latency/execution diagnostics of THIS run's
        # EXISTING Block 8 report — a section-level total line plus ONE
        # per-order detail list. Categories stay separate (dispatch total,
        # internal stages, Broker/API round trips, application split); the
        # UI renders the report's own values only and inherits the
        # section's mode-gated visibility.
        self.latency_total_label = QLabel(
            DIAGNOSTIC_LATENCY_TOTAL_LABEL + DIAGNOSTIC_VALUE_UNAVAILABLE,
            self.diagnostic_section,
        )
        diagnostic_layout.addWidget(self.latency_total_label)

        self.latency_detail_list = QListWidget(self.diagnostic_section)
        self.latency_detail_list.setMaximumHeight(160)
        diagnostic_layout.addWidget(self.latency_detail_list)

        self.diagnostic_list = QListWidget(self.diagnostic_section)
        self.diagnostic_list.setMaximumHeight(120)
        diagnostic_layout.addWidget(self.diagnostic_list)

        self.diagnostic_status_label = QLabel(
            DIAGNOSTIC_EMPTY_STATE, self.diagnostic_section
        )
        diagnostic_layout.addWidget(self.diagnostic_status_label)

        # UI-9 Task 2: the Diagnostic section is placed LAST in the
        # assembly below (after Order Log). Its NORMAL/DIAGNOSTIC
        # visibility boundary is unchanged.
        self.diagnostic_section.setVisible(False)  # NORMAL-mode default

        # ---------------------------------------------
        # Order Log (UI-5 Task 4, base display)
        # ---------------------------------------------
        # A read-only seven-column table of the orders the user has sent:
        # one row per sent order, in send order. Rows are appended by the
        # send action (never by the queue or by a refresh) and are rendered
        # only from the in-memory OrderLog this page owns.

        self.order_log = OrderLog()

        log_group = QGroupBox(ORDER_LOG_GROUP_TITLE, self)
        log_layout = QVBoxLayout(log_group)

        self.order_log_table = QTableWidget(0, len(ORDER_LOG_COLUMNS), log_group)
        self.order_log_table.setHorizontalHeaderLabels(list(ORDER_LOG_COLUMNS))
        self.order_log_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch
        )
        self.order_log_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.order_log_table.setSelectionMode(QTableWidget.SingleSelection)
        self.order_log_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.order_log_table.setWordWrap(False)
        # UI-9 Task 2 — uniform row height and a readable header, both from
        # theme tokens (no magic numbers). The header is slightly taller
        # than a data row so its bold labels are not cramped.
        self.order_log_table.verticalHeader().setDefaultSectionSize(
            GEOMETRY["rowHeight"]
        )
        self.order_log_table.verticalHeader().setVisible(False)
        self.order_log_table.horizontalHeader().setDefaultSectionSize(
            GEOMETRY["rowHeight"]
        )
        self.order_log_table.setMinimumHeight(
            GEOMETRY["rowHeight"] * ORDER_LOG_MIN_VISIBLE_ROWS
        )
        log_layout.addWidget(self.order_log_table)

        # ---------------------------------------------
        # UI-9 Task 2 — final assembly of the page body
        # ---------------------------------------------
        #
        # Order of appearance inside the scroll area:
        #   1. top row      — two equal columns (already added above)
        #   2. tables row   — Order Queue | Test Results
        #   3. Order Log    — full width
        #   4. Diagnostic   — last, mode-gated exactly as before
        content_layout.addLayout(tables_row)
        content_layout.addWidget(log_group)
        content_layout.addWidget(self.diagnostic_section)
        content_layout.addStretch(1)

        # The queue status gets its own bordered group box in the scheduling
        # column, directly BELOW the Schedule group (UI-9 Task 2b, matching
        # the «وضعیت صف» box in the mockup).
        #
        # Every spacing/margin/radius value comes from ui/theme.py tokens, so
        # this box is visually identical to the other group boxes on the page.
        queue_status_group = QGroupBox(QUEUE_STATUS_GROUP_TITLE, self)
        queue_status_layout = QVBoxLayout(queue_status_group)
        queue_status_layout.setContentsMargins(0, 0, 0, 0)
        queue_status_layout.setSpacing(0)
        queue_status_layout.addWidget(self.queue_status_label)
        # A themed group box already carries its own border, radius and
        # padding from the stylesheet; nothing else is set here so it stays
        # pixel-identical to its eight sibling group boxes.
        schedule_column_layout.addWidget(queue_status_group)
        # The scheduling column is naturally shorter than the order column;
        # this trailing stretch keeps the group directly under the schedule
        # instead of floating in the leftover vertical space.
        schedule_column_layout.addStretch(1)

        self._refresh_amounts()
        self._start_auto_amount()
        self._refresh_symbol_info()

    # ---------------------------------------------------------
    # Symbol typing / debounced REAL search (UI-3.2A)
    # ---------------------------------------------------------

    def set_resolver_factory(self, factory):
        """
        Provide the factory that builds the REAL ``SymbolResolver``.

        Production hands in ``None`` (the lazily created repository
        resolver is used); tests may inject a stub resolver factory so
        no network is ever touched. The factory is called on the worker
        thread, immediately before each real search/resolve.
        """
        self._resolver_factory = factory

    def set_trading_state_query_factory(self, factory):
        """
        Provide the factory that builds the REAL trading-state query
        seam (``core.trading_state_query.TradingStateQuery`` backed by
        the real broker/provider pair).

        Production hands in ``None`` (the lazily created repository
        query is used); tests may inject a stub factory so no network is
        ever touched. The factory is called on the worker thread,
        immediately before a real state query runs.
        """
        self._trading_state_factory = factory

    def set_order_identity_factory(self, factory):
        """
        Provide the factory that builds the REAL order-identity resolver
        (the broker ``InstrumentProvider`` exposing
        ``get_nsc_id(ins_code)``).

        Production hands in ``None`` (the lazily created provider for
        the ACTIVE account's broker is used); tests may inject a stub
        factory so no network is ever touched. The factory is called on
        the worker thread, immediately before a real resolution runs.
        """
        self._order_identity_factory = factory

    def set_price_limits_factory(self, factory):
        """Inject the TSETMC price-limits client factory (tests use a stub).

        The factory is called on the background worker, never during page
        construction, so the UI stays offline until an arrow is pressed.
        """
        self._price_limits_factory = factory

    def set_quantity_limits_factory(self, factory):
        """Inject an account-scoped BrokerInstrument provider factory.

        The factory is called on the background worker with the exact
        ``(account_id, broker_name)`` captured at request time. When it is
        not supplied, the existing order-identity factory is used so the
        provider remains the one owned by the active account's broker.
        """
        self._quantity_limits_factory = factory

    def set_buy_preview_factory(self, factory):
        """Inject account-bound, read-only Agaah preview service factory."""
        self._buy_preview_factory = factory

    def _buy_preview_snapshot(self):
        record = self._active_account_record()
        instrument = self.config.selected_instrument
        nsc_id = self._order_nsc_id
        if record is None or instrument is None or not nsc_id:
            raise ValueError("حساب فعال، نماد انتخاب‌شده و شناسهٔ نماد لازم است")
        if record.broker_name != "آگاه":
            raise ValueError("ماشین‌حساب پیش‌نمایش فقط برای آگاه در دسترس است")
        if self.config.side != BUY:
            raise ValueError("پیش‌نمایش فقط برای سفارش خرید است")
        price = _valid_limit(_parse_exact_integral_text(self.price_input.text()))
        if price == 0:
            price = None
        return (record.account_id, record.broker_name, instrument.ins_code,
                nsc_id, price, self._search_sequence, self.config.side)

    def _open_buy_preview(self):
        try:
            snapshot = self._buy_preview_snapshot()
        except Exception as exc:
            self._show_validation_error(str(exc))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("محاسبه پیش‌نمایش سفارش خرید")
        layout = QVBoxLayout(dialog)
        self.preview_power_label = QLabel("در حال دریافت قدرت خرید…", dialog)
        self.preview_amount_input = QLineEdit(dialog)
        self.preview_amount_input.setPlaceholderText("مبلغ موردنظر به ریال")
        self.preview_amount_input.textChanged.connect(self._preview_inputs_changed)
        layout.addWidget(self.preview_power_label)
        amount_row = QHBoxLayout()
        amount_row.addWidget(self.preview_amount_input)
        for icon, ratio, tip in (("battery-full.svg", 1, "کل قدرت خرید"),
                                 ("battery-half.svg", 2, "نصف قدرت خرید")):
            button = QPushButton(dialog)
            button.setIcon(QIcon(str(_ICONS_DIR / icon)))
            button.setToolTip(tip)
            button.clicked.connect(lambda _=False, r=ratio: self._fill_preview_amount(r))
            amount_row.addWidget(button)
        layout.addLayout(amount_row)
        layout.addWidget(QLabel("قیمت (ریال)", dialog))
        self.preview_price_input = QLineEdit(str(snapshot[4]) if snapshot[4] else "", dialog)
        self.preview_price_input.textChanged.connect(self._preview_inputs_changed)
        layout.addWidget(self.preview_price_input)
        price_limits = QHBoxLayout()
        self.preview_price_max_button = QPushButton(dialog)
        self.preview_price_min_button = QPushButton(dialog)
        self.preview_price_max_button.setIcon(QIcon(str(_ARROW_UP_ICON)))
        self.preview_price_min_button.setIcon(QIcon(str(_ARROW_DOWN_ICON)))
        self.preview_price_max_button.setIconSize(QSize(SPACING["lg"], SPACING["lg"]))
        self.preview_price_min_button.setIconSize(QSize(SPACING["lg"], SPACING["lg"]))
        self.preview_price_max_button.setToolTip("حداکثر قیمت مجاز")
        self.preview_price_min_button.setToolTip("حداقل قیمت مجاز")
        self.preview_price_max_button.clicked.connect(lambda: self._set_preview_price_limit("max"))
        self.preview_price_min_button.clicked.connect(lambda: self._set_preview_price_limit("min"))
        price_limits.addWidget(self.preview_price_max_button)
        price_limits.addWidget(self.preview_price_min_button)
        layout.addLayout(price_limits)
        controls = QHBoxLayout()
        self.preview_calculate_button = QPushButton("محاسبه", dialog)
        self.preview_calculate_button.clicked.connect(self._start_buy_preview)
        self.preview_confirm_button = QPushButton("تأیید و پرکردن فرم", dialog)
        self.preview_confirm_button.setEnabled(False)
        self.preview_confirm_button.clicked.connect(self._apply_buy_preview)
        controls.addWidget(self.preview_calculate_button)
        controls.addWidget(self.preview_confirm_button)
        layout.addLayout(controls)
        self.preview_result_label = QLabel("", dialog)
        layout.addWidget(self.preview_result_label)
        self._buy_preview_dialog = dialog
        self._buy_preview_snapshot_value = snapshot
        self._buy_preview_dialog_snapshot = snapshot
        self._buy_preview_power = None
        self._buy_preview_result = None
        self.preview_result_label.setText("")
        dialog.finished.connect(
            lambda _result, current=dialog: self._on_buy_preview_dialog_finished(current)
        )
        self._buy_preview_request_id += 1
        request_id = self._buy_preview_request_id
        factory = self._buy_preview_factory
        worker = _BuyPreviewWorker(
            request_id, snapshot,
            lambda snap: self._get_preview_power_and_form(snap, factory), self,
        )
        self._buy_preview_worker = self._buy_preview_thread = worker
        worker.succeeded.connect(self._on_preview_power_loaded)
        worker.failed.connect(self._on_preview_failed)
        worker.finished.connect(worker.deleteLater)
        worker.start()
        dialog.show()

    def _on_buy_preview_dialog_finished(self, dialog):
        if dialog is self._buy_preview_dialog:
            self._buy_preview_request_id += 1
            self._buy_preview_result = None
            self._buy_preview_power = None
            self._buy_preview_dialog = None

    def _get_preview_power_and_form(self, snapshot, factory):
        if factory is None:
            raise RuntimeError("سرویس پیش‌نمایش آگاه در دسترس نیست")
        service = factory(snapshot[0], snapshot[1])
        power = service.get_tradable_balance(snapshot[0])
        if isinstance(power, bool) or not isinstance(power, int) or power < 0:
            raise ValueError("قدرت خرید معتبر نیست")
        return {"power": power}

    def _on_preview_power_loaded(self, request_id, snapshot, data):
        if (self._buy_preview_dialog is None
                or snapshot != self._buy_preview_dialog_snapshot
                or self.store.active_account_id() != snapshot[0]):
            return
        self._buy_preview_power = data["power"]
        self._buy_preview_snapshot_value = snapshot
        self.preview_power_label.setText(f"قدرت خرید: {self._buy_preview_power:,} ریال")

    def _on_preview_failed(self, request_id, message):
        if request_id == self._buy_preview_request_id and self._buy_preview_dialog is not None:
            self.preview_power_label.setText(message)

    def _preview_inputs_changed(self, *_):
        self._buy_preview_request_id += 1
        self._buy_preview_result = None
        if hasattr(self, "preview_confirm_button"):
            self.preview_confirm_button.setEnabled(False)

    def _set_preview_price_limit(self, kind):
        """Reuse the page's existing TSETMC price-limits worker/factory."""
        instrument = self.config.selected_instrument
        ins_code = getattr(instrument, "ins_code", None)
        if not ins_code or self._buy_preview_dialog is None:
            self.preview_result_label.setText("نماد انتخاب‌شده یا پنجرهٔ محاسبه در دسترس نیست")
            return
        self._buy_preview_request_id += 1
        request_id = self._buy_preview_request_id
        dialog = self._buy_preview_dialog
        dialog_snapshot = self._buy_preview_dialog_snapshot

        def limits_factory():
            if self._price_limits_factory is not None:
                return self._price_limits_factory()
            if self._resolver_factory is not None:
                return self._resolver_factory()
            from market.symbol_resolver import SymbolResolver
            return SymbolResolver()

        worker = _PriceLimitsWorker(ins_code, limits_factory, request_id, self)
        worker.limits_succeeded.connect(
            lambda rid, code, limits: self._on_preview_price_limits(
                rid, code, limits, kind, dialog, dialog_snapshot
            )
        )
        worker.limits_failed.connect(
            lambda rid, code, message: self._on_preview_price_limits_failed(
                rid, code, message, dialog, dialog_snapshot
            )
        )
        worker.finished.connect(worker.deleteLater)
        self._preview_price_limit_worker = worker
        worker.start()

    def _on_preview_price_limits(self, request_id, ins_code, limits, kind,
                                 dialog=None, dialog_snapshot=None):
        if (request_id != self._buy_preview_request_id or
                dialog is not self._buy_preview_dialog or
                dialog_snapshot != self._buy_preview_dialog_snapshot or
                self.config.selected_instrument is None or
                self.config.selected_instrument.ins_code != ins_code):
            return
        value = getattr(limits, "price_max" if kind == "max" else "price_min", None)
        value = _valid_limit(value, allow_zero=False)
        if value is None:
            self.preview_result_label.setText("قیمت مجاز معتبر از TSETMC دریافت نشد")
            return
        self.preview_price_input.setText(str(value))

    def _on_preview_price_limits_failed(self, request_id, ins_code, message,
                                        dialog=None, dialog_snapshot=None):
        if (request_id == self._buy_preview_request_id and
                dialog is self._buy_preview_dialog and
                dialog_snapshot == self._buy_preview_dialog_snapshot and
                getattr(self.config.selected_instrument, "ins_code", None) == ins_code):
            self.preview_result_label.setText(f"قیمت‌های مجاز در دسترس نیست: {message}")

    def _fill_preview_amount(self, divisor):
        if self._buy_preview_power is not None:
            self.preview_amount_input.setText(str(self._buy_preview_power // divisor))

    def _start_buy_preview(self):
        try:
            snapshot = self._buy_preview_snapshot()
            amount = _valid_limit(_parse_exact_integral_text(self.preview_amount_input.text()))
            price = _valid_limit(_parse_exact_integral_text(self.preview_price_input.text()))
            if amount is None or amount <= 0 or price is None or price <= 0:
                raise ValueError("مبلغ و قیمت باید عدد صحیح و مثبت باشند")
            if self._buy_preview_power is None or amount > self._buy_preview_power:
                raise ValueError("مبلغ از قدرت خرید حساب بیشتر است")
            if price is None or price <= 0:
                raise ValueError("قیمت باید عدد صحیح و مثبت باشد")
            snapshot = snapshot[:4] + (price,) + snapshot[5:]
            self._buy_preview_snapshot_value = snapshot + (amount,)
            if self._buy_preview_factory is None:
                raise RuntimeError("سرویس پیش‌نمایش آگاه در دسترس نیست")
            self.preview_result_label.setText("در حال محاسبه…")
            self.preview_confirm_button.setEnabled(False)
            self._buy_preview_request_id += 1
            request_id = self._buy_preview_request_id
            worker = _BuyPreviewWorker(request_id, self._buy_preview_snapshot_value,
                                       self._calculate_buy_preview, self)
            self._buy_preview_worker = self._buy_preview_thread = worker
            worker.succeeded.connect(self._on_buy_preview_calculated)
            worker.failed.connect(self._on_preview_failed)
            worker.finished.connect(worker.deleteLater)
            worker.start()
        except Exception as exc:
            self.preview_result_label.setText(str(exc))

    def _calculate_buy_preview(self, snap):
        account_id, broker_name, ins_code, nsc_id, price, generation, side, amount = snap
        record = self.store.get(account_id)
        if record.broker_name != "آگاه":
            raise ValueError("ماشین‌حساب پیش‌نمایش فقط برای آگاه در دسترس است")
        if self.store.active_account_id() != account_id:
            raise ValueError("حساب فعال هنگام محاسبه تغییر کرده است")
        service = self._buy_preview_factory(account_id, broker_name)
        power = service.get_tradable_balance(account_id)
        if amount > power:
            raise ValueError("مبلغ از قدرت خرید حساب بیشتر است")
        broker = service.get_adapter(account_id)._broker
        quantity = broker.get_buy_capacity(nsc_id, 1, amount, price)
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("تعداد برگشتی از آگاه معتبر نیست")
        amount_order = price * quantity
        # calculatedquantity returns only capacity, with no reduction/lot contract.
        # Never submit a guessed smaller quantity if this result exceeds budget.
        data = broker.get_commission_info(nsc_id, price, quantity, 1)
        commission = data.get("commissionSum")
        if isinstance(commission, bool) or not isinstance(commission, int) or commission < 0:
            raise ValueError("کارمزد برگشتی از آگاه معتبر نیست")
        total = amount_order + commission
        if total > amount or total > power:
            raise ValueError("تعداد محاسبه‌شده از بودجه بیشتر است؛ API تعداد روش دقیق و مجاز برای کاهش تعداد ارائه نمی‌کند")
        return {"price": price, "quantity": quantity, "amount": amount_order,
                "fee": commission, "total": total}

    def _on_buy_preview_calculated(self, request_id, snapshot, result):
        if request_id != self._buy_preview_request_id:
            return
        try:
            current = self._buy_preview_snapshot()
            current = current[:4] + (int(self.preview_price_input.text()),) + current[5:]
            current = current + (int(self.preview_amount_input.text()),)
        except Exception:
            return
        if (current != snapshot or self._buy_preview_power is None
                or self.store.active_account_id() != snapshot[0]):
            return
        self._buy_preview_result = result
        self.preview_result_label.setText(
            f"مبلغ سفارش = {result['amount']:,}\nکارمزد = {result['fee']:,}\nمبلغ کل خرید = {result['total']:,}"
        )
        self.preview_confirm_button.setEnabled(True)

    def _apply_buy_preview(self):
        result = self._buy_preview_result
        if result is None:
            return
        try:
            current = self._buy_preview_snapshot()
            current = current[:4] + (int(self.preview_price_input.text()),) + current[5:]
            current += (int(self.preview_amount_input.text()),)
        except Exception:
            return
        if current != self._buy_preview_snapshot_value or self.store.active_account_id() != current[0]:
            self._buy_preview_result = None
            self.preview_confirm_button.setEnabled(False)
            return
        self.price_input.setText(str(result["price"]))
        self.quantity_input.setText(str(result["quantity"]))
        self.config.set_price(result["price"])
        self.config.set_quantity(result["quantity"])
        self.base_amount_label.setText(f"{result['amount']:,}")
        self.fee_label.setText(f"{result['fee']:,}")
        self.final_amount_label.setText(f"{result['total']:,}")
        self._refresh_test_button_state()
        self._buy_preview_dialog.accept()

    def _invalidate_buy_preview(self, *_):
        self._buy_preview_request_id += 1
        self._buy_preview_result = None
        if self._buy_preview_dialog is not None:
            self.preview_confirm_button.setEnabled(False)

    def _make_limit_arrow(self, icon_path, tooltip, object_name):
        button = QPushButton(self.form_group)
        button.setObjectName(object_name)
        button.setIcon(QIcon(str(icon_path)))
        button.setIconSize(QSize(SPACING["lg"], SPACING["lg"]))
        button.setFixedSize(GEOMETRY["rowHeight"], GEOMETRY["rowHeight"])
        button.setToolTip(tooltip)
        button.setFlat(True)
        return button

    # ---------------------------------------------------------
    # UI-4: the existing core OrderQueue (lazy, never at construction)
    # ---------------------------------------------------------

    @property
    def order_queue(self):
        """
        The EXISTING ``core.order_queue.OrderQueue`` this page prepares
        orders into.

        Tests inject one through the constructor seam; production leaves
        it to the lazy default below. Accessing the queue for the first
        time imports ``core.order_queue`` — which happens on the first
        real Add-to-Queue action, NEVER at construction (the offline
        construction contracts stay intact).
        """
        if self._injected_order_queue is not None:
            return self._injected_order_queue
        return self._default_order_queue()

    def _default_order_queue(self):
        """Build the REAL repository queue once, lazily (on first use)."""
        if self._default_queue is None:
            from core.order_queue import OrderQueue

            self._default_queue = OrderQueue()
        return self._default_queue

    @property
    def results_list(self):
        """
        Row-level compatibility view over the combo popup suggestions.

        There is no separate results QListWidget anymore: the visible
        suggestions are the editable symbol QComboBox's own popup items.
        """
        return _SymbolSuggestionList(self.symbol_input)

    def _symbol_text_is_suggestion(self, text):
        """True when ``text`` is the label of the currently activated row."""
        index = self.symbol_input.currentIndex()
        if index < 0:
            return False
        if self.symbol_input.itemText(index) != text:
            return False
        return self.symbol_input.itemData(index, RESULT_DATA_ROLE) is not None

    def _clear_symbol_suggestions(self, keep_text):
        """
        Remove popup suggestions without treating the programmatic text
        update as user typing.
        """
        self._updating_symbol_suggestions = True
        edit = self.symbol_input.lineEdit()
        self.symbol_input.blockSignals(True)
        edit.blockSignals(True)
        try:
            self.symbol_input.hidePopup()
            self.symbol_input.clear()
            self.symbol_input.setCurrentIndex(-1)
            self.symbol_input.setEditText(keep_text)
        finally:
            edit.blockSignals(False)
            self.symbol_input.blockSignals(False)
            self._updating_symbol_suggestions = False

    def _show_symbol_suggestions(self, sequence, results):
        """
        Put REAL resolver results into the editable combo's popup.

        The identity of every row is the INDEX into ``_latest_results``
        (the original resolver result objects); display text is never
        parsed. The typed text is preserved while items are inserted,
        then the popup is opened for selection.
        """
        self._latest_results = list(results)
        typed = self.symbol_text
        self._updating_symbol_suggestions = True
        edit = self.symbol_input.lineEdit()
        self.symbol_input.blockSignals(True)
        edit.blockSignals(True)
        try:
            self.symbol_input.hidePopup()
            self.symbol_input.clear()
            for index, result in enumerate(self._latest_results):
                self.symbol_input.addItem(
                    f"{result.get('symbol') or ''} - {result.get('name') or ''}"
                )
                # Identity travels as an index, never as parsed text.
                self.symbol_input.setItemData(index, index, RESULT_DATA_ROLE)
                self.symbol_input.setItemData(
                    index, sequence, RESULT_SEQUENCE_ROLE
                )
            # Keep the user's typed text; selecting a row later is what
            # commits a suggestion.
            self.symbol_input.setCurrentIndex(-1)
            self.symbol_input.setEditText(typed)
        finally:
            edit.blockSignals(False)
            self.symbol_input.blockSignals(False)
            self._updating_symbol_suggestions = False

        if self.symbol_input.isVisible():
            # Results are ready: open the combo popup for selection.
            self.symbol_input.showPopup()

    def _on_symbol_edited(self, text):
        """
        Mirror the typed symbol into the config as text only and (re)arm
        the debounce timer for a real background search.

        A new typing session never masquerades as the previous
        selection: the pending debounce is re-armed, and the stale
        selected instrument (no longer matching the new text) is dropped
        explicitly and deterministically.
        """
        if self._updating_symbol_suggestions:
            return
        raw_text = text or ""
        if self._symbol_text_is_suggestion(raw_text):
            # The combo is committing a clicked/activated suggestion;
            # this is not free-form typing. The activated handler will
            # resolve the real result object.
            self.symbol_text = raw_text.strip()
            return

        symbol = raw_text.strip()
        self.symbol_text = symbol

        # New text invalidates EVERY in-flight generation immediately:
        # any search/resolve result that arrives after this point belongs
        # to a superseded request and may neither update the popup nor
        # (re)store a selection — a late resolve for text the user has
        # already replaced must never set selected_instrument.
        self._search_sequence += 1
        self._invalidate_auto_amount()

        # The previously displayed suggestions belong to the superseded
        # request: remove them from the popup and drop their identity
        # list, so an old row can never become a new selection.
        self._clear_symbol_suggestions(symbol)
        self._latest_results = []

        if not symbol:
            # Empty input: no search call at all; the pending debounce is
            # cancelled.
            self._debounce_timer.stop()
            self._set_search_status(SEARCH_STATE_IDLE)
            self.config.select_instrument(None)
            self._clear_trading_state()
            self._clear_order_identity()
            self._refresh_symbol_info()
            self._refresh_test_button_state()
            return

        # New text invalidates the previous selection explicitly: typed
        # text must never be treated as the previously selected
        # instrument until a real result is picked. The previous
        # trading state also belongs to the OLD instrument and must
        # never be attributed to the new text (UI-3.2B).
        self._set_search_status(SEARCH_STATE_IDLE)
        self.config.select_instrument(None)
        self._clear_trading_state()
        self._clear_order_identity()
        self._refresh_symbol_info()

        # Whitespace-only input never triggers a search.
        self._debounce_timer.start()

    def _set_search_status(self, text):
        self.search_status_label.setText(text)

    def _start_symbol_search(self):
        """Debounce fired: launch one real background search (if any)."""
        symbol = (self.symbol_input.currentText() or "").strip()
        if not symbol:
            # Debounce fired on empty/whitespace input → no search call.
            self._set_search_status(SEARCH_STATE_IDLE)
            return

        # Deterministic generation counter: only the latest sequence may
        # update the UI later (stale-result protection).
        self._search_sequence += 1
        sequence = self._search_sequence

        self._set_search_status(SEARCH_STATE_SEARCHING)

        # Plain QThread subclass: run() does the work and the thread
        # finishes by itself when run() returns — fully deterministic.
        worker = SymbolSearchWorker(
            symbol,
            sequence,
            resolver_factory=self._resolver_factory,
            parent=self,
        )
        self._search_worker = worker
        self._search_thread = worker
        self._active_search_threads.append(worker)
        worker.search_succeeded.connect(self._on_search_succeeded)
        worker.search_failed.connect(self._on_search_failed)
        # Lifecycle: the worker forgets ITSELF the moment its run()
        # returns (Qt emits ``finished`` on every completion path —
        # success, failure, or a result that will be discarded as
        # stale) — no worker/thread can linger on any path.
        worker.finished.connect(
            lambda w=worker: self._forget_worker(w)
        )
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _forget_worker(self, worker):
        """Drop one finished worker from the live set (all paths)."""
        if worker in self._active_search_threads:
            self._active_search_threads.remove(worker)
        if self._search_thread is worker:
            self._search_thread = None
            self._search_worker = None
        if self._resolve_thread is worker:
            self._resolve_thread = None
            self._resolve_worker = None

    def _current_sequence(self):
        return self._search_sequence

    def _on_search_succeeded(self, sequence, results):
        """
        Apply a successful search ONLY if it is still the latest one.

        A stale result (an older sequence finishing after a newer search
        started) is discarded — it must never overwrite the newer
        result.
        """
        if sequence != self._search_sequence:
            return  # stale generation — discarded deterministically

        self._searching = False
        if not results:
            self._latest_results = []
            self._clear_symbol_suggestions(self.symbol_text)
            self._set_search_status(SEARCH_STATE_NO_RESULTS)
            return
        # The result's identity travels as the INDEX into the page's
        # shared list of the real resolver result objects — the object
        # itself never passes through a Qt signal (signals marshall/copy
        # payloads), and identity is never rebuilt by parsing the display
        # text. Each popup row is tagged with its search generation so a
        # superseded row can never resolve.
        self._show_symbol_suggestions(sequence, results)
        self._set_search_status(SEARCH_STATE_IDLE)

    def _on_search_failed(self, sequence, message):
        """
        A failed search never crashes the UI and never shows stale
        results; a newer generation's results are untouched.
        """
        if sequence != self._search_sequence:
            return  # a stale failure must not clobber the newer state
        self._searching = False
        self._latest_results = []
        self._clear_symbol_suggestions(self.symbol_text)
        self._set_search_status(f"Search failed: {message}")

    def _on_symbol_activated(self, index):
        """
        Commit a suggestion picked from the combo popup.

        The row's identity comes from the item data (an index into the
        original resolver results), never from the display text. The
        text-change suppression above keeps this activation from being
        mistaken for a new typing session.
        """
        if self._updating_symbol_suggestions or index < 0:
            return
        row_sequence = self.symbol_input.itemData(index, RESULT_SEQUENCE_ROLE)
        result_index = self.symbol_input.itemData(index, RESULT_DATA_ROLE)
        if row_sequence != self._search_sequence or result_index is None:
            return
        self._debounce_timer.stop()
        self.symbol_text = self.symbol_input.itemText(index).strip()
        self._on_result_selected(self.results_list.item(index))

    def _on_result_selected(self, item):
        """
        Resolve the picked REAL search result into a REAL Instrument via
        ``SymbolResolver.resolve()`` on the worker thread.

        Guards:
          * the row must belong to the CURRENT search generation — a row
            from a superseded generation (the user already retyped) is
            never resolved and never becomes a selection;
          * one resolve at a time — duplicate deliveries of the same
            interaction (itemClicked + itemActivated of one double-click)
            collapse into a single worker instead of racing into two.
        """
        try:
            row_sequence = item.data(RESULT_SEQUENCE_ROLE)
            index = item.data(RESULT_DATA_ROLE)
        except RuntimeError:
            # The row was deleted between the click and this delivery —
            # nothing to resolve, never a crash.
            return
        if row_sequence != self._search_sequence:
            return  # superseded generation — never resolve, never select
        if index is None:
            return  # never parse identity out of display text
        try:
            result = self._latest_results[index]
        except (IndexError, TypeError):
            return  # unknown/stale row — never guess an identity
        if result is None:
            return
        if self._resolve_thread is not None:
            return  # a resolve is already in flight — one worker only

        sequence = self._search_sequence
        self._set_search_status(SEARCH_STATE_SEARCHING)

        worker = SymbolResolveWorker(
            result,
            sequence,
            resolver_factory=self._resolver_factory,
            parent=self,
        )
        self._resolve_worker = worker
        self._resolve_thread = worker
        self._active_search_threads.append(worker)
        worker.resolve_succeeded.connect(self._on_resolve_succeeded)
        worker.resolve_failed.connect(self._on_resolve_failed)
        worker.finished.connect(
            lambda w=worker: self._forget_worker(w)
        )
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def wait_for_workers(self, timeout_ms=5000):
        """
        Wait (bounded) for all background search/resolve threads to
        finish. Used by tests for deterministic teardown; production
        never needs to call this.
        """
        for thread in list(self._active_search_threads):
            if not thread.wait(timeout_ms):
                raise TimeoutError("symbol worker thread did not finish")

    def _on_resolve_succeeded(self, sequence, instrument):
        """Store the resolver-produced REAL Instrument (latest only)."""
        if sequence != self._search_sequence:
            return  # stale resolve — discarded
        # OrderConfiguration.select_instrument re-validates: only a real
        # models.instrument.Instrument is ever stored (fail-closed).
        try:
            self.config.select_instrument(instrument)
        except OrderConfigError as exc:
            # Never store a fabricated object; keep the previous state.
            self._set_search_status(f"Resolve failed: {exc}")
            return
        self._set_search_status(SEARCH_STATE_IDLE)
        self._refresh_symbol_info()
        self._start_trading_state_query(instrument)
        # UI-4: capture the broker nscId of THIS instrument off the GUI
        # thread now, so Add-to-Queue never performs a network call.
        self._start_order_identity_resolution(instrument)
        self._refresh_test_button_state()

    def _on_resolve_failed(self, sequence, message):
        """Resolve failure: previous selection stays, nothing fabricated."""
        if sequence != self._search_sequence:
            return
        self._set_search_status(f"Resolve failed: {message}")

    # ---------------------------------------------------------
    # Trading state display (UI-3.2B — read-only, fail-closed)
    # ---------------------------------------------------------

    def _clear_trading_state(self):
        """
        Drop the displayed trading state of the PREVIOUS instrument.

        The old status must never survive a symbol change or be
        attributed to the new typed text: the in-flight query for the
        old instrument is invalidated (its ins_code can no longer match
        the shown selection) and the display is reset.
        """
        self._trading_state_instrument = None
        self._trading_state_account_scope = None
        self._trading_state_shown = None
        self._cancel_trading_state_query()
        self.trading_state_label.setText(STATUS_LABEL_UNKNOWN)
        self._hide_market_status_icon()

    def _cancel_trading_state_query(self):
        """
        Invalidate any in-flight state query.

        The running worker finishes on its own (its result is discarded
        as stale by _on_trading_state_succeeded/failed) — no thread is
        killed, and the worker is reaped by its own finished-cleanup.
        """
        self._trading_state_worker = None
        self._trading_state_thread = None

    def _hide_market_status_icon(self):
        self.trading_state_icon.clear()
        self.trading_state_icon.setToolTip("")
        self.trading_state_icon.setAccessibleName("")
        self.trading_state_icon.setProperty("marketStatus", None)
        self.trading_state_icon.setProperty("stateColor", None)
        self.trading_state_icon.setProperty("iconPath", None)
        self.trading_state_icon.hide()

    def _render_market_status(self, state=None, tooltip=None):
        status = state.market_status if isinstance(state, TradingState) else None
        if tooltip is None:
            tooltip = _market_status_title(state)
        color = _market_status_color(status)
        icon_path = _market_status_icon_path(status)
        self.trading_state_icon.setPixmap(_market_status_pixmap(status))
        self.trading_state_icon.setToolTip(tooltip)
        self.trading_state_icon.setAccessibleName(tooltip)
        self.trading_state_icon.setProperty(
            "marketStatus",
            status.value if isinstance(status, MarketStatus) else None,
        )
        self.trading_state_icon.setProperty("stateColor", color)
        self.trading_state_icon.setProperty("iconPath", str(icon_path))
        self.trading_state_icon.show()

    def _start_trading_state_query(self, instrument):
        """
        After a REAL instrument selection, read its trading state from
        the EXISTING project path on a background thread:

            TradingStateQuery(ins_code)
                → provider.get_instrument
                → broker.get_trading_state(nsc_id)
                → TradingState

        The status is rendered ONLY from the returned ``TradingState``;
        it is never guessed from the symbol text and the raw broker
        mapping is never duplicated here — the UI renders only the
        verdict the existing project path already decided. Any expected
        failure is shown as unknown — never a crash, never "tradable".
        """
        self._clear_trading_state()
        if instrument is None:
            return

        ins_code = getattr(instrument, "ins_code", None)
        if not ins_code:
            # No real identity → nothing to query; fail-closed display.
            self.trading_state_label.setText(STATUS_LABEL_UNKNOWN)
            self._render_market_status(tooltip=STATUS_LABEL_UNKNOWN)
            return

        # Display status is sourced directly from TSETMC by ins_code and
        # is intentionally independent of account selection.
        identity = (self._search_sequence, ins_code)
        self._trading_state_instrument = ins_code
        self._trading_state_account_scope = identity
        self.trading_state_label.setText(STATUS_PENDING_LABEL)
        self._render_market_status(tooltip=STATUS_PENDING_LABEL)

        def query_factory():
            if self._trading_state_factory is None:
                from ui.trading_state_worker import _default_trading_state_query
                return _default_trading_state_query()
            try:
                signature = inspect.signature(self._trading_state_factory)
                signature.bind()
            except (TypeError, ValueError):
                # Keep compatibility with existing callers that accept the
                # former account arguments; status retrieval itself is direct.
                return self._trading_state_factory(None, None)
            return self._trading_state_factory()

        worker = TradingStateWorker(
            ins_code,
            query_factory=query_factory,
            parent=self,
            identity=identity,
        )
        self._trading_state_worker = worker
        self._trading_state_thread = worker
        worker.state_succeeded.connect(self._on_trading_state_succeeded)
        worker.state_failed.connect(self._on_trading_state_failed)
        # Lifecycle: the worker forgets ITSELF the moment run() returns
        # (same self-reaping pattern as the search/resolve workers).
        worker.finished.connect(
            lambda w=worker: self._forget_trading_state_worker(w)
        )
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _forget_trading_state_worker(self, worker):
        """Drop one finished trading-state worker (all paths)."""
        if self._trading_state_thread is worker:
            self._trading_state_thread = None
            self._trading_state_worker = None

    def wait_for_trading_state_workers(self, timeout_ms=5000):
        """
        Wait (bounded) for the background state query thread to finish.
        Used by tests for deterministic teardown; production never needs
        to call this.
        """
        thread = self._trading_state_thread
        if thread is not None and not thread.wait(timeout_ms):
            raise TimeoutError("trading-state worker thread did not finish")

    def _on_trading_state_succeeded(self, identity, ins_code, state):
        """
        Render the returned ``TradingState`` — but ONLY if it still
        belongs to the currently selected instrument.

        A late result for a symbol the user already replaced is
        discarded: the old status can never be attributed to the new
        symbol or to bare typed text.
        """
        if (ins_code != self._trading_state_instrument
                or identity != self._trading_state_account_scope
                or identity != (self._search_sequence, ins_code)):
            return  # stale query — discarded deterministically
        if not isinstance(state, TradingState):
            # Anything unexpected from the seam is unknown (fail-closed).
            self._render_trading_state(STATUS_LABEL_UNKNOWN)
            self._render_market_status(tooltip=STATUS_LABEL_UNKNOWN)
            return
        self._trading_state_shown = state
        self._render_trading_state(self._trading_state_text(state))
        self._render_market_status(state)

    def _on_trading_state_failed(self, identity, ins_code, message):
        """
        The query seam reported a failure (e.g. the expected
        TradingStateUnavailable path): the UI must not crash and the
        status is shown as unknown — never tradable, never fabricated.
        """
        if (ins_code != self._trading_state_instrument
                or identity != self._trading_state_account_scope
                or identity != (self._search_sequence, ins_code)):
            return  # stale query — discarded deterministically
        self._trading_state_shown = None
        self._render_trading_state(STATUS_LABEL_UNKNOWN)
        self._render_market_status(tooltip=STATUS_LABEL_UNKNOWN)

    @staticmethod
    def _trading_state_text(state):
        """
        Map a REAL ``TradingState`` to its user-facing label.

        Exactly the three fail-closed branches the project contract
        defines — no new vocabulary is invented here, and anything that
        is not a real ``TradingState`` is unknown (fail-closed):

            is_verified and allowed      → قابل معامله
            is_verified and not allowed  → غیرقابل معامله
            anything else (UNVERIFIED,
            unknown source, ...)         → نامشخص
        """
        if isinstance(state, TradingState):
            if state.is_verified and state.is_order_entry_allowed:
                return STATUS_LABEL_TRADABLE
            if state.is_verified:
                return STATUS_LABEL_NOT_TRADABLE
        return STATUS_LABEL_UNKNOWN

    def _render_trading_state(self, text):
        self.trading_state_label.setText(text)

    # ---------------------------------------------------------
    # Order identity (UI-4): broker nscId for the selected Instrument
    # ---------------------------------------------------------

    def _clear_order_identity(self):
        """
        Drop the resolved nscId of the PREVIOUS instrument/broker pair.

        An identity is scoped to one (ins_code, broker_name) — a symbol
        change or an account switch always drops it (its in-flight
        worker keeps running and its result is discarded as stale by the
        guards below). Never bound to a different selection.

        The running worker reference is deliberately KEPT (not cleared):
        the worker reaps ITSELF on ``finished``, and keeping the
        reference lets tests (and the page) wait on it deterministically.
        """
        self._order_identity_instrument = None
        self._order_identity_broker = None
        self._order_identity_account = None
        self._order_identity_scope = None
        self._order_nsc_id = None
        self._invalidate_limit_requests()

    def _start_order_identity_resolution(self, instrument):
        """
        Resolve the broker ``nscId`` of a REAL instrument selection on a
        background thread, through the EXISTING read-only seam:

            InstrumentProvider.get_nsc_id(ins_code)

        The result is stored ONLY for the (ins_code, broker_name) pair
        captured here; a late result for a replaced symbol or a changed
        account is never used (fail-closed).
        """
        if instrument is None:
            return

        ins_code = getattr(instrument, "ins_code", None)
        if not ins_code:
            # No real identity → nothing to resolve; fail-closed.
            self._clear_order_identity()
            return

        broker_name = self._active_broker_name()
        record = self._active_account_record()
        if record is None:
            self._clear_order_identity()
            return
        if broker_name != record.broker_name:
            self._clear_order_identity()
            return
        identity = (record.account_id, record.broker_name, ins_code)

        # A resolution for the SAME (ins_code, broker_name) pair is
        # already in flight — do not start a duplicate worker.
        if (
            self._order_identity_thread is not None
            and not self._order_identity_thread.isFinished()
            and self._order_identity_instrument == ins_code
            and self._order_identity_broker == broker_name
            and self._order_identity_account == record.account_id
        ):
            return

        self._clear_order_identity()
        self._order_identity_instrument = ins_code
        self._order_identity_broker = broker_name
        self._order_identity_account = record.account_id
        self._order_identity_scope = identity

        factory = self._order_identity_factory

        def account_resolver_factory():
            if factory is None:
                return _default_order_identity_resolver(
                    self.store, account_id=record.account_id,
                    broker_name=record.broker_name,
                )
            try:
                signature = inspect.signature(factory)
                signature.bind(record.account_id, record.broker_name)
            except (TypeError, ValueError):
                return factory()
            return factory(record.account_id, record.broker_name)

        worker = _OrderIdentityWorker(
            ins_code, account_resolver_factory, parent=self, identity=identity
        )
        self._order_identity_worker = worker
        self._order_identity_thread = worker
        worker.identity_succeeded.connect(self._on_order_identity_succeeded)
        worker.identity_failed.connect(self._on_order_identity_failed)
        # Lifecycle: the worker forgets ITSELF the moment run() returns
        # (same self-reaping pattern as the other workers).
        worker.finished.connect(
            lambda w=worker: self._forget_order_identity_worker(w)
        )
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _forget_order_identity_worker(self, worker):
        """Drop one finished identity worker (all paths)."""
        if self._order_identity_thread is worker:
            self._order_identity_thread = None
            self._order_identity_worker = None

    def wait_for_order_identity_workers(self, timeout_ms=5000):
        """
        Wait (bounded) for the background identity-resolution thread to
        finish. Used by tests for deterministic teardown; production
        never needs to call this.
        """
        thread = self._order_identity_thread
        if thread is not None and not thread.wait(timeout_ms):
            raise TimeoutError("order-identity worker thread did not finish")

    def _on_order_identity_succeeded(self, identity, ins_code=None, nsc_id=None):
        """
        Store the resolved broker nscId — but ONLY if it still belongs
        to the currently selected (ins_code, broker_name) pair.

        A late resolution for a symbol the user already replaced, or for
        an account the user already switched, is discarded (fail-closed:
        an identity is never attached to a different selection).
        """
        # Compatibility for the existing internal two-argument slot contract
        # used by older tests/callers: recover the captured scope only when
        # the current full selection still matches exactly.
        if nsc_id is None and isinstance(identity, str):
            nsc_id = ins_code
            ins_code = identity
            identity = self._order_identity_scope
        if (ins_code != self._order_identity_instrument
                or identity != self._order_identity_scope
                or (identity is not None
                    and identity != self._current_read_identity(ins_code))):
            return  # stale resolution — discarded deterministically
        if self._order_identity_broker != self._active_broker_name():
            # The active broker changed mid-resolution: this nscId
            # belongs to the OLD broker — never bind it to the new one.
            self._order_nsc_id = None
            return
        self._order_nsc_id = (
            nsc_id if isinstance(nsc_id, str) and nsc_id else None
        )

    def _on_order_identity_failed(self, identity, ins_code=None, message=None):
        """A failed resolution leaves the identity unresolved (closed)."""
        if message is None and isinstance(identity, str):
            message = ins_code
            ins_code = identity
            identity = self._order_identity_scope
        if (ins_code != self._order_identity_instrument
                or identity != self._order_identity_scope
                or (identity is not None
                    and identity != self._current_read_identity(ins_code))):
            return  # stale failure — discarded deterministically
        self._order_nsc_id = None

    # ---------------------------------------------------------
    # Add to Queue (UI-4): prepare ONE real Order, enqueue it
    # ---------------------------------------------------------

    def _on_add_to_queue(self):
        """
        Prepare ONE ``models.order.Order`` from the current form state
        and append it to the EXISTING ``OrderQueue`` with the active
        account/broker binding.

        Strictly fail-closed — nothing is queued unless EVERY element is
        real and bound coherently:
          * an active account (its broker is the identity's broker),
          * a selected real Instrument,
          * side, price and quantity,
          * a resolved broker nscId for exactly (ins_code, broker_name).

        No dispatch, no broker call, no network happens here: the nscId
        was already captured off the GUI thread at selection time.

        Returns True when an order was queued, False otherwise (the
        queue is left untouched).
        """
        record = self._active_account_record()
        if record is None:
            self._show_queue_status(QUEUE_STATUS_NO_ACCOUNT)
            return False

        authorization = self._order_authorization(record.account_id, record.broker_name)
        if not authorization.authorized:
            self._show_queue_status(STRINGS.ORDER_AUTHORIZATION_REQUIRED)
            return False

        instrument = self.config.selected_instrument
        if instrument is None:
            self._show_queue_status(QUEUE_STATUS_NO_SYMBOL)
            return False

        side = self.config.side
        price = self.config.price
        quantity = self.config.quantity
        if side is None or price is None or quantity is None:
            self._show_queue_status(QUEUE_STATUS_INCOMPLETE)
            return False

        ins_code = getattr(instrument, "ins_code", None)
        if (record.account_id != self._order_identity_account
                or self._order_identity_scope
                != (record.account_id, record.broker_name, ins_code)):
            self._show_queue_status(QUEUE_STATUS_NO_IDENTITY)
            return False
        if ins_code != self._order_identity_instrument:
            # The identity belongs to a different (or no) selection.
            self._show_queue_status(QUEUE_STATUS_NO_IDENTITY)
            return False
        if self._order_identity_broker != record.broker_name:
            # The nscId was resolved for ANOTHER broker — never bind it
            # to the current account. A reselect resolves it afresh.
            self._show_queue_status(QUEUE_STATUS_BROKER_STALE)
            return False
        nsc_id = self._order_nsc_id
        if not nsc_id:
            self._show_queue_status(QUEUE_STATUS_NO_IDENTITY)
            return False

        # One real Order (the Core model) — identity came from the
        # EXISTING provider seam, never guessed or fabricated.
        order = Order(
            nsc_id=nsc_id,
            side=side,
            price=price,
            quantity=quantity,
        )
        # UI-5 Task 3: keep the user-selected symbol in the UI layer, keyed
        # by this exact Order object. ``Order`` carries no symbol and the
        # broker nscId must never reach a result row, so the display symbol
        # is captured here at the exact enqueue action.
        symbol = getattr(instrument, "symbol", "")
        self._order_symbols[id(order)] = (
            symbol if isinstance(symbol, str) and symbol else ""
        )
        self.order_queue.enqueue(
            order,
            account_id=record.account_id,
            broker_name=record.broker_name,
        )
        self._show_queue_status(QUEUE_STATUS_QUEUED)
        self._refresh_queue_display()
        self._refresh_test_button_state()
        return True

    def _refresh_queue_display(self):
        """
        Re-render the visible queue list ONLY from the exact entries the
        EXISTING ``OrderQueue.list_pending()`` returned.

        The entry (and hence the exact queued Order object) is carried in
        the row's data role — orders are never cloned/rebuild for display,
        and display text is never parsed back into identity.
        """
        self.queue_list.clear()
        pending = self.order_queue.list_pending()
        for entry in pending:
            order = entry.order
            side_label = dict(SIDE_LABELS).get(
                getattr(order, "side", None),
                str(getattr(order, "side", "")),
            )
            text = (
                f"{getattr(order, 'nsc_id', '')} | {side_label} | "
                f"{getattr(order, 'price', '')} | "
                f"{getattr(order, 'quantity', '')} | "
                f"{entry.account_id} - {entry.broker_name}"
            )
            item = QListWidgetItem(text, self.queue_list)
            item.setData(QUEUE_ENTRY_ROLE, entry)
        # UI-9 Task 3: the count uses PERSIAN digits via the ONE formatter.
        self.queue_count_label.setText(
            STRINGS.QUEUE_COUNT_FORMAT.format(
                count=STRINGS.format_persian_digits(len(pending))
            )
        )

    def _show_queue_status(self, text):
        self.queue_status_label.setText(text)

    # ---------------------------------------------------------
    # UI-5 Task 1: Test Button / Test Mode (UI-only toggle)
    # ---------------------------------------------------------

    def _on_test_toggled(self, checked):
        """
        Toggle the UI-only Test Mode state.

        This is a PURE UI state toggle — no execution, no dispatch,
        no broker call, no network activity of any kind. The button
        label reflects the state: OFF -> "Test", ON -> "Test (On)".

        When the toggle turns Test Mode ON, exactly one dry-run Test pass
        is issued through the wired runner (see ``_run_test_pass``) — the
        intentional Test action. Turning OFF never executes anything.
        """
        self._test_mode = bool(checked)
        self.test_button.setText(
            STRINGS.BUTTON_TEST_ON if self._test_mode else STRINGS.BUTTON_TEST
        )
        if self._test_mode:
            self._run_test_pass()

    def set_test_runner_factory(self, factory):
        """
        Provide the factory that builds the Test runner (UI-5 Task 2).

        The runner drives the Test action's pending entries through the
        EXISTING dry-run execution chain (UI-4 bridge -> DispatchIntegration
        -> DispatchCore -> OrderEngine). It is built on the FIRST real Test
        pass, never at construction or plain refresh, so no Core/Broker
        import is ever forced by this page (offline contracts preserved).
        Tests inject a fake runner factory so no dispatch is ever issued.
        """
        self._test_runner_factory = factory

    def set_order_authorizer_factory(self, factory):
        self._order_authorizer_factory = factory

    def _order_authorization(self, account_id, broker_name):
        if self._order_authorizer_factory is None:
            from ui.order_authorization import AuthorizationResult
            return AuthorizationResult(False, "services_unavailable")
        try:
            return self._order_authorizer_factory()(account_id, broker_name)
        except Exception:
            from ui.order_authorization import AuthorizationResult
            return AuthorizationResult(False, "authorization_error")

    def set_feedback_binder_factory(self, factory):
        """
        Provide the factory that binds this page to the EXISTING order
        feedback path (UI-5 Task 4 Stage 3 Task 3).

        Block 9 Task 9B: production MainWindow supplies an ACCOUNT-AWARE
        factory ``(account_id, broker_name) -> service`` returning the
        feedback runtime of exactly that account. The returned service
        object — which already exposes ``order_registered`` — is connected
        here, and the page remembers which account it belongs to so an event
        can only ever resolve that account's row. The factory is called
        lazily on the FIRST real send (never at construction), so the page
        stays fully offline without it. A zero-arg factory (legacy/test
        double) is also accepted and bound to the active account. The page
        only ever uses the signals' existence — it never imports, names or
        starts any feedback/transport module itself.
        """
        self._feedback_binder_factory = factory

    def _test_runner(self):
        """
        Lazily build the wired Test runner (exactly once per factory).

        ``None`` when no runner has been wired — the Test action then
        stays a pure UI toggle (no execution possible).
        """
        if (
            self._test_runner_instance is None
            and self._test_runner_factory is not None
        ):
            self._test_runner_instance = self._test_runner_factory()
        return self._test_runner_instance

    def _run_test_pass(self):
        """
        Issue exactly one dry-run execution pass for the pending entries.

        Only the Test action reaching ON state calls this method; it is
        never invoked from refresh, render, navigation, or any constructor
        or signal-wiring path.

        Guards (fail-closed, no partial execution):
          * Test Mode must be ON (this method is only called then).
          * A runner must actually be wired; otherwise the toggle is a pure
            UI action (Task 1 behavior, no execution).
          * There must be pending queue entries; an empty queue never
            reaches the runner.
          * The active AccountRecord must exist (AccountSource: the pass
            runs for the account the user has selected). Its existing
            ``Account`` object is obtained verbatim from the store — never
            resolved, inferred, fabricated or rebuilt — and passed to the
            runner.
          * The active account's identity (and its broker association) must
            match every queue entry; a mismatch never reaches the runner.

        The resolved ``Account`` object is handed to the runner explicitly
        (``runner.run(entries, account=account)``). No Account is ever
        resolved through a broker or the network, and no queue entry is
        changed by this method.

        Exactly once: one Test action = one ``runner.run(entries, account)``
        call. A blocked/failed result is stored on ``_last_test_run`` /
        ``_last_test_error`` for a later pass to surface; nothing is
        retried and the queue is never mutated by the pass itself.
        """
        if not self._test_mode:
            return

        record = self._active_account_record()
        if record is None:
            self._show_queue_status(STRINGS.TEST_SKIPPED_NO_ACCOUNT)
            return
        authorization = self._order_authorization(record.account_id, record.broker_name)
        if not authorization.authorized:
            self._show_queue_status(STRINGS.ORDER_AUTHORIZATION_REQUIRED)
            return

        runner = self._test_runner()
        if runner is None:
            # No runner wired (tests, or UI-only usage): pure toggle.
            return

        entries = list(self.order_queue.list_pending())
        if not entries:
            self._show_queue_status(STRINGS.TEST_SKIPPED_NO_ORDERS)
            return

        account = record.account
        for entry in entries:
            if (
                entry.account_id != account.account_id
                or entry.broker_name != record.broker_name
            ):
                self._show_queue_status(
                    STRINGS.TEST_SKIPPED_ACCOUNT_MISMATCH
                )
                return

        # UI-5 Task 4 (base display): the wall-clock moment this send is
        # issued. A UI-local stamp of the send moment only — never a broker
        # / exchange timestamp, never a latency measurement, and never read
        # again after the send (the send itself never waits for it).
        sent_at = datetime.now()

        # UI-5 Task 4 Stage 3 Task 3 — corrective contract: the feedback
        # binding is established BEFORE the send pass starts (lazily, once,
        # nothing new is started). A matching-engine registration event
        # emitted while the send is in flight must already find this
        # page's listener connected — never a lost event.
        self._ensure_feedback_binding()

        try:
            plan, execution_id, result = runner.run(
                entries, account=account
            )
        except Exception as exc:  # fail-closed: surface, never crash the UI
            self._last_test_error = str(exc)
            self._show_queue_status(
                STRINGS.TEST_ISSUE_FAILED.format(exc=exc)
            )
            # UI-6 Task 2/3: with the error recorded, the stored tuple is
            # the PREVIOUS run's — stale for display. Clear the stored
            # report and refresh the trace line and latency display RIGHT
            # HERE so no stale value (trace id or a previous run's
            # timings) ever lingers on screen until the next mode change
            # (label/list updates only — no execution impact).
            self._last_latency_report = None
            self._refresh_diagnostic_trace_display()
            self._refresh_diagnostic_latency_display()
            return

        self._last_test_run = (plan, execution_id, result)
        self._last_test_entries = list(entries)
        self._last_test_error = None
        # UI-6 Task 3: THIS run's EXISTING Block 8 report — the runner's
        # own ``last_report`` (None on the plain/test-double path). Taken
        # only from the runner of THIS completed run; a failed issue
        # attempt never leaves a previous run's report on display.
        self._last_latency_report = getattr(runner, "last_report", None)
        # UI-5 Task 3: capture this run's per-order results (aligned to the
        # entries) and render them exactly once — the single final refresh
        # of THIS Test run. The rows fully replace any previous run's rows
        # (no result history is kept).
        self._last_order_results = getattr(runner, "last_order_results", None)
        # UI-5 Task 4 (base display): one log row per SENT order, appended in
        # send order. This only records what this send already produced — it
        # changes nothing about what was sent.
        self._append_order_log_rows(
            self._last_test_entries, sent_at, self._last_order_results
        )
        # UI-5 Task 4 Stage 3 Task 3: bound to the EXISTING order-feedback
        # signal BEFORE the send pass started (see above).
        self._refresh_result_display()
        self._show_queue_status(
            STRINGS.TEST_ISSUED.format(execution_id=execution_id)
        )

    # ---------------------------------------------------------
    # Order Log (UI-5 Task 4, base display)
    # ---------------------------------------------------------

    def _append_order_log_rows(self, entries, sent_at, results):
        """
        Append ONE user-facing log row per SENT order, in send order.

        ``entries`` are the exact ``QueueEntry`` objects of this send in their
        exact send order and ``results`` are this send's real per-order
        results, aligned 1:1 to them (``None`` where no per-order result
        exists). Each row carries only what this send really produced:

            * ``account_id`` — verbatim from the exact QueueEntry;
            * ``symbol``     — the UI-layer symbol recorded at Add-to-Queue
                              from the real Instrument (never a broker
                              nscId / tseId);
            * ``description`` — the fixed user-facing reason of the REAL
                              per-order result, or nothing at all when no
                              per-order result exists;
            * ``sent_at``    — the UI's wall-clock send moment.

        The row also carries its correlation key — the exact sent ``Order``
        object — and, when this send's real result carried a ``decisionId``,
        that id is recorded in the page's decisionId maps (routing state
        only; the id itself is NEVER rendered) and in the queued-order-id
        set for the queue-status consumer. The queue-status field stays
        ``None`` (filled ONLY later by the existing Stage 2 queue-position
        feedback, rendered from the page's UI-layer display state) and the
        trading-core-registration field stays ``None``: they are filled
        ONLY later, by real feedback events. The broker-receipt moment, by
        contrast, is filled NOW when this send's real result already
        carried ``broker_received_at``. Rows are
        appended in send order and are never reordered or removed.
        """
        results = results if isinstance(results, list) else None
        decision_ids = self._decision_ids_for_last_run()
        for index, entry in enumerate(entries):
            order = entry.order
            result = None
            if results is not None and 0 <= index < len(results):
                result = results[index]
            symbol = self._order_symbols.get(id(order))
            # Stage 3 Task 4 — the broker-receipt moment the send's real
            # result already carried (captured in the Core at the
            # ``place_order`` return boundary). Rendered verbatim; never
            # recomputed, never guessed, never a UI clock read.
            broker_received = getattr(result, "broker_received_at", None)
            if not isinstance(broker_received, datetime):
                broker_received = None
            self.order_log.append(
                OrderLogRow(
                    sent_at=sent_at,
                    account_id=entry.account_id,
                    symbol=symbol if symbol else None,
                    description=self._order_log_description(result),
                    broker_received_at=broker_received,
                    key=order,
                )
            )
            decision_id = (
                decision_ids[index]
                if decision_ids is not None
                and 0 <= index < len(decision_ids)
                else None
            )
            if decision_id:
                # decisionId correlation (Stage 1 binding) only — never
                # rendered in any table cell. ``Order`` is an unhashable
                # dataclass, so the identity is ``id(order)`` — the same
                # convention the page already uses for ``_order_symbols``.
                # The reverse map is ACCOUNT-SCOPED (Block 9 Task 9B), so the
                # same decision_id on two accounts can never collide.
                self._decision_id_by_order[id(order)] = decision_id
                self._order_by_decision_key[
                    (entry.account_id, entry.broker_name, decision_id)
                ] = order
                self._queued_order_ids.add(id(order))
        self._refresh_order_log_display()

    def _decision_ids_for_last_run(self):
        """
        The decisionIds of the last send pass, aligned 1:1 to its entries.

        Read ONLY from what the real send produced: each entry's
        per-order ``OrderExecutionResult`` — a live success response carries
        ``data.decisionId`` (the existing Stage 1 field). A position with no
        real id stays ``None`` (dry-run, blocked or failed — there is no
        broker identity to route, and none is invented).
        """
        entries = self._last_test_entries or []
        results = self._last_order_results
        decision_ids = [None] * len(entries)
        for index in range(len(entries)):
            result = None
            if isinstance(results, list) and 0 <= index < len(results):
                result = results[index]
            response = getattr(result, "response", None)
            if not isinstance(response, dict):
                continue
            data = response.get("data")
            if not isinstance(data, dict):
                continue
            decision_id = data.get("decisionId")
            if isinstance(decision_id, str) and decision_id.strip():
                decision_ids[index] = decision_id
        return decision_ids

    @staticmethod
    def _call_feedback_binder_factory(factory, account_id, broker_name):
        """
        Call the binder factory compatibly.

        Production factories are account-aware ``(account_id, broker_name)
        -> binder``. A legacy/test zero-arg factory (``lambda: binder``) is
        also supported and bound to the resolved account, so the offline
        test doubles keep working. A factory failure yields ``None`` — the
        caller treats it as a fail-closed no-op.
        """
        try:
            inspect.signature(factory).bind(account_id, broker_name)
        except (TypeError, ValueError):
            return factory()
        return factory(account_id, broker_name)

    def _ensure_feedback_binding(self, account_id=None, broker_name=None):
        """
        Bind the page to one account's EXISTING order-feedback signals once.

        Block 9 Task 9B: bindings are PER ACCOUNT. When no identity is given
        the active account is used; when the account is unavailable nothing
        is bound (fail-closed, the base Stage 3 behavior). The factory
        returns an object exposing the existing ``order_registered`` and
        ``queue_position`` signals for exactly that account (production wires
        the account-scoped feedback runtime). It is called lazily at the
        first real send — never at construction — so a page without a factory
        simply never binds. Each account is connected exactly once: a second
        call for the same account is a no-op, so listener duplication is
        impossible. The page only ever uses those signals' existence: it
        never imports, names or starts any feedback/transport module and
        implements no queue logic. Any binding failure is swallowed as a
        no-op so the send path can never be disturbed by display wiring.
        """
        if account_id is None or broker_name is None:
            record = self._active_account_record()
            if record is None:
                return
            account_id, broker_name = record.account_id, record.broker_name
        key = (account_id, broker_name)
        if key in self._feedback_binders:
            return
        factory = self._feedback_binder_factory
        if factory is None:
            return
        try:
            binder = self._call_feedback_binder_factory(
                factory, account_id, broker_name
            )
        except Exception:  # noqa: BLE001 — display wiring never breaks the send
            return
        if binder is None:
            return
        signal = getattr(binder, "order_registered", None)
        if signal is None:
            return
        signal.connect(
            self._make_order_registered_handler(account_id, broker_name)
        )
        # Stage 3 Task 4 — the SAME bound object's EXISTING queue-position
        # signal, consumed only when it actually exists (an object that
        # carries no such signal simply binds the registration signal
        # alone — fail-closed, never an AttributeError).
        queue_signal = getattr(binder, "queue_position", None)
        if queue_signal is not None:
            queue_signal.connect(
                self._make_queue_position_handler(account_id, broker_name)
            )
        self._feedback_binders[key] = binder
        self._feedback_binder = binder

    def _make_order_registered_handler(self, account_id, broker_name):
        """A per-account registration slot that tags the account identity."""
        def handler(decision_id, accepted_at_ts, order_info):
            self._on_order_registered_from_feedback(
                account_id, broker_name, decision_id, accepted_at_ts,
                order_info,
            )
        return handler

    def _make_queue_position_handler(self, account_id, broker_name):
        """A per-account queue-position slot that tags the account identity."""
        def handler(decision_id, position):
            self._on_queue_position_from_feedback(
                account_id, broker_name, decision_id, position
            )
        return handler

    def _on_queue_position_from_feedback(
        self, account_id, broker_name, decision_id, position
    ):
        """
        The EXISTING Stage 2 queue-position feedback arrived.

        ``(account_id, broker_name, decision_id)`` resolves to the row of the
        EXACT sent order of that account through the page's own account-scoped
        map, and the position value it already computed fills that row's
        «وضعیت صف» cell. Guards (all fail-closed):

          * a non-string / blank decisionId is ignored;
          * a non-integer position (bool included) is ignored — nothing
            is fabricated;
          * an unknown / other-account key never creates or changes any row;
          * an order without a real decisionId is never routed to;
          * a duplicate delivery of the same value overwrites it with the
            SAME value — a no-op, idempotent.

        The value is stored in the page's UI-layer display state (keyed by
        the exact sent order's identity) and rendered into the row's
        «وضعیت صف» cell at the next refresh. ``OrderLog`` is never
        touched: its append-only Task 3 contract stays intact, no new row
        is created, the row count and order never change. The decisionId
        itself is never rendered in any cell.
        """
        if not isinstance(decision_id, str):
            return
        decision_id = decision_id.strip()
        if not decision_id:
            return
        if isinstance(position, bool) or not isinstance(position, int):
            return
        order = self._order_by_decision_key.get(
            (account_id, broker_name, decision_id)
        )
        if order is None:
            return  # unknown / other-account key — the UI stays untouched
        if id(order) not in self._queued_order_ids:
            return  # only orders a real send produced may be routed to
        # UI-layer display state only — the OrderLog model is untouched.
        self._queue_status_text_by_order[id(order)] = str(position)
        self._refresh_order_log_display()

    def _on_order_registered_from_feedback(
        self, account_id, broker_name, decision_id, accepted_at_ts, order_info
    ):
        """
        A real matching-engine registration event arrived.

        ``(account_id, broker_name, decision_id)`` is the account-scoped
        Stage 1 correlation key. It is resolved to the row of the EXACT sent
        order of that account through the page's own account-scoped map, and
        the REAL event timestamp (``accepted_at_ts`` — the epoch-seconds
        moment the event itself was received, carried through the existing
        feedback path) is stamped on that row, which then renders highlighted
        (green). Guards (all fail-closed):

          * a non-string / blank decisionId is ignored;
          * an unknown / other-account key never creates or changes any row
            (an event of one account can never alter another account's row,
            even when the decision_id is identical);
          * an event without a real timestamp stamps nothing;
          * a duplicate event carrying the same timestamp is a no-op —
            idempotent.
        """
        if not isinstance(decision_id, str):
            return
        decision_id = decision_id.strip()
        if not decision_id:
            return
        order = self._order_by_decision_key.get(
            (account_id, broker_name, decision_id)
        )
        if order is None:
            return  # unknown / other-account key — the UI stays untouched
        accepted_at = _epoch_to_local_datetime(accepted_at_ts)
        if accepted_at is None:
            return  # no real event timestamp — nothing may be invented
        self.order_log.update_core_registration(order, accepted_at)
        self._refresh_order_log_display()

    @staticmethod
    def _order_log_description(result):
        """
        The fixed, user-facing description for one sent order.

        Derived only from the REAL ``OrderExecutionResult`` of this send,
        through the existing fail-closed UI-5 Task 3 mapper — never from a
        raw result message, mode name, endpoint, exception, Trace ID or
        latency. ``None`` (rendered ``—``) when no per-order result exists,
        so nothing is ever fabricated for an order the UI knows nothing about.
        """
        if result is None:
            return None
        return _result_reason_for_status(_result_status_label(result))

    # ---------------------------------------------------------
    # UI-6 Task 1 — Diagnostic Mode display boundary
    # ---------------------------------------------------------

    def apply_mode(self, mode):
        """
        Apply the application's display boundary for ``mode`` (UI-6 Task 1).

        The mode STATE itself never lives here — it stays on MainWindow
        (the existing ``ui.main_window.ApplicationMode`` holder). This
        page only applies the DISPLAY consequence the mode asks for:

            * ``ApplicationMode.NORMAL``    → the diagnostic section is
              hidden.
            * ``ApplicationMode.DIAGNOSTIC`` → the diagnostic section may
              be shown.
            * Anything else (not one of the two real application modes) →
              the diagnostic section is HIDDEN and the internal visibility
              state is synced accordingly (fail-closed: an unknown value
              never leaves the section unmasked).

        Ordering, queue, result and feedback behavior are untouched:
        this is a visibility change only. The Trace ID line follows the
        same boundary: it exists only inside the (mode-gated) section and
        is re-rendered on every visibility change so the shown value is
        always THIS mode moment's current run value.
        """
        # ``ui.main_window`` is already imported at module level (the two
        # modules form one package surface since UI-1); the name is bound
        # here so this module never depends on the window class itself.
        global ApplicationMode
        if "ApplicationMode" not in globals():
            from ui.main_window import ApplicationMode  # noqa: local bind
        if mode is ApplicationMode.DIAGNOSTIC:
            visible = True
        else:  # ApplicationMode.NORMAL — and any non-valid value
            visible = False
        self._diagnostic_section_visible = visible
        self.diagnostic_section.setVisible(visible)
        # UI-6 Task 2/3: the Trace ID line and the latency display
        # re-render on every visibility change, so a shown value is always
        # the current run's value at the moment the boundary lets it be
        # seen.
        self._refresh_diagnostic_trace_display()
        self._refresh_diagnostic_latency_display()

    def is_diagnostic_visible(self):
        """The current diagnostic-section visibility (the page boundary)."""
        return self._diagnostic_section_visible

    def _diagnostic_trace_id(self):
        """
        The Trace ID of THIS run's real dispatch result — or ``None``.

        Source of truth: ``_last_test_run[2].trace_id`` — the
        ``DispatchResult`` the existing Test runner returned as the third
        member of its bridge triple (the Core built the id; the UI never
        creates, derives or substitutes one; ``execution_id`` is a
        DIFFERENT identifier and is never used).

        Strict result validation (fail-closed): ONLY a real
        ``core.dispatch_contracts.DispatchResult`` of THIS run is accepted.
        Any other object — a dict, a look-alike carrying a forged
        ``trace_id`` attribute, a previous run's result handed back — is
        rejected and renders the unavailable marker. The contract module
        imports ONLY the standard library and is imported lazily INSIDE
        this method (never at module import or window construction, where
        the UI-1 offline contracts forbid any ``core.*`` module); an
        import failure yields ``None``.

        Halted / failed runs: a real STOPPED pre-dispatch result carries
        ``trace_id=None`` and renders unavailable. When the last issue
        attempt FAILED (the runner raised — ``_last_test_error`` is set),
        the stored tuple is the PREVIOUS run's and is treated as stale:
        ``None`` is returned, so the previous run's trace id is never
        presented as the new run's. The line shows a trace id again only
        after a new run actually completes.
        """
        if self._last_test_error is not None:
            return None  # last issue attempt failed — stored run is stale
        if not isinstance(self._last_test_run, tuple) or len(
            self._last_test_run
        ) != 3:
            return None
        result = self._last_test_run[2]
        try:
            # Stdlib-only contract module; never imported at construction
            # (the no-run guard in the trace renderer prevents that).
            from core.dispatch_contracts import DispatchResult
        except ImportError:  # pragma: no cover — fail-closed
            return None
        if not isinstance(result, DispatchResult):
            return None
        trace_id = result.trace_id
        if not isinstance(trace_id, str):
            return None
        text = trace_id.strip()
        return text or None

    def _refresh_diagnostic_display(self):
        """
        Render the diagnostic section ONLY from real execution results.

        The content is the per-order execution verdict of the last Test
        pass — the SAME verdicts the Task 3 Test Results area shows,
        derived from the REAL ``OrderExecutionResult`` objects
        (``_result_status_label``), in the exact result order — plus the
        ONE dispatch-level Trace ID line (UI-6 Task 2: the Core-built
        ``DispatchResult.trace_id`` of THIS run, never a new or substitute
        id, never attributed to a single order). No new measurement is
        taken, no value is invented: without a Test pass the section
        shows its real empty state. Called on the single final refresh of
        a run and on visibility changes, never from construction or
        navigation.
        """
        self.diagnostic_list.clear()
        entries = self._last_test_entries or []
        results = self._last_order_results
        for index, entry in enumerate(entries):
            result = None
            if isinstance(results, list) and 0 <= index < len(results):
                result = results[index]
            order = entry.order
            symbol = (
                self._order_symbols.get(id(order), "")
                or RESULT_SYMBOL_UNKNOWN
            )
            side_label = dict(SIDE_LABELS).get(
                getattr(order, "side", None),
                str(getattr(order, "side", "")),
            )
            verdict = _result_status_label(result)
            text = (
                DIAGNOSTIC_ENTRY_PREFIX.format(position=index + 1)
                + f"{symbol} | {side_label} | "
                + DIAGNOSTIC_VERDICT_PREFIX
                + verdict
            )
            item = QListWidgetItem(text, self.diagnostic_list)
            # Fail-closed display guard: the diagnostic section is still a
            # user-facing surface — no technical payload (exception text,
            # mode name, broker response, decisionId, Trace ID) is ever
            # attached to its items.
            item.setData(Qt.UserRole, None)
        if entries:
            self.diagnostic_status_label.setText(
                f"{len(entries)} order(s) in the last Test pass"
            )
        else:
            self.diagnostic_status_label.setText(DIAGNOSTIC_EMPTY_STATE)
        # UI-6 Task 2/3: keep the dispatch-level Trace ID line and the
        # latency/execution diagnostics in sync with the run these
        # verdicts belong to (both render only when the display boundary
        # lets them be seen).
        self._refresh_diagnostic_trace_display()
        self._refresh_diagnostic_latency_display()

    def _diagnostic_latency_report(self):
        """
        THIS run's EXISTING Block 8 report — or ``None``.

        Source of truth: the runner's own ``last_report`` of THIS
        completed run (stored in ``_last_latency_report`` at run time —
        the ``DispatchLatencyReport`` the Core's
        ``dispatch_with_latency`` already built). Read-only: the UI never
        measures, re-derives, sums unlike categories or invents a value;
        without a completed run (failed issue, no run, plain/test-double
        path) ``None`` is returned so the previous run's timings are
        never shown as the new run's.
        """
        if self._last_test_error is not None:
            return None  # failed issue: never present stale timings
        return self._last_latency_report

    def _refresh_diagnostic_latency_display(self):
        """
        Render the latency/execution diagnostics of THIS run's EXISTING
        Block 8 report (UI-6 Task 3) — the four SEPARATE categories:

        1. the total dispatch window (``dispatch_duration``);
        2. each recorded internal stage duration per order (``plan_item``,
           ``plan_account``, ``instrument_resolution``, ``order_engine_path``),
           with missing stages explicitly unavailable;
        3. the Broker/API round trips the report actually recorded, with
           the recorded operation name — the FULL measured call, never
           labelled network latency, never summed into the stages;
        4. the application/Broker split ONLY as the report itself states
           it (``application_side_ns`` per record; ``None`` — e.g. across
           different clocks — stays ناموجود, never estimated).

        Source: the runner's own ``last_report`` of THIS completed run.
        Per-order detail is matched ONLY by the real ``Order`` object
        identity (never by list order or symbol text); an unmatched order
        shows ناموجود. Without a report (no run, failed issue, plain
        path) everything shows ناموجود — never a fabricated zero. The
        no-report early return keeps construction free of any ``core.*``
        import. Rendering only updates widgets; no ordering/execution
        behavior is touched.
        """
        self.latency_detail_list.clear()
        report = self._diagnostic_latency_report()
        if report is None:
            self.latency_total_label.setText(
                DIAGNOSTIC_LATENCY_TOTAL_LABEL + DIAGNOSTIC_VALUE_UNAVAILABLE
            )
            return

        total_ms = _ns_to_ms_text(
            getattr(report, "dispatch_duration", None)
        )
        self.latency_total_label.setText(
            DIAGNOSTIC_LATENCY_TOTAL_LABEL
            + (total_ms if total_ms is not None else DIAGNOSTIC_VALUE_UNAVAILABLE)
        )

        # Categories 2/3 are rendered from each record and call, not from
        # distributions or cross-order totals. Each value therefore has
        # an explicit order identity and cannot be mistaken for a median,
        # sum, or single call representing several orders.

        # Category 4 — the application/Broker split, ONLY as the report
        # states it (shared-clock values; a cross-clock ``None`` stays
        # ناموجود — never estimated, never 0). Per-order identity: the
        # record's execution_result owns the SAME Order object the run
        # dispatched; the display label is that order's identity-keyed
        # symbol (the page's own map — never a list-position or symbol
        # guess).
        records = getattr(report, "orders", None) or []
        for record in records:
            result = getattr(record, "execution_result", None)
            order = getattr(result, "order", None)
            order_text = (
                self._order_symbols.get(id(order), "")
                if order is not None
                else ""
            ) or RESULT_SYMBOL_UNKNOWN

            # Category 2 — the recorded duration for each named stage of
            # THIS order. Missing stages are explicit, never treated as 0.
            for stage in DIAGNOSTIC_LATENCY_STAGES:
                duration = record.duration_ns(stage)
                stage_ms = _ns_to_ms_text(duration)
                self._add_diagnostic_latency_item(
                    DIAGNOSTIC_LATENCY_STAGE_PREFIX.format(
                        order=order_text, stage=stage
                    )
                    + (
                        stage_ms
                        if stage_ms is not None
                        else DIAGNOSTIC_VALUE_UNAVAILABLE
                    )
                )

            # Category 3 — every measured Broker/API call for THIS order,
            # kept as an individual full call with its recorded operation.
            for call_number, call in enumerate(
                getattr(record, "broker_api_calls", None) or [], start=1
            ):
                call_ms = _ns_to_ms_text(getattr(call, "duration_ns", None))
                self._add_diagnostic_latency_item(
                    DIAGNOSTIC_LATENCY_BROKER_PREFIX.format(
                        order=order_text,
                        operation=getattr(call, "operation", "unknown"),
                        call_number=call_number,
                    )
                    + (
                        call_ms
                        if call_ms is not None
                        else DIAGNOSTIC_VALUE_UNAVAILABLE
                    )
                )
            if not (getattr(record, "broker_api_calls", None) or []):
                self._add_diagnostic_latency_item(
                    DIAGNOSTIC_LATENCY_BROKER_NONE.format(order=order_text)
                )

            for label, field_name in DIAGNOSTIC_LATENCY_APP_FIELDS:
                value_ms = _ns_to_ms_text(
                    getattr(record, field_name, None)
                )
                self._add_diagnostic_latency_item(
                    label.format(order=order_text)
                    + (
                        value_ms
                        if value_ms is not None
                        else DIAGNOSTIC_VALUE_UNAVAILABLE
                    )
                )
        if not records:
            # A report without order records has no stage or Broker/API
            # measurements; make that absence visible rather than implying
            # a zero or silently dropping the categories.
            for stage in DIAGNOSTIC_LATENCY_STAGES:
                self._add_diagnostic_latency_item(
                    DIAGNOSTIC_LATENCY_STAGE_PREFIX.format(
                        order=RESULT_SYMBOL_UNKNOWN, stage=stage
                    ) + DIAGNOSTIC_VALUE_UNAVAILABLE
                )
            self._add_diagnostic_latency_item(
                DIAGNOSTIC_LATENCY_BROKER_NONE.format(
                    order=RESULT_SYMBOL_UNKNOWN
                )
            )

    def _add_diagnostic_latency_item(self, text):
        """ONE read-only list row; never carries a technical payload."""
        item = QListWidgetItem(text, self.latency_detail_list)
        item.setData(Qt.UserRole, None)

    def _refresh_diagnostic_trace_display(self):
        """
        Render the ONE dispatch-level Trace ID line (UI-6 Task 2).

        The value is ``_diagnostic_trace_id()`` — the Core-built
        ``DispatchResult.trace_id`` of THIS run, verbatim. Nothing here
        creates, derives, defaults or substitutes an id: without a real
        trace id (no dispatch, a stopped run, a failed issue attempt,
        ``None``, blank, a non-result object) the line shows the real
        unavailable marker. ``execution_id`` — a DIFFERENT identifier —
        is never shown in its place. Rendering only updates one label; no
        ordering/execution behavior is touched. The no-run early return
        keeps window construction free of any ``core.*`` import (the
        extractor's lazy import runs only once a run actually exists).
        """
        if self._last_test_run is None:
            self.trace_id_label.setText(
                DIAGNOSTIC_TRACE_LABEL + DIAGNOSTIC_TRACE_UNAVAILABLE
            )
            return
        trace_id = self._diagnostic_trace_id()
        if trace_id:
            self.trace_id_label.setText(
                DIAGNOSTIC_TRACE_LABEL + trace_id
            )
        else:
            self.trace_id_label.setText(
                DIAGNOSTIC_TRACE_LABEL + DIAGNOSTIC_TRACE_UNAVAILABLE
            )

    def _refresh_order_log_display(self):
        """
        Re-render the order-log table ONLY from the in-memory ``OrderLog``
        plus the page's UI-layer queue-status display state.

        The table is rebuilt from ``OrderLog.rows()`` — the rows in send
        order — with each row's seven cells placed by its own column order;
        the «وضعیت صف» cell shows ONLY the value the EXISTING Stage 2
        feedback signal delivered for that exact order (UI-layer state,
        keyed by the row's order identity) or ``—`` when none arrived.
        This render never creates, updates or invents a row: it mirrors
        what the send action appended plus the two feedback values (the
        matching-engine registration stamp — model state — and the
        queue-position value — UI-layer display state). Rows whose order
        was REALLY registered in the trading core (a real matching-engine
        registration event) are rendered with the registered highlight
        (green); every other row is unhighlighted.
        """
        rows = self.order_log.rows()
        self.order_log_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            cells = list(row.cells())
            # Stage 3 Task 4 — the queue-status cell renders the page's
            # UI-layer display state for THIS row's order (only what the
            # existing Stage 2 signal delivered); ``—`` when nothing did.
            # The model row is read-only here: no contract change, no
            # invented value.
            position_text = self._queue_status_text_by_order.get(
                id(row.key)
            )
            cells[COLUMN_QUEUE_STATUS] = (
                position_text if position_text else EMPTY_CELL
            )
            for column, text in enumerate(cells):
                self.order_log_table.setItem(
                    row_index, column, QTableWidgetItem(text)
                )
            if row.registered_in_core is True:
                for column in range(len(ORDER_LOG_COLUMNS)):
                    item = self.order_log_table.item(row_index, column)
                    if item is not None:
                        item.setBackground(
                            QColor(CORE_REGISTERED_ROW_COLOR)
                        )

    def _refresh_result_display(self):
        """
        Render the per-order results of the last successful Test run.

        Called EXACTLY ONCE per successful run (the final refresh, at the
        end of ``_run_test_pass``); it is never invoked from construction,
        navigation, refresh/render or toggle-off paths. One call clears and
        repopulates, so a new run fully replaces the previous rows.

        One visible row per queued order, in exact queue order:

            حساب {account_id} | {symbol} | {side} | {status} | {reason}

        Everything is user-facing only: the account id and side label come
        from the exact QueueEntry/Order, the display symbol from the UI-layer
        map (recorded at Add-to-Queue from the real Instrument), and the
        verdict from the fail-closed status mapper. No nscId/tseId, mode
        name, message, Trace ID, latency, M6-* label, endpoint, broker
        response or exception text is ever rendered here.
        """
        self.result_list.clear()
        entries = self._last_test_entries or []
        results = self._last_order_results
        for index, entry in enumerate(entries):
            result = None
            if isinstance(results, list) and 0 <= index < len(results):
                result = results[index]
            order = entry.order
            symbol = (
                self._order_symbols.get(id(order), "")
                or RESULT_SYMBOL_UNKNOWN
            )
            side_label = dict(SIDE_LABELS).get(
                getattr(order, "side", None),
                str(getattr(order, "side", "")),
            )
            status = _result_status_label(result)
            text = (
                f"\u062d\u0633\u0627\u0628 {entry.account_id} | {symbol} | "
                f"{side_label} | {status} | "
                f"{_result_reason_for_status(status)}"
            )
            QListWidgetItem(text, self.result_list)
        if entries:
            self.result_status_label.setText(
                f"{len(entries)} result(s)"
            )
        else:
            self.result_status_label.setText(RESULT_EMPTY_STATE)
        # UI-6 Task 1: the diagnostic section mirrors the same real
        # verdicts at the single final refresh (it renders only when the
        # display boundary lets it — visibility is mode-gated).
        self._refresh_diagnostic_display()

    def _refresh_test_button_state(self):
        """
        Update the Test button enabled/disabled state based on UI conditions.

        The Test button is disabled when:
          * the queue is empty, OR
          * the required selected account is missing, OR
          * the required selected instrument is missing.

        It becomes enabled only when all three conditions are valid.

        The queue is consulted only when one actually exists (an injected
        queue or a lazily built one) — an untouched page is trivially
        empty, so the lazy ``core.order_queue`` import is never forced on
        a plain navigation or refresh.
        """
        has_queue = False
        if (
            self._injected_order_queue is not None
            or self._default_queue is not None
        ):
            has_queue = len(self.order_queue.list_pending()) > 0
        has_account = self._active_account_record() is not None
        has_instrument = self.config.selected_instrument is not None

        # UI-7 Task 2: while a schedule is accepted the Test action is one
        # of the locked controls — Stop is the only active button then.
        if self._schedule_locked:
            self.test_button.setEnabled(False)
            return

        self.test_button.setEnabled(has_queue and has_account and has_instrument)

    # ---------------------------------------------------------
    # Symbol info / status display
    # ---------------------------------------------------------

    def _refresh_symbol_info(self):
        instrument = self.config.selected_instrument
        if instrument is None:
            self.symbol_name_label.setText("-")
        else:
            # Display comes from the REAL Instrument object only.
            market = getattr(instrument, "market", None)
            market_part = f" ({market})" if market else ""
            self.symbol_name_label.setText(
                f"{getattr(instrument, 'symbol', '')} - "
                f"{getattr(instrument, 'name', '')}{market_part}"
            )
        self._invalidate_auto_amount()
        self._refresh_amounts()
        # Fail-closed display: without a verified source this is never
        # "tradable"/"permitted".
        self.symbol_status_label.setText(
            STRINGS.LABEL_SYMBOL_STATUS_PREFIX
            + _symbol_status_display(self.config.symbol_status())
        )

    # ---------------------------------------------------------
    # Side / Price / Quantity
    # ---------------------------------------------------------

    # ---------------------------------------------------------
    # Inline validation message (UI-9.4)
    # ---------------------------------------------------------

    def _show_validation_error(self, message):
        """
        Show one inline error on the order form (UI-9.4).

        Replaces the former blocking ``QMessageBox``: the message is the
        same Persian ``STRINGS.DIALOG_*`` text the dialog carried. A new
        error simply replaces the previous one.
        """
        self.validation_error_label.setText(message)
        self.validation_error_label.setVisible(bool(message))

    def _clear_validation_error(self):
        """
        Clear the inline error after a successful action (UI-9.4).

        The label is emptied *and* hidden, so an error-free form occupies
        exactly the space it did before this task.
        """
        self.validation_error_label.clear()
        self.validation_error_label.setVisible(False)

    def _on_side_selected(self, side):
        self._invalidate_buy_preview()
        self._invalidate_auto_amount()
        try:
            self.config.set_side(side)
        except OrderConfigError:  # pragma: no cover — buttons are fixed
            self._show_validation_error(STRINGS.DIALOG_INVALID_SIDE)
        else:
            self._clear_validation_error()
            self._apply_order_panel_halo(side)
            # A quantity ceiling depends on the side; an in-flight response
            # for the previous side must never land on the new side.
            self._invalidate_limit_requests()

    def _apply_order_panel_halo(self, side):
        """Give the order panel a soft side-keyed halo and inner tint.

        The glow is a blurred, translucent drop shadow around the panel; the
        inner tint is the panel surface blended with the same theme colour.
        Both are scoped to this panel's object name, so the global theme and
        every other group box keep their existing styling. Only the theme's
        success/danger tokens are used — no new colour is invented.
        """
        color = PALETTE["success"] if side == BUY else PALETTE["danger"]
        center_tint = self._blend_with_surface(color, 0.03)
        middle_tint = self._blend_with_surface(color, 0.10)
        edge_tint = self._blend_with_surface(color, 0.22)
        self.form_group.setStyleSheet(
            "QGroupBox#orderConfigPanel {"
            f" border: 1px solid {color};"
            " background-color: qradialgradient("
            "cx:0.5, cy:0.5, radius:0.6, fx:0.5, fy:0.5,"
            f" stop:0 {center_tint}, stop:0.55 {middle_tint},"
            f" stop:1 {edge_tint});"
            "}"
        )

        glow = QColor(color)
        glow.setAlpha(130)
        if self._order_panel_glow is None:
            self._order_panel_glow = QGraphicsDropShadowEffect(self.form_group)
            self._order_panel_glow.setOffset(0, 0)
            self._order_panel_glow.setBlurRadius(40)
            self.form_group.setGraphicsEffect(self._order_panel_glow)
        self._order_panel_glow.setColor(glow)

    @staticmethod
    def _blend_with_surface(color, ratio=0.12):
        """Blend a theme accent into the panel surface for a faint inner tint."""
        surface = QColor(PALETTE["surface"])
        accent = QColor(color)
        return QColor(
            round(surface.red() * (1 - ratio) + accent.red() * ratio),
            round(surface.green() * (1 - ratio) + accent.green() * ratio),
            round(surface.blue() * (1 - ratio) + accent.blue() * ratio),
        ).name()

    def _on_price_changed(self):
        self._invalidate_buy_preview()
        self._invalidate_auto_amount()
        self._auto_amount_timer.stop()
        text = self.price_input.text().strip()
        if not text:
            self.config.price = None
            self._clear_validation_error()
            self._refresh_amounts()
            self.base_amount_label.setText(STRINGS.VALUE_EMPTY_DASH)
            return
        try:
            # The Core Order contract is price: int — integer input only.
            # Fractional input ("15000.5") is rejected, and the previous
            # valid state is preserved.
            self.config.set_price(int(text))
        except (OrderConfigError, ValueError):
            self._show_validation_error(STRINGS.DIALOG_INVALID_PRICE)
            self.base_amount_label.setText(STRINGS.VALUE_EMPTY_DASH)
            self.fee_label.setText("نامشخص؛ قیمت معتبر نیست")
            self.final_amount_label.setText(STRINGS.VALUE_NOT_AVAILABLE)
            return
        else:
            self._clear_validation_error()
        self._refresh_amounts()
        self._start_auto_amount()

    def _on_quantity_changed(self):
        self._invalidate_auto_amount()
        self._auto_amount_timer.stop()
        text = self.quantity_input.text().strip()
        if not text:
            self.config.quantity = None
            self._clear_validation_error()
            self._refresh_amounts()
            self.base_amount_label.setText(STRINGS.VALUE_EMPTY_DASH)
            return
        try:
            # The Core Order contract is quantity: int — integer input
            # only. Fractional input ("500.5") is rejected, and the
            # previous valid state is preserved.
            self.config.set_quantity(int(text))
        except (OrderConfigError, ValueError):
            self._show_validation_error(STRINGS.DIALOG_INVALID_QUANTITY)
            self.base_amount_label.setText(STRINGS.VALUE_EMPTY_DASH)
            self.fee_label.setText("نامشخص؛ تعداد معتبر نیست")
            self.final_amount_label.setText(STRINGS.VALUE_NOT_AVAILABLE)
            return
        else:
            self._clear_validation_error()
        self._refresh_amounts()
        self._start_auto_amount()

    # ---------------------------------------------------------
    # Daily price / broker quantity limit arrows
    # ---------------------------------------------------------

    def _invalidate_limit_requests(self):
        """Discard every in-flight limit response (symbol/account/side change)."""
        self._price_limits_request_id += 1
        self._quantity_limits_request_id += 1
        self._price_limits_scope = None
        self._quantity_limits_scope = None

    def _request_price_limit(self, kind):
        """Fetch and place one TSETMC daily price bound for the selected symbol."""
        if kind not in (PRICE_LIMIT_MAX, PRICE_LIMIT_MIN):
            return
        instrument = self.config.selected_instrument
        ins_code = getattr(instrument, "ins_code", None)
        if not ins_code:
            self._show_validation_error(STRINGS.LIMIT_PRICE_NO_SYMBOL)
            return

        self._price_limits_request_id += 1
        request_id = self._price_limits_request_id
        identity = self._current_read_identity(ins_code)
        self._price_limits_scope = (request_id, ins_code, identity, kind)
        self._clear_validation_error()

        injected_factory = self._price_limits_factory

        def limits_factory():
            if injected_factory is not None:
                return injected_factory()
            # Reuse the EXISTING market seam (SymbolResolver owns the
            # TSETMC client) instead of importing market.tsetmc from ui/.
            if self._resolver_factory is not None:
                return self._resolver_factory()
            from market.symbol_resolver import SymbolResolver

            return SymbolResolver()

        worker = _PriceLimitsWorker(
            ins_code, limits_factory, request_id, parent=self
        )
        self._price_limits_worker = worker
        self._price_limits_thread = worker
        worker.limits_succeeded.connect(self._on_price_limits_succeeded)
        worker.limits_failed.connect(self._on_price_limits_failed)
        worker.finished.connect(
            lambda w=worker: self._forget_price_limits_worker(w)
        )
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _forget_price_limits_worker(self, worker):
        if self._price_limits_thread is worker:
            self._price_limits_thread = None
            self._price_limits_worker = None

    def wait_for_limit_workers(self, timeout_ms=5000):
        """Wait (bounded) for any price/quantity limit worker to finish."""
        for thread in (self._price_limits_thread, self._quantity_limits_thread):
            if thread is not None and not thread.wait(timeout_ms):
                raise TimeoutError("limit worker thread did not finish")

    def _on_price_limits_succeeded(self, request_id, ins_code, limits):
        scope = self._price_limits_scope
        if (request_id != self._price_limits_request_id or scope is None):
            return  # stale request — discarded deterministically
        _, scope_ins_code, scope_identity, kind = scope
        current_ins_code = getattr(
            self.config.selected_instrument, "ins_code", None
        )
        if (
            ins_code != scope_ins_code
            or current_ins_code != scope_ins_code
            or self._current_read_identity(scope_ins_code) != scope_identity
        ):
            return  # symbol/account changed mid-flight — never apply

        if kind == PRICE_LIMIT_MAX:
            value = getattr(limits, "price_max", None)
        else:
            value = getattr(limits, "price_min", None)
        value = _valid_limit(value, allow_zero=False)
        if value is None:
            self._show_validation_error(STRINGS.LIMIT_PRICE_INVALID)
            return

        # Go through the existing input validation path so
        # OrderConfiguration and the visible field stay in sync.
        self.price_input.setText(str(value))
        self._on_price_changed()

    def _on_price_limits_failed(self, request_id, ins_code, message):
        scope = self._price_limits_scope
        if (request_id != self._price_limits_request_id or scope is None):
            return  # stale failure — never shown
        _, scope_ins_code, scope_identity, _kind = scope
        current_ins_code = getattr(
            self.config.selected_instrument, "ins_code", None
        )
        if (
            ins_code != scope_ins_code
            or current_ins_code != scope_ins_code
            or self._current_read_identity(scope_ins_code) != scope_identity
        ):
            return
        self._show_validation_error(STRINGS.LIMIT_PRICE_UNAVAILABLE)

    def _request_quantity_limit(self, kind):
        """Fetch and place one account-scoped broker quantity bound."""
        if kind not in (PRICE_LIMIT_MAX, PRICE_LIMIT_MIN):
            return
        record = self._active_account_record()
        if record is None:
            self._show_validation_error(STRINGS.LIMIT_QUANTITY_NO_ACCOUNT)
            return
        instrument = self.config.selected_instrument
        ins_code = getattr(instrument, "ins_code", None)
        if not ins_code:
            self._show_validation_error(STRINGS.LIMIT_PRICE_NO_SYMBOL)
            return
        side = self.config.side
        if side not in (BUY, SELL):
            self._show_validation_error(STRINGS.DIALOG_INVALID_SIDE)
            return

        identity = (record.account_id, record.broker_name, ins_code)
        if self._current_read_identity(ins_code) != identity:
            self._show_validation_error(STRINGS.LIMIT_QUANTITY_NO_ACCOUNT)
            return

        self._quantity_limits_request_id += 1
        request_id = self._quantity_limits_request_id
        self._quantity_limits_scope = (
            request_id, ins_code, identity, side, kind
        )
        self._clear_validation_error()

        injected_factory = (
            self._quantity_limits_factory or self._order_identity_factory
        )

        def provider_factory():
            if injected_factory is None:
                return None
            try:
                signature = inspect.signature(injected_factory)
                signature.bind(record.account_id, record.broker_name)
            except (TypeError, ValueError):
                return injected_factory()
            return injected_factory(
                record.account_id, record.broker_name
            )

        worker = _QuantityLimitsWorker(
            ins_code, provider_factory, request_id, parent=self
        )
        self._quantity_limits_worker = worker
        self._quantity_limits_thread = worker
        worker.limits_succeeded.connect(self._on_quantity_limits_succeeded)
        worker.limits_failed.connect(self._on_quantity_limits_failed)
        worker.finished.connect(
            lambda w=worker: self._forget_quantity_limits_worker(w)
        )
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _forget_quantity_limits_worker(self, worker):
        if self._quantity_limits_thread is worker:
            self._quantity_limits_thread = None
            self._quantity_limits_worker = None

    def _on_quantity_limits_succeeded(
        self, request_id, ins_code, broker_instrument
    ):
        scope = self._quantity_limits_scope
        if (request_id != self._quantity_limits_request_id or scope is None):
            return  # stale request — discarded deterministically
        _, scope_ins_code, scope_identity, scope_side, kind = scope
        current_ins_code = getattr(
            self.config.selected_instrument, "ins_code", None
        )
        if (
            ins_code != scope_ins_code
            or current_ins_code != scope_ins_code
            or self._current_read_identity(scope_ins_code) != scope_identity
            or self.config.side != scope_side
        ):
            return  # symbol/account/side changed mid-flight — never apply

        if kind == PRICE_LIMIT_MAX:
            field = (
                "maximum_order_quantity_for_buy"
                if scope_side == BUY
                else "maximum_order_quantity_for_sell"
            )
        else:
            field = "minimum_order_quantity"
        value = _valid_limit(getattr(broker_instrument, field, None))
        if value is None:
            self._show_validation_error(STRINGS.LIMIT_QUANTITY_INVALID)
            return

        # Same validation path as manual entry, keeping state and text aligned.
        self.quantity_input.setText(str(value))
        self._on_quantity_changed()

    def _on_quantity_limits_failed(self, request_id, ins_code, message):
        scope = self._quantity_limits_scope
        if (request_id != self._quantity_limits_request_id or scope is None):
            return  # stale failure — never shown
        _, scope_ins_code, scope_identity, scope_side, _kind = scope
        current_ins_code = getattr(
            self.config.selected_instrument, "ins_code", None
        )
        if (
            ins_code != scope_ins_code
            or current_ins_code != scope_ins_code
            or self._current_read_identity(scope_ins_code) != scope_identity
            or self.config.side != scope_side
        ):
            return
        self._show_validation_error(STRINGS.LIMIT_QUANTITY_UNAVAILABLE)

    # ---------------------------------------------------------
    # Schedule & clock (UI-7 Tasks 1 and 2)
    # ---------------------------------------------------------
    # Task 1 owns the window configuration and validation: applying a
    # schedule validates the inputs through the existing Block 3
    # ``DispatchTiming`` contract, generates the moments with the existing
    # ``TimedDispatchScheduler``, and shows the result before anything runs.

    def set_clock_service_factory(self, factory):
        """
        Inject the clock-service seam (production and tests).

        The factory receives the injectable transport and returns a
        ``MarketClockService``. Leaving it ``None`` keeps the default
        lazily-created service, which still performs no network call until
        a refresh is requested.
        """
        self._clock_service_factory = factory

    def set_clock_transport(self, transport):
        """
        Inject the HTTP transport used by the default clock service.

        Replacing the transport rebuilds the clock service, so a new
        transport can never be silently ignored by an already-built
        service. The displayed clock status is cleared with it: a reading
        taken through the previous transport does not describe the new one.
        """
        self._clock_transport = transport
        self._clock_service = None
        self._clock_status = None

    def clock_service(self):
        """Return the page's clock service, creating it on first use."""
        if self._clock_service is None:
            factory = self._clock_service_factory
            if factory is not None:
                self._clock_service = factory(self._clock_transport)
            else:
                self._clock_service = MarketClockService(
                    transport=self._clock_transport
                )
            self._clock_transport = self._clock_service.transport
        return self._clock_service

    def _refresh_clock_display(self):
        status = self._clock_status
        if status is None:
            status = self.clock_service().status()
            self._clock_status = status
        self.clock_status_label.setText(describe_clock(status))
        self.sync_status_label.setText(self._sync_state_text())
        self._refresh_market_clock_row()

    def _refresh_market_clock_row(self):
        """
        UI-10: render the live clock row (the attribute named
        ``schedule_timezone_label``). The value is the current
        application time on the clock service's own time base —
        ``now_utc + applied_offset``, expressed in Tehran, exactly the
        time the schedule inputs and the countdown use. Shown as
        ``HH:MM:SS`` only: the market source is second-resolution by
        contract (MARKET_PRECISION_NOTE) and no sub-second precision is
        ever claimed. Until a market sync has completed (or before the
        service even exists) the row shows the program time and says so
        explicitly — the program clock is never dressed up as a market
        clock. This is a pure DISPLAY read: it never STARTS the service
        (construction stays offline — tests inject their own factory
        after the page is built), it starts no request and it does not
        touch the locked schedule time base.
        """
        time_text = datetime.now().astimezone(TEHRAN_TIMEZONE).strftime(
            "%H:%M:%S"
        )
        status = self._clock_status
        service = self._clock_service  # deliberately NOT clock_service()
        if service is not None:
            try:
                time_text = service.now_tehran().strftime("%H:%M:%S")
            except Exception:  # pragma: no cover — never raise on display
                pass
        if (
            service is None
            or status is None
            or status.source is not ClockSource.MARKET
            or not service.is_sync_fresh()
        ):
            time_text = f"{time_text} {STRINGS.CLOCK_PROGRAM_TIME_SUFFIX}"
        self.schedule_timezone_label.setText(time_text)

    def _sync_state_text(self) -> str:
        """
        One line describing the RESULT of the last clock sync.

        Shows the source, the estimated offset, the uncertainty band and
        the freshness of the reading. Freshness comes from the service's
        MONOTONIC measurement, so a system-clock step can neither renew a
        stale reading nor expire a fresh one. A stale, failed or missing
        reading is never dressed up as a market clock, and no
        millisecond precision is ever claimed for a second-resolution
        TSETMC answer.
        """
        service = self.clock_service()
        status = (
            self._clock_status
            if self._clock_status is not None
            else service.status()
        )
        # Freshness is always read from the LIVE service, measured on its
        # monotonic clock, so the line ages honestly between two syncs and
        # a system-clock step can neither renew a stale reading nor expire
        # a fresh one.
        age = service.sync_age_seconds()
        if age is None:
            return SYNC_STATE_FAILED if service.last_sync_attempt else SYNC_STATE_NEVER
        if age > SCHEDULE_SYNC_MAX_AGE_SECONDS:
            return (
                STRINGS.SYNC_STALE.format(
                age=STRINGS.format_technical(age),
                limit=STRINGS.format_technical(SCHEDULE_SYNC_MAX_AGE_SECONDS),
                button=SYNC_BUTTON_LABEL,
            )
            )
        text = (
            f"{STRINGS.SYNC_OK_PREFIX.format(age=STRINGS.format_technical(age), source=status.source.value)}"
            f"{STRINGS.SYNC_OK_OFFSET.format(offset=format_offset(status.applied_offset))}"
            f"{STRINGS.SYNC_OK_UNCERTAINTY.format(uncertainty=format_uncertainty(status.uncertainty))}"
            f"{status.precision_note}"
        )
        if not service.last_sync_ok:
            text += STRINGS.SYNC_OK_FAILED_SUFFIX
        return text

    def _on_clock_succeeded(self, sample):
        self._clock_status = self.clock_service().observe(sample)
        self._refresh_clock_display()
        self._on_clock_sync_finished(True)
        self._apply_pending_schedule_if_any()

    def _on_clock_failed(self, reason):
        self._clock_status = self.clock_service().mark_market_unavailable(reason)
        self._refresh_clock_display()
        self._on_clock_sync_finished(False)
        self._apply_pending_schedule_if_any()

    def _start_clock_refresh(self):
        """
        Begin one non-blocking clock refresh; ``False`` if already running.

        The network call always happens on a worker thread, never on the
        GUI thread, so Apply and Refresh both stay responsive.
        """
        service = self.clock_service()
        if self._clock_thread is not None and self._clock_thread.isRunning():
            return False
        worker = MarketClockWorker(
            transport=service.transport,
            now_utc=service.now_utc,
            parent=self,
        )
        self._clock_worker = worker
        worker.clock_succeeded.connect(self._on_clock_succeeded)
        worker.clock_failed.connect(self._on_clock_failed)
        worker.finished.connect(self._on_clock_worker_finished)
        self._clock_thread = worker
        self.sync_status_label.setText(SYNC_STATE_IN_PROGRESS)
        worker.start()
        return True

    def _on_refresh_clock(self):
        """Fetch market time off the GUI thread; never blocks the UI."""
        self._start_clock_refresh()

    def _on_clock_worker_finished(self):
        worker = self._clock_worker
        self._clock_worker = None
        self._clock_thread = None
        if worker is not None:
            worker.deleteLater()

    # --- UI-7 Task 2: manual sync & startup sync --------------------------

    def _clock_sync_in_progress(self) -> bool:
        """True while a clock refresh worker is still running."""
        thread = self._clock_thread
        return thread is not None and thread.isRunning()

    def _on_sync_clock(self):
        """
        Manual sync button handler. Starts a non-blocking clock refresh.

        The button reads "busy" while the request is in flight and the
        result (source, estimated offset, uncertainty, freshness) is shown
        on the Sync line when it lands — success or failure.
        """
        if self._start_clock_refresh():
            self.sync_clock_button.setText(SYNC_BUTTON_LABEL_BUSY)
            self.sync_clock_button.setEnabled(False)

    def start_startup_sync(self) -> bool:
        """
        Start the ONE-SHOT, non-blocking startup clock sync.

        Called by ``MainWindow`` only after the window has been shown and
        the event loop is running, so importing or constructing the UI
        stays offline and the sync never depends on the Order
        Configuration page being opened.
        """
        if self._startup_sync_done:
            return False
        self._startup_sync_done = True
        return self._start_clock_refresh()

    def _on_clock_sync_finished(self, success: bool):
        """
        Called when a clock refresh (manual, startup or Refresh Clock)
        completes.

        Restores the sync button — unless a schedule is active, in which
        case the button stays locked and only Stop remains active.
        """
        if not self._schedule_locked:
            self.sync_clock_button.setEnabled(True)
        self.sync_clock_button.setText(
            SYNC_BUTTON_LABEL if success else SYNC_BUTTON_LABEL_FAILED
        )
        self._start_sync_freshness_display()
        self._refresh_clock_display()

    # --- UI-7 Task 2: sync freshness display timer ------------------------

    def _start_sync_freshness_display(self):
        """
        Keep the sync freshness line honest between two syncs.

        The line says how long ago the last completed sync was, measured
        on the monotonic clock. Without a timer it would keep claiming
        "fresh" long after the reading has actually expired. This timer
        only RE-RENDERS that text: it starts no request, never reads the
        clock service's time base and never touches the locked schedule
        or its countdown.
        """
        if self._sync_freshness_timer is None:
            self._sync_freshness_timer = QTimer(self)
            self._sync_freshness_timer.setInterval(SYNC_FRESHNESS_TICK_MS)
            self._sync_freshness_timer.timeout.connect(
                self._refresh_sync_freshness_display
            )
        self._sync_freshness_timer.start()

    def _stop_sync_freshness_display(self):
        """Stop the freshness timer (the timer object is reused)."""
        if self._sync_freshness_timer is not None:
            self._sync_freshness_timer.stop()

    def _refresh_sync_freshness_display(self):
        """
        Re-render the sync line from the LIVE monotonic age, nothing else.

        Deliberately does NOT start a sync, does not re-lock or re-freeze
        any schedule time base and does not touch the countdown — the
        active schedule's locked clock is completely independent of how
        fresh the displayed sync reading is.
        """
        # While a request is in flight the line already says so; leave
        # that honest message alone instead of overwriting it.
        if self._clock_sync_in_progress():
            return
        self._refresh_clock_display()

    def closeEvent(self, event):
        """Stop the display timers when the page is closed/destroyed."""
        self._stop_sync_freshness_display()
        # Task 3: closing the page stops STARTING new dispatch turns and
        # wakes the worker, so no send is ever started after the page goes.
        self._stop_dispatcher()
        self._stop_countdown()
        super().closeEvent(event)

    # --- UI-7 Task 3: periodic, concurrent dispatch ------------------------

    def _dispatch_set_rejection(self):
        """
        Why this send set may NOT be scheduled, or ``None`` when it may.

        The WHOLE destination set is validated, fail-closed, BEFORE the
        schedule is locked and before any dispatch worker is started:

          * an EMPTY queue has no destination at all, so there is nothing
            to schedule;
          * an order whose account is not (or no longer) in the existing
            account store has no valid destination;
          * an order whose registered broker disagrees with the broker its
            account is bound to points at the wrong broker, and the
            existing send path fail-closes on that anyway.

        A single unusable destination rejects the WHOLE schedule. The
        valid orders beside it are NEVER sent as a silent partial set,
        and nothing is ever resolved, inferred or fabricated here to make
        a broken binding look usable.
        """
        entries = tuple(self.order_queue.list_pending())
        if not entries:
            return (
                "the order queue is empty - add at least one order before "
                "scheduling a dispatch"
            )
        store = self.store
        for entry in entries:
            record = _account_record_or_none(store, entry.account_id)
            if record is None or record.account is None:
                return (
                    f"queued order {getattr(entry.order, 'nsc_id', entry)} "
                    f"has no valid account ({entry.account_id}) - "
                    f"add that account first"
                )
            if record.broker_name != entry.broker_name:
                return (
                    f"queued order {getattr(entry.order, 'nsc_id', entry)} "
                    f"is registered for broker {entry.broker_name!r} but "
                    f"account {entry.account_id} is bound to "
                    f"{record.broker_name!r}"
                )
        return None

    def _frozen_dispatch_targets(self):
        """
        The pending queue entries, each bound to ITS OWN broker + account.

        Task 3 fans out per broker, so unlike the single-batch Test action
        the pending entries are grouped by their own frozen binding. The
        ``Account`` object comes from the existing account store, verbatim.

        The set was already validated as a WHOLE by
        ``_dispatch_set_rejection`` before the schedule was locked, so this
        never drops an entry: an order that could not be resolved rejects
        the entire schedule instead of being silently omitted, which would
        send a partial set the user never asked for.
        """
        targets = []
        store = self.store
        for entry in self.order_queue.list_pending():
            record = _account_record_or_none(store, entry.account_id)
            if record is None or record.account is None:
                raise DispatchTargetSetError(
                    f"queued order {getattr(entry.order, 'nsc_id', entry)} "
                    f"has no valid account ({entry.account_id})"
                )
            targets.append(
                DispatchTarget(
                    entry=entry,
                    account_id=entry.account_id,
                    broker_name=entry.broker_name,
                    account=record.account,
                )
            )
        return tuple(targets)

    def _freeze_dispatch_set(self):
        """
        Freeze the send set, its destinations and the cadence at Apply.

        The millisecond interval was already validated fail-closed by
        ``_on_apply_schedule`` (an empty, zero, negative, decimal or
        malformed value rejects the Apply and dispatches nothing), so it is
        consumed here as milliseconds and never as seconds.

        The reference for the due times is UI-7 Task 2's LOCKED base (the
        effective clock time plus its monotonic anchor), so the due moments
        stay anchored even if a later sync moves the displayed clock.

        Returns ``True`` when a dispatch run was started. A schedule with
        no valid destination set freezes nothing, starts no worker and
        sends nothing.
        """
        interval_ms = self._pending_dispatch_interval_ms
        if interval_ms is None:  # fail-closed: nothing is frozen or sent
            self._stop_dispatcher()
            self._clear_accepted_schedule()
            self._pending_schedule = None
            self._pending_dispatch_interval_ms = None
            return False

        # Defence in depth: the set was checked before the lock, and it is
        # checked again here so no code path can ever freeze or start a
        # worker over an unvalidated set.
        rejection = self._dispatch_set_rejection()
        if rejection is not None:
            self._stop_dispatcher()
            self._clear_accepted_schedule()
            self._pending_schedule = None
            self._pending_dispatch_interval_ms = None
            self.schedule_summary_label.setText(
                STRINGS.SCHEDULE_REJECTED.format(reason=rejection)
            )
            return False

        targets = self._frozen_dispatch_targets()
        dispatcher = PeriodicScheduleDispatcher(
            runner_factory=self._new_send_runner,
            mono_clock=self.clock_service()._mono,
        )
        timing = self._schedule_timing
        window = (
            (timing.start_time, timing.end_time)
            if timing is not None
            else None
        )
        dispatcher.freeze(
            targets=targets,
            interval_ms=interval_ms,
            locked_base=self._locked_base_time,
            locked_mono=self._locked_mono_anchor,
            window=window,
        )
        self._dispatcher = dispatcher
        self._dispatch_interval_ms = interval_ms
        self._pending_dispatch_interval_ms = None
        self._dispatch_cursor = 0
        self._dispatch_turns = ()
        self._start_dispatch_worker(dispatcher)
        return True

    def _stop_dispatcher(self):
        """
        Stop STARTING new dispatch turns.

        Requests already handed to the existing send path are never
        force-cancelled: their outcome is collected through the normal
        result path into their own turn record.
        """
        if self._dispatcher is not None:
            self._dispatcher.stop()
        self._stop_dispatch_worker()
        self._dispatcher = None
        self._dispatch_interval_ms = None
        self._pending_dispatch_interval_ms = None
        # Task 2's rule, applied to Task 3: a stopped run is forgotten
        # completely, so the next Apply inherits no turn, no cadence and
        # no cursor from it.
        self._dispatch_cursor = 0
        with self._dispatch_turns_lock:
            self._dispatch_turns = ()

    def _new_send_runner(self):
        """
        Build ONE INDEPENDENT runner instance for a single group/turn send.

        The existing send path (``ui.test_runner.TestRunner``) carries
        per-run mutable state — ``last_result``, ``last_execution_id``,
        ``last_order_results``, ``last_report`` — so a SINGLE shared
        instance would let concurrent groups/turns overwrite each other's
        results. Every send therefore gets its own instance from the
        existing factory.

        The instance is built over the SAME existing send path, so the plan
        build, the SafetyGate, the live-permission bridge and the Block 8
        measurement are all unchanged, and the broker API is still reached
        only through the Core — never directly from the UI.
        """
        factory = self._test_runner_factory
        if factory is None:
            raise RuntimeError("no send path is wired")
        return factory()

    # -- the dispatch worker (never the UI thread) -------------------------

    def _start_dispatch_worker(self, dispatcher):
        """
        Run the ms-cadence clock OFF the UI thread.

        This coordinator waits only for each due time. It hands each due
        turn to its own worker and immediately resumes the cadence; it never
        waits for that turn's broker responses before starting the next one.
        """
        self._stop_dispatch_worker()
        stop_event = threading.Event()
        self._dispatch_stop_event = stop_event
        cursor = 0

        def _loop():
            index = cursor
            while not stop_event.is_set():
                dispatcher_obj = self._dispatcher
                if dispatcher_obj is None or dispatcher_obj.stopped:
                    break
                mono = dispatcher_obj.mono_now()

                # The window has closed: nothing more is ever sent.
                if not dispatcher_obj.index_in_window(index):
                    break

                due = dispatcher_obj.due_mono_for_turn(index)
                # Wait until this due time arrives. A Stop wakes us at once.
                while not stop_event.is_set():
                    remaining = due - dispatcher_obj.mono_now()
                    if remaining <= 0:
                        break
                    stop_event.wait(min(remaining, 0.05))
                if stop_event.is_set():
                    break

                now_mono = dispatcher_obj.mono_now()
                # Bind the existing feedback signals lazily at the FIRST
                # scheduled send, before handing off the turn. Binding is
                # idempotent and never waits for a broker response.
                self._ensure_feedback_binding()
                # Each turn's worker may wait for responses; this coordinator
                # does not. Therefore a pending response cannot delay the
                # next due tick. Missed machine-level ticks remain skipped,
                # never replayed as a burst.
                turn_thread = threading.Thread(
                    target=self._service_dispatch_turn,
                    args=(dispatcher_obj, now_mono, index),
                    name=f"ui7-turn-{index}",
                    daemon=True,
                )
                turn_thread.start()
                index += 1

        thread = threading.Thread(
            target=_loop, name="ui7-dispatch", daemon=True
        )
        self._dispatch_thread = thread
        thread.start()

    def _service_dispatch_turn(self, dispatcher, now_mono, index):
        """Wait for one turn's responses away from the cadence/UI threads."""
        record = dispatcher.service_due_turn(now_mono, index)
        if record is not None:
            self._append_dispatch_turn(record, dispatcher)

    def _append_dispatch_turn(self, record, dispatcher=None):
        """Collect completed results without mixing runs or touching widgets."""
        with self._dispatch_turns_lock:
            if dispatcher is not None and self._dispatcher is not dispatcher:
                return
            self._dispatch_turns = tuple(
                sorted(
                    self._dispatch_turns + (record,),
                    key=lambda item: item.turn_index,
                )
            )

    def _stop_dispatch_worker(self):
        """Wake and stop the dispatch worker; it never blocks the caller."""
        stop_event = self._dispatch_stop_event
        if stop_event is not None:
            stop_event.set()
        self._dispatch_stop_event = None
        self._dispatch_thread = None

    def _service_due_dispatch_turns(self):
        """
        Service ONE due time of the ms cadence, synchronously.

        This exists for deterministic testing and for any caller that
        wants to step the cadence itself. The page's own run does NOT use
        it: the live cadence runs on the worker thread instead, so the UI
        is never blocked here.
        """
        dispatcher = self._dispatcher
        if dispatcher is None:
            return ()

        index = self._dispatch_cursor
        if not dispatcher.index_in_window(index):
            return ()

        record = dispatcher.service_due_turn(dispatcher.mono_now(), index)
        # The cursor only ever moves forward, and only past a due time that
        # was actually considered, so no due time is serviced twice.
        self._dispatch_cursor = index + 1
        if record is not None:
            self._append_dispatch_turn(record, dispatcher)
        return (record,) if record is not None else ()

    @property
    def dispatch_turns(self):
        """The dispatch turns of the active run (Task 3 scheduling log)."""
        with self._dispatch_turns_lock:
            return self._dispatch_turns

    @property
    def dispatch_interval_ms(self):
        return self._dispatch_interval_ms

    def _clear_locked_time_base(self):
        """Drop every value the countdown advances from."""
        self._locked_clock_source = None
        self._locked_applied_offset = None
        self._locked_uncertainty = None
        self._locked_market_time = None
        self._locked_sync_time = None
        self._locked_base_time = None
        self._locked_mono_anchor = None
        self._locked_last_now = None

    def _lock_schedule_time_base(self):
        """
        Freeze the CURRENT clock state as the time base of the schedule.

        The base is the clock service's EFFECTIVE ``now()`` at Apply —
        the very value the countdown is measured against — plus the
        monotonic reading taken at that same instant. Both are COPIED
        here rather than read back from the service later, so a
        subsequent sync — which may even rebuild the clock service —
        can never move the accepted target or restart, rewind or shift
        the countdown.

        ``now()`` is sampled on purpose instead of re-deriving
        ``wall_anchor + applied_offset`` here: when a gradual correction
        has walked the applied offset down, ``now()`` HOLDS at its
        previous value (the non-rewinding guarantee) while the raw terms
        already sit behind it. Reconstructing from the raw terms would
        therefore start the countdown in the past.
        """
        service = self.clock_service()
        status = (
            self._clock_status
            if self._clock_status is not None
            else service.status()
        )
        self._locked_clock_source = status.source
        self._locked_applied_offset = status.applied_offset
        self._locked_uncertainty = status.uncertainty
        self._locked_market_time = status.market_time
        self._locked_sync_time = status.last_successful_sync
        # Monotonic FIRST, then now(): the elapsed time measured from
        # this reading can then only be >= 0, so the locked clock can
        # never start behind the effective time it was locked at.
        self._locked_mono_anchor = service._mono()
        self._locked_base_time = service.now()
        self._locked_last_now = None

    def _get_locked_now_tehran(self) -> datetime:
        """
        Current application time on the LOCKED time base.

        Built from the stored effective base time plus the monotonic
        time elapsed since it was taken, so it advances on the monotonic
        clock and never jumps because of a later sync, a system-clock
        step or a fallback.
        """
        if (
            self._locked_base_time is None
            or self._locked_mono_anchor is None
        ):
            return self.clock_service().now_tehran()

        elapsed = self.clock_service()._mono() - self._locked_mono_anchor
        if elapsed < 0:
            elapsed = 0.0
        candidate = self._locked_base_time + timedelta(seconds=elapsed)
        if self._locked_last_now is not None and candidate < self._locked_last_now:
            return self._locked_last_now
        self._locked_last_now = candidate
        return candidate.astimezone(TEHRAN_TIMEZONE)

    @property
    def countdown_active(self) -> bool:
        """True while the countdown timer of an accepted schedule runs."""
        return self._countdown_timer is not None and self._countdown_timer.isActive()

    def _start_countdown(self):
        """Start the countdown timer for the accepted schedule."""
        if self._countdown_timer is None:
            self._countdown_timer = QTimer(self)
            self._countdown_timer.setInterval(1000)
            self._countdown_timer.timeout.connect(self._update_countdown)
        self._countdown_timer.start()
        self._update_countdown()

    def _stop_countdown(self):
        """Stop the countdown timer (the timer object is reused)."""
        if self._countdown_timer is not None:
            self._countdown_timer.stop()

    def _update_countdown(self):
        """
        Recompute the remaining time from the ACCEPTED target and the
        internal monotonic clock.

        Because the remaining time is always derived from the locked
        target minus the monotonic now, a refresh delay never accumulates
        into the countdown, and a system-clock step, a manual sync, a
        fallback or a market-clock recovery cannot shift it.
        """
        timing = self._schedule_timing
        if not self._schedule_times or timing is None:
            self.countdown_label.setText(COUNTDOWN_LABEL_UNAVAILABLE)
            return

        # UI-7 Task 3 NOTE: dispatch turns are NOT serviced here. They run
        # on their own worker thread (see ``_start_dispatch_worker``), so
        # the countdown tick stays pure UI work and never waits for a
        # broker answer.

        now = self._get_locked_now_tehran()
        next_run = None
        for moment in self._schedule_times:
            if moment > now:
                next_run = moment
                break

        if next_run is None:
            self.countdown_label.setText(COUNTDOWN_LABEL_NO_UPCOMING)
            self._finish_schedule(SCHEDULE_STATE_EXPIRED)
            return

        total_seconds = max(0, int((next_run - now).total_seconds()))
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        self._countdown_target = next_run
        self.countdown_label.setText(
            STRINGS.COUNTDOWN_NEXT_RUN.format(
                clock="{:02d}:{:02d}:{:02d}".format(hours, minutes, seconds),
                tehran=next_run.strftime("%H:%M:%S"),
            )
        )

        if now < timing.start_time:
            self._set_schedule_state(SCHEDULE_STATE_WAITING)
        elif now >= timing.end_time:
            self.countdown_label.setText(COUNTDOWN_LABEL_NO_UPCOMING)
            self._finish_schedule(SCHEDULE_STATE_EXPIRED)
        else:
            self._set_schedule_state(SCHEDULE_STATE_COUNTING)

    def _set_schedule_state(self, state: str):
        """Update the lifecycle state and render it on the State row."""
        self._schedule_state = state
        self.schedule_state_label.setText(state)

    def _finish_schedule(self, state: str):
        """
        End the active schedule: stop the timer, drop the locked time base
        and the accepted plan, and free every locked control.

        UI-7 Task 2 ONLY cancels the countdown: no order is sent and no
        dispatch is performed here. Connecting Stop to suppressing later
        sends belongs to UI-7 Task 3.
        """
        self._stop_countdown()
        self._stop_dispatcher()
        self._clear_locked_time_base()
        self._pending_schedule = None
        self._countdown_target = None
        self._start_now_shown = False
        self._set_schedule_locked(False)

        if state == SCHEDULE_STATE_STOPPED:
            # A stopped plan is forgotten completely: the next Apply must
            # not inherit its timer, offset, sync or state.
            self._schedule_parsed = None
            self._schedule_timing = None
            self._schedule_times = ()
            self._schedule_assessment = None
            self.countdown_label.setText(COUNTDOWN_LABEL_STOPPED)
        elif state == SCHEDULE_STATE_EXPIRED:
            # The expired window stays readable so the user can see what
            # ran out; only the active runtime state is dropped.
            self.countdown_label.setText(COUNTDOWN_LABEL_NO_UPCOMING)
        else:
            self.countdown_label.setText(COUNTDOWN_LABEL_UNAVAILABLE)

        self._set_schedule_state(state)
        self._refresh_clock_display()

    def _on_schedule_button_clicked(self):
        """The single schedule button: Apply before, Stop afterwards."""
        if self._schedule_locked:
            self._on_stop_schedule()
        else:
            self._on_apply_schedule()

    def _on_stop_schedule(self):
        """
        Cancel the active schedule and its countdown immediately.

        Stops the timer, clears the active plan and the locked time base,
        returns the page to the configuring state and re-enables every
        locked control. It sends nothing (UI-7 Task 2).
        """
        self._finish_schedule(SCHEDULE_STATE_STOPPED)

    def _on_apply_schedule(self):
        """
        Validate the inputs, then accept them using the LAST COMPLETED
        clock sync.

        Apply never starts a network request of its own. Three cases:

          * a sync is still in flight -> Apply waits for that very result;
          * the last completed sync is fresh (monotonic age inside
            ``SCHEDULE_SYNC_MAX_AGE_SECONDS``) -> it is consumed as-is;
          * nothing fresh is available -> the page says so explicitly and
            falls back to the system clock with a soft notice. Stale or
            missing market data is never used as if it were current, and
            no reading is ever invented.

        Fail-closed: an incomplete or malformed input produces a visible
        rejection immediately, never reaches the network, and leaves no
        previously accepted schedule looking active.
        """
        try:
            parsed = parse_schedule_inputs(
                self.schedule_start_input.text(),
                self.schedule_end_input.text(),
                self.schedule_interval_input.text(),
            )
            # UI-7 Task 3: the dispatch interval is validated HERE, with
            # the other inputs, so a bad millisecond value rejects the
            # Apply exactly like a bad time does — fail-closed, before
            # anything is frozen, locked or dispatched. It is a whole
            # number of MILLISECONDS and is never read as seconds.
            self._pending_dispatch_interval_ms = parse_execution_interval_ms(
                self.dispatch_interval_input.text()
            )
            # UI-7 Task 3: the send set is validated HERE, with the other
            # inputs, BEFORE anything is locked or any worker is started.
            # An empty queue, an order with no valid account, or an order
            # whose broker disagrees with its account's broker rejects the
            # WHOLE schedule: nothing is locked, no worker starts, no turn
            # is created and ``runner.run()`` is never reached. The valid
            # orders beside a broken one are never sent as a silent partial
            # set.
            target_rejection = self._dispatch_set_rejection()
        except (ScheduleValidationError, DispatchIntervalError) as exc:
            self._clear_accepted_schedule()
            self._pending_schedule = None
            self.schedule_summary_label.setText(
                STRINGS.SCHEDULE_REJECTED.format(reason=exc)
            )
            return

        if target_rejection is not None:
            self._clear_accepted_schedule()
            self._pending_schedule = None
            self._pending_dispatch_interval_ms = None
            self.schedule_summary_label.setText(
                STRINGS.SCHEDULE_REJECTED.format(reason=target_rejection)
            )
            return

        self._pending_schedule = parsed
        if self._clock_sync_in_progress():
            # Wait for the result already in flight instead of starting a
            # second request; the worker's completion handler finishes
            # this Apply.
            #
            # The controls are locked IMMEDIATELY, not when the sync
            # lands: from this moment the user has a schedule pending,
            # so every order/queue/schedule control is frozen and the
            # button becomes Stop. Stop drops ``_pending_schedule`` and
            # frees the controls, and the landing sync result then finds
            # nothing pending and can never revive a cancelled plan.
            self.sync_status_label.setText(SYNC_STATE_IN_PROGRESS)
            self._set_schedule_locked(True)
            return
        self._apply_pending_schedule_if_any()

    def _ensure_usable_clock_for_apply(self, service):
        """
        Refuse to schedule against a stale or missing market clock.

        A successful sync whose MONOTONIC age is inside the schedule limit
        is used unchanged. Otherwise the page states the problem explicitly
        and falls back to the system clock with a soft notice — the
        confirmed fallback behaviour. It never fabricates a TSETMC reading
        and never silently reuses an old one.
        """
        if service.is_sync_fresh():
            return
        age = service.sync_age_seconds()
        status = service.status()
        age_text = f"{age:.0f}s" if age is not None else "no recorded age"
        if status.source is ClockSource.MARKET:
            service.note_unavailable(
                f"the last market clock sync is {age_text} old, older than "
                f"the {SCHEDULE_SYNC_MAX_AGE_SECONDS:.0f}s schedule limit"
            )
        elif status.last_sync_attempt is None:
            service.note_unavailable(
                "no market clock sync has completed yet - press the sync "
                "button before applying"
            )
        # A sync that already failed keeps its own, more specific reason.

    def _apply_pending_schedule_if_any(self):
        """
        Accept the pending inputs once a clock refresh has landed.

        Does nothing until a refresh has actually landed, so the window is
        always evaluated against a real, completed sync result.

        On success this LOCKS the time base, locks every order/queue/
        schedule control (Stop stays active) and starts the countdown.
        """
        parsed = self._pending_schedule
        if parsed is None:
            return

        service = self.clock_service()
        self._ensure_usable_clock_for_apply(service)
        status = service.status()
        self._clock_status = status

        try:
            now_tehran = service.now_tehran()
            timing = build_dispatch_timing(parsed, now_tehran)
            times = generate_schedule_times(timing)
            assessment = assess_schedule_window(timing, now_tehran, times)
        except ScheduleValidationError as exc:
            self._clear_accepted_schedule()
            self._pending_schedule = None
            self.schedule_summary_label.setText(
                STRINGS.SCHEDULE_REJECTED.format(reason=exc)
            )
            return

        self._pending_schedule = None
        self._schedule_parsed = parsed
        self._schedule_timing = timing
        self._schedule_times = tuple(times)
        self._schedule_assessment = assessment
        # A new plan never inherits the previous plan's runtime state.
        self._schedule_state = SCHEDULE_STATE_CONFIG
        self._start_now_shown = False
        self._countdown_target = None
        self._clear_locked_time_base()
        self._lock_schedule_time_base()
        # The queue/account set may have changed while Apply waited for a
        # clock sync. Freezing repeats destination validation; if it fails,
        # the helper clears the accepted state and we must not continue by
        # locking the page or starting a countdown without a dispatcher.
        if not self._freeze_dispatch_set():
            return

        summary = build_schedule_summary(
            parsed,
            timing,
            assessment,
            describe_clock(status),
            moments=times,
        )
        self.schedule_summary_label.setText(describe_summary(summary))

        # Lock BEFORE the first tick: an already-expired window finishes
        # during that tick and must find its controls locked so it can
        # free them again.
        self._set_schedule_locked(True)
        self._start_countdown()

        # START_NOW is a one-shot notice: shown exactly once, never
        # re-entered by a later tick, and never a dispatch (Task 2).
        if (
            self._schedule_locked
            and assessment.state is ScheduleState.START_NOW
            and not self._start_now_shown
        ):
            self._start_now_shown = True
            self._set_schedule_state(SCHEDULE_STATE_START_NOW)

        self._refresh_clock_display()

    def _clear_accepted_schedule(self):
        """Forget the accepted schedule entirely and free every control."""
        self._stop_countdown()
        self._stop_dispatcher()
        self._clear_locked_time_base()
        self._schedule_parsed = None
        self._schedule_timing = None
        self._schedule_times = ()
        self._schedule_assessment = None
        self._countdown_target = None
        self._start_now_shown = False
        self._set_schedule_locked(False)
        self.countdown_label.setText(COUNTDOWN_LABEL_UNAVAILABLE)
        self._set_schedule_state(SCHEDULE_STATE_CONFIG)

    def _set_schedule_locked(self, locked: bool):
        """
        Lock (or release) every control of THIS page that can change an
        order, the queue or the schedule.

        While locked the Apply button reads "Stop Schedule" and is the
        ONLY enabled button of that set — order editing, queue changes,
        Apply, Sync and Refresh are all disabled, and Stop is the single
        way out.
        """
        self._schedule_locked = bool(locked)
        unlocked = not self._schedule_locked

        self.schedule_start_input.setEnabled(unlocked)
        self.schedule_end_input.setEnabled(unlocked)
        self.schedule_interval_input.setEnabled(unlocked)
        self.dispatch_interval_input.setEnabled(unlocked)
        self.sync_clock_button.setEnabled(unlocked)
        self.refresh_clock_button.setEnabled(unlocked)
        self.apply_schedule_button.setText(
            STOP_BUTTON_LABEL if self._schedule_locked else APPLY_BUTTON_LABEL
        )
        self.apply_schedule_button.setEnabled(True)
        self._set_order_controls_enabled(unlocked)

    def _set_order_controls_enabled(self, enabled: bool):
        """Enable/disable the order and queue controls of this page."""
        self.symbol_input.setEnabled(enabled)
        self.results_list.setEnabled(enabled)
        for button in self.side_buttons.values():
            button.setEnabled(enabled)
        self.price_input.setEnabled(enabled)
        self.quantity_input.setEnabled(enabled)
        self.price_max_button.setEnabled(enabled)
        self.price_min_button.setEnabled(enabled)
        self.quantity_max_button.setEnabled(enabled)
        self.quantity_min_button.setEnabled(enabled)
        self.add_to_queue_button.setEnabled(enabled)
        self.queue_list.setEnabled(enabled)
        if enabled:
            self._refresh_test_button_state()
        else:
            self.test_button.setEnabled(False)

    def schedule_state(self):
        """Public read-only access to the accepted schedule (or ``None``)."""
        return self._schedule_assessment

    def schedule_lifecycle_state(self) -> str:
        """Public read-only access to the displayed lifecycle state."""
        return self._schedule_state

    def schedule_timing(self):
        """Public read-only access to the accepted ``DispatchTiming``."""
        return self._schedule_timing

    def schedule_times(self):
        """Public read-only access to the accepted run moments."""
        return self._schedule_times

    def clock_status(self):
        """Public read-only access to the current clock status."""
        if self._clock_status is None:
            self._clock_status = self.clock_service().status()
        return self._clock_status

    # ---------------------------------------------------------
    # Amounts
    # ---------------------------------------------------------

    def _refresh_amounts(self):
        base = self.config.base_amount()
        # base is an int (price * quantity, both int per the Core Order
        # contract) — format it as a plain integer, no scientific notation.
        # UI-9 Task 3: money uses PERSIAN digits through the ONE
        # centralized formatter - no ad-hoc conversion here.
        self.base_amount_label.setText(
            STRINGS.VALUE_EMPTY_DASH
            if base is None
            else STRINGS.format_grouped(base)
        )
        # Fee / Final Amount: no contract exists — never fabricated.
        self.fee_label.setText(STRINGS.VALUE_NOT_AVAILABLE)
        self.final_amount_label.setText(STRINGS.VALUE_NOT_AVAILABLE)

    def _invalidate_auto_amount(self):
        if hasattr(self, "_auto_amount_timer"):
            self._auto_amount_timer.stop()
        self._auto_amount_request_id += 1
        if hasattr(self, "amount_warning_label"):
            self.amount_warning_label.clear()
        if hasattr(self, "fee_label"):
            self.fee_label.setText(STRINGS.VALUE_NOT_AVAILABLE)
            self.final_amount_label.setText(STRINGS.VALUE_NOT_AVAILABLE)

    def _schedule_auto_amount(self, *_):
        """Coalesce keystrokes into one request while invalidating old results immediately."""
        self._invalidate_auto_amount()
        if hasattr(self, "base_amount_label"):
            try:
                price = _valid_limit(_parse_exact_integral_text(self.price_input.text()), allow_zero=False)
                quantity = _valid_limit(_parse_exact_integral_text(self.quantity_input.text()), allow_zero=False)
            except Exception:
                price = quantity = None
            self.base_amount_label.setText(
                STRINGS.format_grouped(price * quantity)
                if price is not None and quantity is not None
                else STRINGS.VALUE_EMPTY_DASH
            )
            self.fee_label.setText("نامشخص؛ قیمت یا تعداد معتبر نیست")
            self.final_amount_label.setText(STRINGS.VALUE_NOT_AVAILABLE)
        self._auto_amount_timer.start()

    def _start_auto_amount(self):
        try:
            record = self._active_account_record()
            instrument = self.config.selected_instrument
            price = _valid_limit(_parse_exact_integral_text(self.price_input.text()), allow_zero=False)
            quantity = _valid_limit(_parse_exact_integral_text(self.quantity_input.text()), allow_zero=False)
            if (record is None or record.broker_name != "آگاه" or instrument is None
                    or not getattr(instrument, "ins_code", None) or not self._order_nsc_id
                    or self.config.side != BUY or price is None or quantity is None):
                self.fee_label.setText("نامشخص؛ حساب، نماد، قیمت یا تعداد معتبر نیست")
                self.final_amount_label.setText(STRINGS.VALUE_NOT_AVAILABLE)
                return
        except Exception:
            self.fee_label.setText("نامشخص؛ قیمت یا تعداد معتبر نیست")
            self.final_amount_label.setText(STRINGS.VALUE_NOT_AVAILABLE)
            return
        snapshot = (record.account_id, instrument.ins_code, self._order_nsc_id,
                    price, quantity, self.config.side)
        self.base_amount_label.setText(STRINGS.format_grouped(price * quantity))
        self.fee_label.setText("در حال دریافت کارمزد…")
        self.final_amount_label.setText(STRINGS.VALUE_NOT_AVAILABLE)
        request_id = self._auto_amount_request_id
        factory = self._buy_preview_factory

        def calculate(_snapshot):
            if factory is None:
                raise RuntimeError("سرویس کارمزد آگاه در دسترس نیست")
            service = factory(record.account_id, record.broker_name)
            power = service.get_tradable_balance(record.account_id)
            if isinstance(power, bool) or not isinstance(power, int) or power < 0:
                raise ValueError("قدرت خرید حساب معتبر نیست")
            broker = service.get_adapter(record.account_id)._broker
            data = broker.get_commission_info(self._order_nsc_id, price, quantity, 1)
            fee = data.get("commissionSum") if isinstance(data, dict) else None
            if isinstance(fee, bool) or not isinstance(fee, int) or fee < 0:
                raise ValueError("پاسخ کارمزد آگاه معتبر نیست")
            return {"power": power, "fee": fee, "base": price * quantity,
                    "total": price * quantity + fee}

        worker = _BuyPreviewWorker(request_id, snapshot, calculate, self)
        self._auto_amount_worker = self._auto_amount_thread = worker
        worker.succeeded.connect(self._on_auto_amount_succeeded)
        worker.failed.connect(self._on_auto_amount_failed)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _auto_amount_current(self, snapshot):
        record = self._active_account_record()
        instrument = self.config.selected_instrument
        try:
            values = (_valid_limit(_parse_exact_integral_text(self.price_input.text()), allow_zero=False),
                      _valid_limit(_parse_exact_integral_text(self.quantity_input.text()), allow_zero=False))
        except Exception:
            return False
        return (record is not None and instrument is not None
                and snapshot == (record.account_id, instrument.ins_code, self._order_nsc_id,
                                 *values, self.config.side))

    def _on_auto_amount_succeeded(self, request_id, snapshot, result):
        if request_id != self._auto_amount_request_id or not self._auto_amount_current(snapshot):
            return
        self.fee_label.setText(STRINGS.format_grouped(result["fee"]))
        self.final_amount_label.setText(STRINGS.format_grouped(result["total"]))
        if result["total"] > result["power"]:
            self.amount_warning_label.setText("مبلغ نهایی از موجودی شما بیشتر است")
        else:
            self.amount_warning_label.clear()

    def _on_auto_amount_failed(self, request_id, message):
        if request_id == self._auto_amount_request_id:
            self.fee_label.setText(f"نامشخص: {message}")
            self.final_amount_label.setText(STRINGS.VALUE_NOT_AVAILABLE)
            self.amount_warning_label.clear()

    # ---------------------------------------------------------
    # Account display (verbatim from the UI-2.1 store)
    # ---------------------------------------------------------

    def _active_account_text(self):
        record = self._active_account_record()
        if record is None:
            # No fallback to accounts[0]/first/default — shown transparently.
            return STRINGS.NO_ACTIVE_ACCOUNT
        # The user-chosen display name is the account's public identity in
        # the UI; the internal account id is never substituted for it.
        return record.display_name

    def showEvent(self, event):
        """Re-read the active account every time this page is entered."""
        super().showEvent(event)
        self.refresh_active_account()

    def refresh_active_account(self):
        """Re-mirror the active account from the store into the page."""
        self._invalidate_buy_preview()
        self._invalidate_auto_amount()
        self._buy_preview_power = None
        if self._buy_preview_dialog is not None:
            self._buy_preview_dialog.reject()
            self._buy_preview_dialog = None
        self.active_account_label.setText(self._active_account_text())
        self._clear_order_identity()
        instrument = self.config.selected_instrument
        self._restart_order_identity_if_stale()
        self._refresh_test_button_state()
        self._start_auto_amount()

    def _active_account_record(self):
        """
        The active AccountRecord, or ``None`` while nothing is active.
        Fail-closed: an unknown/removed id yields ``None`` (never guessed).
        """
        active_id = self.store.active_account_id()
        if active_id is None:
                return None
        try:
                return self.store.get(active_id)
        except ValueError:  # AccountStoreError of the UI-2.1 store
                return None

    def _active_broker_name(self):
        """The active account's broker name, or ``None`` while inactive."""
        record = self._active_account_record()
        if record is None:
                return None
        return record.broker_name

    def _current_read_identity(self, expected_ins_code=None):
        """Current account/broker/instrument binding for order reads."""
        record = self._active_account_record()
        instrument = self.config.selected_instrument
        ins_code = getattr(instrument, "ins_code", None)
        if (record is None or not ins_code
                or (expected_ins_code is not None and ins_code != expected_ins_code)):
            return None
        return (record.account_id, record.broker_name, ins_code)

    def _restart_order_identity_if_stale(self):
        """
        Re-resolve the selected instrument's order identity when selecting
        an account made it available (or the broker changed) — so the
        realistic "choose account → pick symbol" order of operations still
        leads to a working Add-to-Queue.
        """
        instrument = self.config.selected_instrument
        if instrument is None:
                return
        record = self._active_account_record()
        if record is None:
                self._clear_order_identity()
                return
        if (self._order_nsc_id
                and self._order_identity_broker == record.broker_name
                and self._order_identity_account == record.account_id):
                return  # still coherent — nothing to do
        self._start_order_identity_resolution(instrument)
