"""
ui/accounts_page.py — UI-2.1 Accounts page of the User Application.

Presentation of in-memory account management:

    * "Add Account" form  — Account ID input + Broker selector + Add button
    * Account list        — Account ID | Broker | Active columns
    * Active selection    — the user explicitly selects the active account

Boundaries (UI-2.1 / Decision 024):

    * Account identity comes verbatim from the user input and is stored on
      a real ``models.account.Account`` via ``ui.account_store.AccountStore``
      — it is never guessed from an index, symbol or broker.
    * The broker association is the explicit ``broker_name`` string of the
      record; no broker is ever instantiated here, no BrokerManager is
      created and the broker list is NOT read from BrokerManager.
    * The only implemented broker in the repository today is Agah
      (``آگاه``), so the selector currently offers exactly that option.
    * No network, login, credential, broker API or TSETMC access; no
      persistence; no trading/order/symbol functionality.
"""

from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from models.account import AccountValidationError
from ui.account_store import AccountStoreError

# The only broker implemented in the repository today (UI-2.1).
# Deliberately NOT read from BrokerManager — no broker object is created.
AVAILABLE_BROKERS = ("آگاه",)

_ACCOUNT_ID_COLUMN = 0
_BROKER_COLUMN = 1
_ACTIVE_COLUMN = 2


class AccountsPage(QWidget):
    """
    Accounts page: add accounts, list them and select the active one.

    The page owns no state of its own beyond the widgets: all account
    state lives in the supplied ``AccountStore`` (in-memory), and the page
    mirrors that state in the list.
    """

    def __init__(self, account_store, parent=None):
        super().__init__(parent)

        self.store = account_store

        root_layout = QVBoxLayout(self)

        # ---------------------------------------------
        # Add Account group
        # ---------------------------------------------

        add_group = QGroupBox("Add Account", self)
        add_form = QGridLayout(add_group)

        add_form.addWidget(QLabel("Account ID:", add_group), 0, 0)
        self.account_id_input = QLineEdit(add_group)
        self.account_id_input.setPlaceholderText(
            "e.g. ACC-001 \u2014 the account's explicit identity"
        )
        add_form.addWidget(self.account_id_input, 0, 1)

        add_form.addWidget(QLabel("Broker:", add_group), 1, 0)
        self.broker_selector = QComboBox(add_group)
        for broker_name in AVAILABLE_BROKERS:
            self.broker_selector.addItem(broker_name)
        add_form.addWidget(self.broker_selector, 1, 1)

        self.add_button = QPushButton("Add", add_group)
        self.add_button.clicked.connect(self._on_add_clicked)
        add_form.addWidget(self.add_button, 2, 0, 1, 2)

        root_layout.addWidget(add_group)

        # ---------------------------------------------
        # Account list (Account ID | Broker | Active)
        # ---------------------------------------------

        list_group = QGroupBox("Accounts", self)
        list_layout = QVBoxLayout(list_group)

        self.accounts_table = QTableWidget(0, 3, list_group)
        self.accounts_table.setHorizontalHeaderLabels(
            ["Account ID", "Broker", "Active"]
        )
        self.accounts_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch
        )
        self.accounts_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.accounts_table.setSelectionMode(QTableWidget.SingleSelection)
        self.accounts_table.setEditTriggers(QTableWidget.NoEditTriggers)
        list_layout.addWidget(self.accounts_table)

        # Explicit "set active" action on the selected row.
        selection_row = QHBoxLayout()
        self.set_active_button = QPushButton("Set Active", list_group)
        self.set_active_button.clicked.connect(self._on_set_active_clicked)
        selection_row.addWidget(self.set_active_button)
        selection_row.addStretch(1)
        list_layout.addLayout(selection_row)

        root_layout.addWidget(list_group, stretch=1)

        self._refresh_list()

    # ---------------------------------------------------------
    # Actions
    # ---------------------------------------------------------

    def _on_add_clicked(self):
        """Add an account from the form; invalid input is reported, never guessed."""
        account_id = self.account_id_input.text()
        broker_name = self.broker_selector.currentText()

        try:
            self.store.add(account_id, broker_name)
        except (AccountStoreError, AccountValidationError) as exc:
            QMessageBox.warning(self, "Invalid account", str(exc))
            return

        self.account_id_input.clear()
        self._refresh_list()

    def _on_set_active_clicked(self):
        """Activate the account of the currently selected row."""
        row = self.accounts_table.currentRow()
        if row < 0:
            QMessageBox.information(
                self, "No selection", "Select an account in the list first."
            )
            return

        account_item = self.accounts_table.item(row, _ACCOUNT_ID_COLUMN)
        try:
            self.store.set_active(account_item.text())
        except AccountStoreError as exc:
            QMessageBox.warning(self, "Invalid account", str(exc))
            return

        self._refresh_list()

    # ---------------------------------------------------------
    # State mirroring (store -> widgets)
    # ---------------------------------------------------------

    def refresh(self):
        """Public hook to re-mirror the store into the page."""
        self._refresh_list()

    def _refresh_list(self):
        active_id = self.store.active_account_id()

        records = self.store.all_accounts()
        self.accounts_table.setRowCount(len(records))
        for row, record in enumerate(records):
            account_id_item = QTableWidgetItem(str(record.account_id))
            broker_item = QTableWidgetItem(record.broker_name)
            active_item = QTableWidgetItem(
                "Yes" if record.account_id == active_id else ""
            )
            self.accounts_table.setItem(row, _ACCOUNT_ID_COLUMN, account_id_item)
            self.accounts_table.setItem(row, _BROKER_COLUMN, broker_item)
            self.accounts_table.setItem(row, _ACTIVE_COLUMN, active_item)
