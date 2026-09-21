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

Stale-result protection (UI-3.2A): every search carries a monotonically
increasing sequence number; only the result of the LATEST sequence may
update the results list — an older, late-finishing result is discarded.

Boundaries: no OrderEngine, DispatchCore, SafetyGate, BrokerManager,
InstrumentProvider, Broker API or direct TSETMC access from the UI; the
only market seam is the real ``SymbolResolver`` (search/resolve) run on
a background thread. No Order object is created; no ``nsc_id`` exists.
"""

from models.order import BUY, SELL

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ui.order_config_state import (
    SYMBOL_STATUS_NOT_AVAILABLE,
    OrderConfigError,
    OrderConfiguration,
)
from ui.symbol_search_worker import (
    SYMBOL_SEARCH_DEBOUNCE_MS,
    SymbolResolveWorker,
    SymbolSearchWorker,
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

# The three explicit, separated search states.
SEARCH_STATE_IDLE = ""
SEARCH_STATE_SEARCHING = "Searching…"
SEARCH_STATE_NO_RESULTS = "No symbols found"


class OrderConfigurationPage(QWidget):
    """
    Order Configuration page (form and state only — no execution).
    """

    def __init__(self, account_store, config=None, parent=None):
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
        self._searching = False
        self._search_thread = None
        self._search_worker = None
        self._resolve_thread = None
        self._resolve_worker = None

        root_layout = QVBoxLayout(self)

        # ---------------------------------------------
        # Active account (from the existing UI-2.1 store)
        # ---------------------------------------------

        account_group = QGroupBox("Active Account", self)
        account_layout = QHBoxLayout(account_group)
        self.active_account_label = QLabel(self._active_account_text(), account_group)
        account_layout.addWidget(self.active_account_label)
        account_layout.addStretch(1)
        root_layout.addWidget(account_group)

        # ---------------------------------------------
        # Order Configuration group
        # ---------------------------------------------

        form_group = QGroupBox("Order Configuration", self)
        form_grid = QGridLayout(form_group)

        # --- Symbol ---------------------------------------------
        form_grid.addWidget(QLabel("Symbol:", form_group), 0, 0)
        self.symbol_input = QComboBox(form_group)
        self.symbol_input.setEditable(True)
        self.symbol_input.lineEdit().setPlaceholderText(
            "e.g. \u0622\u06a9\u0648 \u2014 resolved by the Core in a later task"
        )
        self.symbol_input.lineEdit().textChanged.connect(self._on_symbol_edited)
        form_grid.addWidget(self.symbol_input, 0, 1)

        # --- Real search results (UI-3.2A) ------------------------
        self.search_status_label = QLabel(SEARCH_STATE_IDLE, form_group)
        self.results_list = QListWidget(form_group)
        self.results_list.setMaximumHeight(120)
        self.results_list.itemActivated.connect(self._on_result_selected)
        self.results_list.itemClicked.connect(self._on_result_selected)
        form_grid.addWidget(self.search_status_label, 0, 2)
        form_grid.addWidget(self.results_list, 0, 3)

        # --- Side ---------------------------------------------
        form_grid.addWidget(QLabel("Side:", form_group), 1, 0)
        side_row = QWidget(form_group)
        side_layout = QHBoxLayout(side_row)
        side_layout.setContentsMargins(0, 0, 0, 0)
        self.side_buttons = {}
        for side_value, label in SIDE_LABELS:
            button = QRadioButton(label, side_row)
            button.clicked.connect(
                lambda checked=False, s=side_value: self._on_side_selected(s)
            )
            self.side_buttons[side_value] = button
            side_layout.addWidget(button)
        side_layout.addStretch(1)
        form_grid.addWidget(side_row, 1, 1)

        # --- Price ---------------------------------------------
        form_grid.addWidget(QLabel("Price:", form_group), 2, 0)
        self.price_input = QLineEdit(form_group)
        self.price_input.setPlaceholderText("Rial \u2014 numeric")
        self.price_input.editingFinished.connect(self._on_price_changed)
        form_grid.addWidget(self.price_input, 2, 1)

        # --- Quantity ---------------------------------------------
        form_grid.addWidget(QLabel("Quantity:", form_group), 3, 0)
        self.quantity_input = QLineEdit(form_group)
        self.quantity_input.setPlaceholderText("numeric")
        self.quantity_input.editingFinished.connect(self._on_quantity_changed)
        form_grid.addWidget(self.quantity_input, 3, 1)

        root_layout.addWidget(form_group)

        # ---------------------------------------------
        # Symbol information / status display area
        # ---------------------------------------------

        info_group = QGroupBox("Symbol Information", self)
        info_form = QFormLayout(info_group)

        self.symbol_name_label = QLabel("\u2014", info_group)
        self.symbol_status_label = QLabel(
            f"Status: {SYMBOL_STATUS_NOT_AVAILABLE}", info_group
        )
        info_form.addRow("Name:", self.symbol_name_label)
        info_form.addRow("Status:", self.symbol_status_label)

        root_layout.addWidget(info_group)

        # ---------------------------------------------
        # Amounts group
        # ---------------------------------------------

        amounts_group = QGroupBox("Amounts", self)
        amounts_form = QFormLayout(amounts_group)

        self.base_amount_label = QLabel("\u2014", amounts_group)
        self.fee_label = QLabel("Not available", amounts_group)
        self.final_amount_label = QLabel("Not available", amounts_group)

        amounts_form.addRow("Base Amount:", self.base_amount_label)
        amounts_form.addRow("Fee:", self.fee_label)
        amounts_form.addRow("Final Amount:", self.final_amount_label)

        root_layout.addWidget(amounts_group)

        root_layout.addStretch(1)

        self._refresh_amounts()
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

    def _on_symbol_edited(self, text):
        """
        Mirror the typed symbol into the config as text only and (re)arm
        the debounce timer for a real background search.

        A new typing session never masquerades as the previous
        selection: the pending debounce is re-armed, and the stale
        selected instrument (no longer matching the new text) is dropped
        explicitly and deterministically.
        """
        symbol = (text or "").strip()
        self.symbol_text = symbol

        # New text invalidates EVERY in-flight generation immediately:
        # any search/resolve result that arrives after this point belongs
        # to a superseded request and may neither update the results list
        # nor (re)store a selection — a late resolve for text the user
        # has already replaced must never set selected_instrument.
        self._search_sequence += 1

        # The previously displayed results belong to the superseded
        # request: they are removed from the UI and their identity list
        # is dropped, so an old row can never be clicked into a new
        # selection ("typed text != selected instrument").
        self.results_list.clear()
        self._latest_results = []

        if not symbol:
            # Empty input: no search call at all; the pending debounce is
            # cancelled.
            self._debounce_timer.stop()
            self._set_search_status(SEARCH_STATE_IDLE)
            self.config.select_instrument(None)
            self._refresh_symbol_info()
            return

        # New text invalidates the previous selection explicitly: typed
        # text must never be treated as the previously selected
        # instrument until a real result is picked.
        self._set_search_status(SEARCH_STATE_IDLE)
        self.config.select_instrument(None)
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
        self.results_list.clear()
        self._latest_results = list(results)
        if not results:
            self._set_search_status(SEARCH_STATE_NO_RESULTS)
            return
        for index, result in enumerate(results):
            item = QListWidgetItem(
                f"{result.get('symbol') or ''} \u2014 {result.get('name') or ''}",
                self.results_list,
            )
            # The result's identity travels as the INDEX into the page's
            # shared list of the real resolver result objects — the
            # object itself never passes through a Qt signal (signals
            # marshall/copy payloads), and identity is never rebuilt by
            # parsing the display text. The row is also tagged with its
            # search generation so a superseded row can never resolve.
            item.setData(RESULT_DATA_ROLE, index)
            item.setData(RESULT_SEQUENCE_ROLE, sequence)
            self.results_list.addItem(item)
        self._set_search_status(SEARCH_STATE_IDLE)

    def _on_search_failed(self, sequence, message):
        """
        A failed search never crashes the UI and never shows stale
        results; a newer generation's results are untouched.
        """
        if sequence != self._search_sequence:
            return  # a stale failure must not clobber the newer state
        self._searching = False
        self.results_list.clear()
        self._set_search_status(f"Search failed: {message}")

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

    def _on_resolve_failed(self, sequence, message):
        """Resolve failure: previous selection stays, nothing fabricated."""
        if sequence != self._search_sequence:
            return
        self._set_search_status(f"Resolve failed: {message}")

    # ---------------------------------------------------------
    # Symbol info / status display
    # ---------------------------------------------------------

    def _refresh_symbol_info(self):
        instrument = self.config.selected_instrument
        if instrument is None:
            self.symbol_name_label.setText("\u2014")
        else:
            # Display comes from the REAL Instrument object only.
            market = getattr(instrument, "market", None)
            market_part = f" ({market})" if market else ""
            self.symbol_name_label.setText(
                f"{getattr(instrument, 'symbol', '')} \u2014 "
                f"{getattr(instrument, 'name', '')}{market_part}"
            )
        # Fail-closed display: without a verified source this is never
        # "tradable"/"permitted".
        self.symbol_status_label.setText(
            f"Status: {self.config.symbol_status()}"
        )

    # ---------------------------------------------------------
    # Side / Price / Quantity
    # ---------------------------------------------------------

    def _on_side_selected(self, side):
        try:
            self.config.set_side(side)
        except OrderConfigError as exc:  # pragma: no cover — buttons are fixed
            QMessageBox.warning(self, "Invalid side", str(exc))

    def _on_price_changed(self):
        text = self.price_input.text().strip()
        if not text:
            self.config.price = None
            self._refresh_amounts()
            return
        try:
            # The Core Order contract is price: int — integer input only.
            # Fractional input ("15000.5") is rejected, and the previous
            # valid state is preserved.
            self.config.set_price(int(text))
        except (OrderConfigError, ValueError) as exc:
            QMessageBox.warning(self, "Invalid price", str(exc))
        self._refresh_amounts()

    def _on_quantity_changed(self):
        text = self.quantity_input.text().strip()
        if not text:
            self.config.quantity = None
            self._refresh_amounts()
            return
        try:
            # The Core Order contract is quantity: int — integer input
            # only. Fractional input ("500.5") is rejected, and the
            # previous valid state is preserved.
            self.config.set_quantity(int(text))
        except (OrderConfigError, ValueError) as exc:
            QMessageBox.warning(self, "Invalid quantity", str(exc))
        self._refresh_amounts()

    # ---------------------------------------------------------
    # Amounts
    # ---------------------------------------------------------

    def _refresh_amounts(self):
        base = self.config.base_amount()
        # base is an int (price * quantity, both int per the Core Order
        # contract) — format it as a plain integer, no scientific notation.
        self.base_amount_label.setText(
            "\u2014" if base is None else f"{base:,}".replace(",", "\u066c")
        )
        # Fee / Final Amount: no contract exists — never fabricated.
        self.fee_label.setText("Not available")
        self.final_amount_label.setText("Not available")

    # ---------------------------------------------------------
    # Account display (verbatim from the UI-2.1 store)
    # ---------------------------------------------------------

    def _active_account_text(self):
        active_id = self.store.active_account_id()
        if active_id is None:
            # No fallback to accounts[0]/first/default — shown transparently.
            return "No active account \u2014 select one on the Accounts page"
        record = self.store.get(active_id)
        return f"{record.account_id} → {record.broker_name}"

    def refresh_active_account(self):
        """Re-mirror the active account from the store into the page."""
        self.active_account_label.setText(self._active_account_text())
