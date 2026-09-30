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
    * ``core_registered_at`` — matching-engine (trading core) registration
      feedback does not reach the UI yet, so this column is always ``—``.
    * ``queue_status`` — no queue-position / queue-status source is wired into
      the UI yet, so this column is always ``—``.

Boundaries (explicitly NOT part of this module):

    * no NATS/OMS connection, no asynchronous feedback, no polling, no
      listener, no update of an already-appended row;
    * no green/"registered" highlighting, no queue-status logic;
    * no Trace ID, latency, diagnostics or execution-step detail (UI-6);
    * no persistence, database, export or new logging framework — the rows
      live in this in-memory list only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

# The seven user-facing columns, in display order. This tuple is the single
# authority for the table's shape: header labels, column count and the cell
# order of every row all come from it.
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
EMPTY_CELL = "—"


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
    """

    sent_at: Optional[datetime] = None
    account_id: Optional[str] = None
    symbol: Optional[str] = None
    description: Optional[str] = None
    broker_received_at: Optional[datetime] = None
    core_registered_at: Optional[datetime] = None
    queue_status: Optional[str] = None

    def cells(self) -> tuple:
        """
        The row's seven display strings, in ``ORDER_LOG_COLUMNS`` order.

        This is the only place a row becomes text, so the table can never show
        a cell in the wrong column and never leak a technical value: each
        field is rendered by its own formatter and a missing one is ``—``.
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
    update/reorder/remove/delete operation — a row is appended once, when its
    order is sent, and this base display never mutates it afterwards. No row
    is ever persisted, exported or sent anywhere.
    """

    def __init__(self, rows=None) -> None:
        existing = list(rows) if rows is not None else []
        for row in existing:
            self._check_row(row)
        self._rows: List[OrderLogRow] = existing

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