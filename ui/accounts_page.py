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
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from models.account import AccountValidationError
from ui.account_store import AccountStoreError
from ui import strings as STRINGS

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

        add_group = QGroupBox(STRINGS.GROUP_ADD_ACCOUNT, self)
        add_form = QGridLayout(add_group)

        add_form.addWidget(QLabel(STRINGS.LABEL_ACCOUNT_ID, add_group), 0, 0)
        self.account_id_input = QLineEdit(add_group)
        self.account_id_input.setPlaceholderText(
            STRINGS.PLACEHOLDER_ACCOUNT_ID
        )
        add_form.addWidget(self.account_id_input, 0, 1)

        add_form.addWidget(QLabel(STRINGS.LABEL_BROKER, add_group), 1, 0)
        self.broker_selector = QComboBox(add_group)
        for broker_name in AVAILABLE_BROKERS:
            self.broker_selector.addItem(broker_name)
        add_form.addWidget(self.broker_selector, 1, 1)

        self.add_button = QPushButton(STRINGS.BUTTON_ADD, add_group)
        self.add_button.clicked.connect(self._on_add_clicked)
        add_form.addWidget(self.add_button, 2, 0, 1, 2)

        # UI-9.4: the inline validation message of this form, directly
        # under it. It replaces the former blocking QMessageBox, so an
        # invalid entry is reported in place instead of in a pop-up.
        # Colours come from the ui/theme.py danger role (the "danger"
        # property below); no colour or spacing is invented here. It is
        # empty and hidden while there is nothing to report, so the
        # normal layout is unchanged.
        self.validation_error_label = QLabel("", add_group)
        self.validation_error_label.setProperty("role", "danger")
        self.validation_error_label.setWordWrap(True)
        self.validation_error_label.setVisible(False)
        add_form.addWidget(self.validation_error_label, 3, 0, 1, 2)

        root_layout.addWidget(add_group)

        # ---------------------------------------------
        # Account list (Account ID | Broker | Active)
        # ---------------------------------------------

        list_group = QGroupBox(STRINGS.GROUP_ACCOUNTS, self)
        list_layout = QVBoxLayout(list_group)

        self.accounts_table = QTableWidget(0, 3, list_group)
        self.accounts_table.setHorizontalHeaderLabels(
            [
                STRINGS.TABLE_HEADER_ACCOUNT_ID,
                STRINGS.TABLE_HEADER_BROKER,
                STRINGS.TABLE_HEADER_ACTIVE,
            ]
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
        self.set_active_button = QPushButton(STRINGS.BUTTON_SET_ACTIVE, list_group)
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
        except (AccountStoreError, AccountValidationError):
            self._show_validation_error(STRINGS.DIALOG_INVALID_ACCOUNT)
            return

        self._clear_validation_error()
        self.account_id_input.clear()
        self._refresh_list()

    def _on_set_active_clicked(self):
        """Activate the account of the currently selected row."""
        row = self.accounts_table.currentRow()
        if row < 0:
            self._show_validation_error(
                f"{STRINGS.DIALOG_NO_SELECTION}: "
                f"{STRINGS.DIALOG_SELECT_ACCOUNT_FIRST}"
            )
            return

        account_item = self.accounts_table.item(row, _ACCOUNT_ID_COLUMN)
        try:
            self.store.set_active(account_item.text())
        except AccountStoreError:
            self._show_validation_error(STRINGS.DIALOG_INVALID_ACCOUNT)
            return

        self._clear_validation_error()
        self._refresh_list()

    # ---------------------------------------------------------
    # Inline validation message (UI-9.4)
    # ---------------------------------------------------------

    def _show_validation_error(self, message):
        """
        Show one inline error on the add-account form (UI-9.4).

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
