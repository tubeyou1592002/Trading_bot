"""
ui/user_log.py — UI-5 Task 4 (Stage 3, base display): the user-facing order log.

An in-memory, append-only log of the orders the user has SENT from the Order
Configuration page, rendered as one fixed seven-column table:

    زمان ارسال | حساب | نماد | توضیح | زمان دریافت توسط کارگزاری |
    زمان ثبت در هسته معاملاتی | وضعیت صف

What this base display owns:

    * ONE row per sent order, appended in SEND order — never reordered,
      never removed, never deduplicated;
    * the seven user-facing columns above, and nothing else;
    * ``—`` for every value that does not exist yet — an absent value is
      rendered as empty, NEVER invented, never back-calculated.

Where each value comes from (existing project data only):

    * ``sent_at`` — the wall-clock moment the UI issued that send, captured
      once per send pass. It is a UI-local wall clock (local time, millisecond
      display precision), NOT a broker/exchange timestamp and NOT a latency
      value: it never waits for feedback and never measures anything.
    * ``account_id`` — verbatim from the real ``QueueEntry`` that was sent.
    * ``symbol`` — the UI-layer symbol the user picked (recorded at
      Add-to-Queue from the real ``Instrument``). ``models.order.Order``
      carries no symbol, and the broker ``nscId`` / ``tseId`` must never
      reach a user-facing row.
    * ``description`` — the fixed, user-facing reason derived from the REAL
      per-order execution result of that same send (the existing UI-5 Task 3
      status mapper). A raw result message, mode name, endpoint, exception,
      Trace ID, latency or internal id is never rendered.

Fail-closed columns in this base stage (they exist, and they stay empty):

    * ``broker_received_at`` — no broker/exchange feedback consumer is wired
      into the UI yet, so this column is always ``—``.
    * ``queue_status`` — no queue-position / queue-status source is wired into
      the UI yet, so this column is always ``—``.

Stage 3 Task 3 addition (trading-core registration only):

    * ``core_registered_at`` — filled on the row whose exact sent order
      matches a real ``AcceptedByBourse`` feedback event, through the
      decisionId correlation the page owns. The value is the event's own
      real receive moment (epoch seconds — the feedback path's
      ``OmsStateChanged.raw_timestamp``), converted by the page to a local
      ``datetime`` for display; this module never reads a clock, never
      converts a monotonic value and never fabricates a time. A row that
      received the event is additionally flagged (``registered_in_core``)
      so the page renders it with the registered highlight (green).

Boundaries (explicitly NOT part of this module):

    * rows are never reordered, removed, deduplicated by an update — the
      only feedback mutation is the logical update of ONE row's
      core-registration value/flag (``update_core_registration``), which
      atomically substitutes the immutable row with its updated copy;
    * no NATS/OMS connection, no asynchronous feedback, no polling and no
      listener — the ONE permitted feedback entry point is the logical
      update above, nothing else;
    * no green/"registered" highlighting, no queue-status logic;
    * no Trace ID, latency, diagnostics or execution-step detail (UI-6);
    * no persistence, database, export or new logging framework — the rows
      live in this in-memory list only.
"""

from __future__ import annotations
from dataclasses import dataclass, replace
from datetime import datetime
from typing import List, Optional

# The seven user-facing columns, in display order. This tuple is the single
# authority for the table's shape: header labels, column count and the cell
# order of every row object all come from it.
ORDER_LOG_COLUMNS = (
    "زمان ارسال",
    "حساب",
    "نماد",
    "توضیح",
    "زمان دریافت توسط کارگزاری",
    "زمان ثبت در هسته معاملاتی",
    "وضعیت صف",
)

# Display index of each column, derived from ORDER_LOG_COLUMNS — the page
# fills the table by these positions, never by a hand-counted literal.
COLUMN_SENT_AT = 0
COLUMN_ACCOUNT = 1
COLUMN_SYMBOL = 2
COLUMN_DESCRIPTION = 3
COLUMN_BROKER_RECEIVED_AT = 4
COLUMN_CORE_REGISTERED_AT = 5
COLUMN_QUEUE_STATUS = 6

# The one and only rendering of "this information does not exist yet".
EMPTY_CELL = "-"


def format_timestamp(value) -> str:
    """
    Render a timestamp as ``HH:MM:SS.mmm`` (millisecond precision).

    Fail-closed: anything that is not a real ``datetime`` — ``None``
    included — renders as ``EMPTY_CELL``. A missing timestamp is never shown
    as a made-up time, and a timestamp is never converted into a duration or
    merged with any other timing value.
    """
    if not isinstance(value, datetime):
        return EMPTY_CELL
    return value.strftime("%H:%M:%S.%f")[:-3]


def format_text(value) -> str:
    """
    Render a plain text value, or ``EMPTY_CELL`` when it is missing/blank.

    Fail-closed: no placeholder word, no default symbol, no fallback account
    — an absent value is simply empty.
    """
    if value is None:
        return EMPTY_CELL
    text = str(value).strip()
    return text if text else EMPTY_CELL


@dataclass(frozen=True)
class OrderLogRow:
    """
    One immutable user-facing log row for exactly ONE sent order.

    A field is ``None`` when that piece of information does not exist yet —
    it is rendered as ``EMPTY_CELL`` and is never guessed. Fields are read by
    name (never by parsing rendered text), so a later task may supply a
    verified broker / trading-core / queue value without changing the shape of
    the table.

    Update semantics (Stage 3 Task 3): feedback NEVER creates a new row, never
    changes the row count or order, and never touches any other field. An
    update is a logical in-place substitution of the ONE matching row by its
    updated immutable copy (``dataclasses.replace``) at the SAME position —
    every other row object, including its neighbors, stays the SAME object.
    A re-delivery carrying the exact same value substitutes nothing (no new
    row object is created) — the operation is idempotent.
    """

    sent_at: Optional[datetime] = None
    account_id: Optional[str] = None
    symbol: Optional[str] = None
    description: Optional[str] = None
    broker_received_at: Optional[datetime] = None
    core_registered_at: Optional[datetime] = None
    queue_status: Optional[str] = None
    # UI-5 Task 4 Stage 3 Task 3 — outcome of the REAL matching-engine
    # (trading core) registration event. ``None`` = no such event has been
    # received for this order (rendered as the plain, unhighlighted row);
    # ``True`` = AcceptedByBourse was actually received (the row renders
    # with the registered highlight). It is set ONLY from the real event —
    # never guessed, never synthesized from any other state.
    registered_in_core: Optional[bool] = None
    # UI-5 Task 4 Stage 3 Task 3 — the append-time correlation key: the
    # EXACT sent ``Order`` object this row belongs to. It is identity only
    # (an ``id``-style binding), is NEVER rendered, and is the sole link a
    # feedback event's ``decisionId`` may be resolved through. Kept on the
    # row so a later event can find its row without any external registry.
    key: object = None


    def cells(self) -> tuple:
        """
        The row's seven display strings, in ``ORDER_LOG_COLUMNS`` order.

        This is the only place a row becomes text, so the collection never
        shows a cell in the wrong column and never leaks a technical value:
        each field is rendered by its own formatter and a missing one is ``—``.
        """
        return (
            format_timestamp(self.sent_at),
            format_text(self.account_id),
            format_text(self.symbol),
            format_text(self.description),
            format_timestamp(self.broker_received_at),
            format_timestamp(self.core_registered_at),
            format_text(self.queue_status),
        )


class OrderLog:
    """
    The in-memory user-facing order log: rows in send order, nothing else.

    ``append()`` adds exactly one row for one sent order and returns it;
    ``rows()`` returns the rows in send order. There is deliberately no
    reorder/remove/delete operation — rows are appended once, in send
    order, and the row count and order never change afterwards. No row
    is ever persisted, exported or sent anywhere.

    Stage 3 Task 3 update semantics: ``update_core_registration`` logically
    updates the trading-core registration value/flag of ONE EXISTING row
    from the real feedback event — feedback never creates a row and never
    touches any other row or field.
    """

    def __init__(self, rows=None) -> None:
        existing = list(rows) if rows is not None else []
        for row in existing:
            self._check_row(row)
        self._rows: List[OrderLogRow] = existing

    # ------------------------------------------------------------------
    # UI-5 Task 4 Stage 3 Task 3 — update semantics (minimal, documented)
    # ------------------------------------------------------------------
    # The base Stage 3 display was append-only. ONE further operation is
    # added, scoped to exactly the one event of this task — receiving the
    # matching-engine (trading core) registration feedback for an order:
    # the row's ``core_registered_at`` value and its ``registered_in_core``
    # flag are filled with the REAL event timestamp. That is the only
    # mutation: rows are never reordered, never removed, never duplicated,
    # and every other field stays untouched. An unknown ``key`` changes
    # nothing (fail-closed). A re-delivery carrying the exact same value
    # performs NO replacement at all (idempotent — the stored row object
    # stays the same).

    def _replace(self, index: int, row: OrderLogRow) -> OrderLogRow:
        """Atomically replace the row at ``index`` with ``row``."""
        self._check_row(row)
        self._rows[index] = row
        return row

    def update_core_registration(self, key, core_registered_at):
        """
        Logically update the trading-core registration of ONE existing row.

        Args:
            key: identity the row was appended with — the exact order
                object that was sent (never a symbol, never an account id,
                never a parsed display text).
            core_registered_at: the REAL matching-engine registration
                moment carried by the received feedback event. Must be a
                real ``datetime``; anything else is rejected and nothing
                is written (fail-closed — a fabricated time is never
                stored).

        The update never creates a new row, never changes the row count or
        the send order, and never touches any other field of the matching
        row or any other row: the ONE matching row is logically substituted
        by its updated immutable copy (``dataclasses.replace``) at the same
        position — neighboring rows stay the SAME objects.

        Returns the (possibly new) row, or ``None`` when nothing changed:
        unknown key, invalid timestamp, or an idempotent re-delivery
        carrying the exact same value (no replacement happens at all).
        """
        index = self._index_of(key)
        if index is None:
            return None
        if not isinstance(core_registered_at, datetime):
            return None
        row = self._rows[index]
        if row.core_registered_at == core_registered_at:
            return None
        return self._replace(
            index,
            replace(
                row,
                core_registered_at=core_registered_at,
                registered_in_core=True,
            ),
        )

    def _index_of(self, key):
        """Position of the row appended for ``key``, or ``None``."""
        for index, row in enumerate(self._rows):
            if row.key is key:
                return index
        return None

    @staticmethod
    def _check_row(row) -> None:
        """
        Guard the log's single element type (fail-closed).

        A caller may not put an arbitrary object into the log: every row must
        be a real ``OrderLogRow`` so no technical object can ever be rendered
        as a cell.
        """
        if not isinstance(row, OrderLogRow):
            raise TypeError(
                "order log rows must be ui.user_log.OrderLogRow instances; "
                "the user-facing log never renders an arbitrary object"
            )

    def append(self, row: OrderLogRow) -> OrderLogRow:
        """
        Append ONE row for one sent order and return it.

        The row lands at the end of the log, so the list is always in send
        order. An existing row is never touched and never moved.
        """
        self._check_row(row)
        self._rows.append(row)
        return row

    def rows(self) -> List[OrderLogRow]:
        """
        All appended rows, in send order.

        A new list is returned (the row objects are the same immutable
        objects), so a caller can never reorder or remove log entries through
        it.
        """
        return list(self._rows)

    def __len__(self) -> int:
        return len(self._rows)