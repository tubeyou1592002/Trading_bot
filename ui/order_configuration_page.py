"""
ui/order_configuration_page.py — UI-3.1 Order Configuration page.

Presentation of the order-configuration form:

    * Symbol       — explicit user input (state only; NO TSETMC search,
                     NO SymbolResolver, NO network)
    * Symbol info  — display area for the selected symbol's information,
                     fed only from a real models.instrument.Instrument
    * Symbol Status— display placeholder: "Not available" without a
                     verified source; NEVER shown as tradable/permitted
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

Boundaries: no OrderEngine, DispatchCore, SafetyGate, BrokerManager,
InstrumentProvider, Broker API or TSETMC is touched; no Order object is
created; no network of any kind.
"""

from models.order import BUY, SELL

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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

# User-facing side labels — mapped 1:1 to the real project constants.
SIDE_LABELS = ((BUY, "خرید"), (SELL, "فروش"))


class OrderConfigurationPage(QWidget):
    """
    Order Configuration page (form and state only — no execution).
    """

    def __init__(self, account_store, config=None, parent=None):
        super().__init__(parent)

        self.store = account_store
        self.config = config if config is not None else OrderConfiguration()
        self.symbol_text = ""

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
    # Symbol / status (state only — no resolution, no network)
    # ---------------------------------------------------------

    def _on_symbol_edited(self, text):
        """
        Mirror the typed symbol into the config as a text selection only.

        No instrument is resolved or fabricated; without a real
        models.instrument.Instrument the selection stays None and the
        status stays "Not available".
        """
        symbol = (text or "").strip()
        self.symbol_text = symbol
        # No real data yet → no instrument selection, no fake status.
        self._refresh_symbol_info()

    def _refresh_symbol_info(self):
        instrument = self.config.selected_instrument
        if instrument is None:
            self.symbol_name_label.setText("\u2014")
        else:
            self.symbol_name_label.setText(str(getattr(instrument, "name", "")))
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
