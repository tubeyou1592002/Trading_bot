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
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt
import base64
import binascii

from models.account import AccountValidationError
from ui.account_store import AccountStoreError
from ui.credential_store import (
    CredentialNotFoundError,
    CredentialStoreError,
)
from ui import strings as STRINGS

# The only broker implemented in the repository today (UI-2.1).
# Deliberately NOT read from BrokerManager — no broker object is created.
AVAILABLE_BROKERS = ("آگاه",)

_ACCOUNT_ID_COLUMN = 0
_DISPLAY_NAME_COLUMN = 1
_BROKER_COLUMN = 2
_ACTIVE_COLUMN = 3
_LOGIN_STATUS_COLUMN = 4


class AccountsPage(QWidget):
    """
    Accounts page: add accounts, list them and select the active one.

    The page owns no state of its own beyond the widgets: all account
    state lives in the supplied ``AccountStore`` (in-memory), and the page
    mirrors that state in the list.
    """

    def __init__(
        self,
        account_store,
        parent=None,
        *,
        authentication_service_factory=None,
        credential_store_factory=None,
        session_manager_factory=None,
    ):
        super().__init__(parent)

        self.store = account_store
        self._authentication_service_factory = authentication_service_factory
        self._credential_store_factory = credential_store_factory
        self._session_manager_factory = session_manager_factory

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

        add_form.addWidget(QLabel(STRINGS.LABEL_DISPLAY_NAME, add_group), 1, 0)
        self.display_name_input = QLineEdit(add_group)
        add_form.addWidget(self.display_name_input, 1, 1)

        add_form.addWidget(QLabel(STRINGS.LABEL_BROKER, add_group), 2, 0)
        self.broker_selector = QComboBox(add_group)
        for broker_name in AVAILABLE_BROKERS:
            self.broker_selector.addItem(broker_name)
        add_form.addWidget(self.broker_selector, 2, 1)

        self.add_button = QPushButton(STRINGS.BUTTON_ADD, add_group)
        self.add_button.clicked.connect(self._on_add_clicked)
        add_form.addWidget(self.add_button, 3, 0, 1, 2)

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
        add_form.addWidget(self.validation_error_label, 4, 0, 1, 2)

        root_layout.addWidget(add_group)

        # ---------------------------------------------
        # Account list (Account ID | Display name | Broker | Active)
        # ---------------------------------------------

        list_group = QGroupBox(STRINGS.GROUP_ACCOUNTS, self)
        list_layout = QVBoxLayout(list_group)

        self.accounts_table = QTableWidget(0, 5, list_group)
        self.accounts_table.setHorizontalHeaderLabels(
            [
                STRINGS.TABLE_HEADER_ACCOUNT_ID,
                STRINGS.TABLE_HEADER_DISPLAY_NAME,
                STRINGS.TABLE_HEADER_BROKER,
                STRINGS.TABLE_HEADER_ACTIVE,
                STRINGS.LOGIN_STATUS_HEADER,
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
        self.refresh_status_button = QPushButton(STRINGS.BUTTON_REFRESH_STATUS, list_group)
        self.refresh_status_button.clicked.connect(self._on_refresh_status_clicked)
        selection_row.addWidget(self.refresh_status_button)
        self.logout_button = QPushButton(STRINGS.BUTTON_LOGOUT, list_group)
        self.logout_button.clicked.connect(self._on_logout_clicked)
        selection_row.addWidget(self.logout_button)
        selection_row.addStretch(1)
        list_layout.addLayout(selection_row)

        root_layout.addWidget(list_group, stretch=1)

        credentials_group = QGroupBox(STRINGS.GROUP_CREDENTIALS, self)
        credentials_layout = QGridLayout(credentials_group)
        credentials_layout.addWidget(
            QLabel(STRINGS.LABEL_USERNAME, credentials_group), 0, 0
        )
        self.username_input = QLineEdit(credentials_group)
        credentials_layout.addWidget(self.username_input, 0, 1, 1, 2)
        credentials_layout.addWidget(
            QLabel(STRINGS.LABEL_PASSWORD, credentials_group), 1, 0
        )
        self.password_input = QLineEdit(credentials_group)
        self.password_input.setEchoMode(QLineEdit.Password)
        credentials_layout.addWidget(self.password_input, 1, 1, 1, 2)

        self.save_credentials_button = QPushButton(
            STRINGS.BUTTON_SAVE_CREDENTIALS, credentials_group
        )
        self.save_credentials_button.clicked.connect(
            self._on_save_credentials_clicked
        )
        credentials_layout.addWidget(self.save_credentials_button, 2, 1)
        self.delete_credentials_button = QPushButton(
            STRINGS.BUTTON_DELETE_CREDENTIALS, credentials_group
        )
        self.delete_credentials_button.clicked.connect(
            self._on_delete_credentials_clicked
        )
        credentials_layout.addWidget(self.delete_credentials_button, 2, 2)

        self.credentials_message_label = QLabel("", credentials_group)
        self.credentials_message_label.setProperty("role", "danger")
        self.credentials_message_label.setWordWrap(True)
        self.credentials_message_label.setVisible(False)
        credentials_layout.addWidget(self.credentials_message_label, 3, 0, 1, 3)
        root_layout.addWidget(credentials_group)

        login_group = QGroupBox(STRINGS.GROUP_LOGIN, self)
        login_layout = QVBoxLayout(login_group)
        login_buttons = QHBoxLayout()
        self.begin_login_button = QPushButton(STRINGS.BUTTON_BEGIN_LOGIN, login_group)
        self.begin_login_button.clicked.connect(self._on_begin_login_clicked)
        login_buttons.addWidget(self.begin_login_button)
        self.cancel_login_button = QPushButton(STRINGS.BUTTON_CANCEL_LOGIN, login_group)
        self.cancel_login_button.clicked.connect(self._on_cancel_login_clicked)
        self.cancel_login_button.setEnabled(False)
        login_buttons.addWidget(self.cancel_login_button)
        self.complete_login_button = QPushButton(STRINGS.BUTTON_COMPLETE_LOGIN, login_group)
        self.complete_login_button.clicked.connect(self._on_complete_login_clicked)
        self.complete_login_button.setEnabled(False)
        login_buttons.addWidget(self.complete_login_button)
        login_layout.addLayout(login_buttons)
        response_row = QHBoxLayout()
        response_row.addWidget(QLabel(STRINGS.LABEL_CAPTCHA_RESPONSE, login_group))
        self.captcha_response_input = QLineEdit(login_group)
        response_row.addWidget(self.captcha_response_input)
        login_layout.addLayout(response_row)
        self.login_message_label = QLabel("", login_group)
        self.login_message_label.setProperty("role", "danger")
        self.login_message_label.setWordWrap(True)
        self.login_message_label.setVisible(False)
        login_layout.addWidget(self.login_message_label)
        self.challenge_prompt_label = QLabel("", login_group)
        self.challenge_prompt_label.setWordWrap(True)
        self.challenge_prompt_label.setVisible(False)
        login_layout.addWidget(self.challenge_prompt_label)
        self.challenge_image_label = QLabel(login_group)
        self.challenge_image_label.setAlignment(Qt.AlignCenter)
        self.challenge_image_label.setVisible(False)
        login_layout.addWidget(self.challenge_image_label)
        root_layout.addWidget(login_group)
        self._pending_login_account_id = None
        self._pending_authentication_service = None
        self._login_status_by_account = {}

        self._refresh_list()

    # ---------------------------------------------------------
    # Actions
    # ---------------------------------------------------------

    def _on_add_clicked(self):
        """Add an account from the form; invalid input is reported, never guessed."""
        account_id = self.account_id_input.text()
        display_name = self.display_name_input.text()
        broker_name = self.broker_selector.currentText()

        try:
            if not display_name.strip():
                raise AccountStoreError(STRINGS.DIALOG_INVALID_ACCOUNT)
            self.store.add(account_id, broker_name, display_name)
        except (AccountStoreError, AccountValidationError):
            self._show_validation_error(STRINGS.DIALOG_INVALID_ACCOUNT)
            return

        self._clear_validation_error()
        self.account_id_input.clear()
        self.display_name_input.clear()
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

    def _selected_account_record(self):
        row = self.accounts_table.currentRow()
        if row < 0:
            return None
        account_item = self.accounts_table.item(row, _ACCOUNT_ID_COLUMN)
        if account_item is None:
            return None
        account_id = account_item.text()
        return next(
            (record for record in self.store.all_accounts()
             if record.account_id == account_id),
            None,
        )

    def _clear_challenge(self):
        self.challenge_prompt_label.clear()
        self.challenge_prompt_label.setVisible(False)
        self.challenge_image_label.clear()
        self.challenge_image_label.setVisible(False)

    def _login_message(self, message, *, error=True):
        self.login_message_label.setText(message)
        self.login_message_label.setProperty("role", "danger" if error else "success")
        self.login_message_label.setVisible(bool(message))

    def _on_begin_login_clicked(self):
        from brokers.authentication import CHALLENGE_CAPTCHA_IMAGE, LoginChallenge
        if self._pending_login_account_id is not None:
            self._login_message(STRINGS.LOGIN_PENDING)
            return
        self._clear_challenge()
        self.login_message_label.clear()
        self.login_message_label.setVisible(False)
        record = self._selected_account_record()
        if record is None:
            self._login_message(STRINGS.LOGIN_SELECT_ACCOUNT)
            return
        if self._authentication_service_factory is None:
            self._login_message(STRINGS.LOGIN_OPERATION_FAILED)
            return
        try:
            service = self._authentication_service_factory()
            challenge = service.begin_login(record.account_id)
        except Exception:
            self._login_message(STRINGS.LOGIN_OPERATION_FAILED)
            return
        if challenge is None:
            try:
                service.cancel_login(record.account_id)
            except Exception:
                pass
            self._clear_challenge()
            self._login_message(STRINGS.LOGIN_CHALLENGE_UNAVAILABLE)
            return
        if not isinstance(challenge, LoginChallenge):
            try:
                service.cancel_login(record.account_id)
            except Exception:
                pass
            self._clear_challenge()
            self._login_message(STRINGS.LOGIN_CHALLENGE_UNAVAILABLE)
            return
        self._pending_login_account_id = record.account_id
        self._pending_authentication_service = service
        self.cancel_login_button.setEnabled(True)
        self.complete_login_button.setEnabled(True)
        try:
            if challenge.kind != CHALLENGE_CAPTCHA_IMAGE:
                raise ValueError
            if not isinstance(challenge.display_payload, str):
                raise ValueError
            image_bytes = base64.b64decode(challenge.display_payload, validate=True)
            pixmap = QPixmap()
            if not pixmap.loadFromData(image_bytes) or pixmap.isNull():
                raise ValueError
            self.challenge_prompt_label.setText(challenge.prompt)
            self.challenge_prompt_label.setVisible(True)
            self.challenge_image_label.setPixmap(pixmap)
            self.challenge_image_label.setVisible(True)
        except Exception:
            try:
                service.cancel_login(record.account_id)
            except Exception:
                pass
            self._pending_login_account_id = None
            self._pending_authentication_service = None
            self.cancel_login_button.setEnabled(False)
            self.complete_login_button.setEnabled(False)
            self.captcha_response_input.clear()
            self._clear_challenge()
            self._login_message(STRINGS.LOGIN_CHALLENGE_UNAVAILABLE)

    def _on_cancel_login_clicked(self):
        account_id = self._pending_login_account_id
        if account_id is None:
            return
        self._clear_challenge()
        try:
            service = self._pending_authentication_service
            if service is None:
                raise RuntimeError
            service.cancel_login(account_id)
        except Exception:
            self._pending_login_account_id = None
            self._pending_authentication_service = None
            self.cancel_login_button.setEnabled(False)
            self.complete_login_button.setEnabled(False)
            self.captcha_response_input.clear()
            self._login_message(STRINGS.LOGIN_OPERATION_FAILED)
            return
        self._pending_login_account_id = None
        self._pending_authentication_service = None
        self.cancel_login_button.setEnabled(False)
        self.complete_login_button.setEnabled(False)
        self.captcha_response_input.clear()
        self._login_message(STRINGS.LOGIN_CANCELLED, error=False)

    def _on_complete_login_clicked(self):
        account_id = self._pending_login_account_id
        service = self._pending_authentication_service
        response = self.captcha_response_input.text()
        if account_id is None or service is None:
            self._login_message(STRINGS.LOGIN_OPERATION_FAILED)
            self.captcha_response_input.clear()
            return
        if not response.strip():
            self._login_message(STRINGS.LOGIN_RESPONSE_REQUIRED)
            self.captcha_response_input.clear()
            return
        try:
            service.complete_login(account_id, response)
        except Exception:
            self._clear_challenge()
            self._pending_login_account_id = None
            self._pending_authentication_service = None
            self.cancel_login_button.setEnabled(False)
            self.complete_login_button.setEnabled(False)
            self._login_message(STRINGS.LOGIN_OPERATION_FAILED)
        else:
            self._clear_challenge()
            self._pending_login_account_id = None
            self._pending_authentication_service = None
            self.cancel_login_button.setEnabled(False)
            self.complete_login_button.setEnabled(False)
            self._login_message(STRINGS.LOGIN_COMPLETED, error=False)
            self._login_status_by_account.pop(account_id, None)
            self._refresh_one_login_status(account_id, service)
        finally:
            self.captcha_response_input.clear()

    def _on_logout_clicked(self):
        record = self._selected_account_record()
        if record is None:
            self._login_message(STRINGS.LOGIN_SELECT_ACCOUNT)
            return
        if self._pending_login_account_id == record.account_id:
            self._login_message(STRINGS.LOGOUT_PENDING_LOGIN)
            return
        if self._authentication_service_factory is None:
            self._login_message(STRINGS.LOGIN_OPERATION_FAILED)
            return
        try:
            service = self._authentication_service_factory()
            service.logout(record.account_id)
        except Exception:
            if "service" in locals():
                self._refresh_one_login_status(record.account_id, service)
            self._login_message(STRINGS.LOGIN_OPERATION_FAILED)
            return
        self._login_message(STRINGS.LOGOUT_COMPLETED, error=False)
        self._login_status_by_account.pop(record.account_id, None)
        self._refresh_one_login_status(record.account_id, service)

    def _on_refresh_status_clicked(self):
        if self._authentication_service_factory is None:
            self._login_message(STRINGS.LOGIN_OPERATION_FAILED)
            return
        try:
            service = self._authentication_service_factory()
        except Exception:
            self._login_message(STRINGS.LOGIN_STATUS_REFRESH_FAILED)
            return
        failed = False
        for record in self.store.all_accounts():
            self._refresh_one_login_status(record.account_id, service)
            if self._login_status_by_account.get(record.account_id) is None:
                failed = True
        self._login_message(
            STRINGS.LOGIN_STATUS_REFRESH_FAILED if failed else "",
            error=failed,
        )

    def _refresh_one_login_status(self, account_id, service):
        try:
            logged_in = service.is_logged_in(account_id)
            if not isinstance(logged_in, bool):
                raise ValueError
        except Exception:
            self._login_status_by_account[account_id] = None
            status_text = STRINGS.LOGIN_STATUS_UNKNOWN
            self._login_message(STRINGS.LOGIN_STATUS_REFRESH_FAILED)
        else:
            self._login_status_by_account[account_id] = logged_in
            status_text = (
                STRINGS.LOGIN_STATUS_LOGGED_IN
                if logged_in else STRINGS.LOGIN_STATUS_LOGGED_OUT
            )
        for row in range(self.accounts_table.rowCount()):
            item = self.accounts_table.item(row, _ACCOUNT_ID_COLUMN)
            if item is not None and item.text() == account_id:
                self.accounts_table.setItem(
                    row, _LOGIN_STATUS_COLUMN, QTableWidgetItem(status_text)
                )

    def _on_save_credentials_clicked(self):
        username = self.username_input.text()
        password = self.password_input.text()
        try:
            if not username.strip() or not password.strip():
                self._show_credentials_message(
                    STRINGS.CREDENTIALS_INVALID, error=True
                )
                return
            record = self._selected_account_record()
            if record is None:
                self._show_credentials_message(
                    STRINGS.CREDENTIALS_SELECT_ACCOUNT, error=True
                )
                return
            if self._credential_store_factory is None:
                self._show_credentials_message(
                    STRINGS.CREDENTIALS_OPERATION_FAILED, error=True
                )
                return
            credential_store = self._credential_store_factory()
            credential_store.save_credentials(
                record.account_id, record.broker_name, username, password
            )
        except CredentialStoreError:
            self._show_credentials_message(
                STRINGS.CREDENTIALS_OPERATION_FAILED, error=True
            )
        except Exception:
            self._show_credentials_message(
                STRINGS.CREDENTIALS_OPERATION_FAILED, error=True
            )
        else:
            self._show_credentials_message(
                STRINGS.CREDENTIALS_SAVED, error=False
            )
        finally:
            self.username_input.clear()
            self.password_input.clear()

    def _on_delete_credentials_clicked(self):
        try:
            record = self._selected_account_record()
            if record is None:
                self._show_credentials_message(
                    STRINGS.CREDENTIALS_SELECT_ACCOUNT, error=True
                )
                return
            if self._credential_store_factory is None:
                self._show_credentials_message(
                    STRINGS.CREDENTIALS_OPERATION_FAILED, error=True
                )
                return
            credential_store = self._credential_store_factory()
            credential_store.delete_credentials(
                record.account_id, record.broker_name
            )
        except CredentialNotFoundError:
            self._show_credentials_message(
                STRINGS.CREDENTIALS_NOT_FOUND, error=True
            )
        except CredentialStoreError:
            self._show_credentials_message(
                STRINGS.CREDENTIALS_OPERATION_FAILED, error=True
            )
        except Exception:
            self._show_credentials_message(
                STRINGS.CREDENTIALS_OPERATION_FAILED, error=True
            )
        else:
            self._show_credentials_message(
                STRINGS.CREDENTIALS_DELETED, error=False
            )
        finally:
            self.username_input.clear()
            self.password_input.clear()

    def _show_credentials_message(self, message, *, error):
        self.credentials_message_label.setText(message)
        self.credentials_message_label.setProperty(
            "role", "danger" if error else "success"
        )
        self.credentials_message_label.setVisible(bool(message))

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
            display_name_item = QTableWidgetItem(record.display_name)
            broker_item = QTableWidgetItem(record.broker_name)
            active_item = QTableWidgetItem(
                "Yes" if record.account_id == active_id else ""
            )
            login_status = self._login_status_by_account.get(record.account_id)
            login_status_item = QTableWidgetItem(
                STRINGS.LOGIN_STATUS_UNKNOWN if login_status is None else (
                    STRINGS.LOGIN_STATUS_LOGGED_IN if login_status
                    else STRINGS.LOGIN_STATUS_LOGGED_OUT
                )
            )
            self.accounts_table.setItem(row, _ACCOUNT_ID_COLUMN, account_id_item)
            self.accounts_table.setItem(row, _DISPLAY_NAME_COLUMN, display_name_item)
            self.accounts_table.setItem(row, _BROKER_COLUMN, broker_item)
            self.accounts_table.setItem(row, _ACTIVE_COLUMN, active_item)
            self.accounts_table.setItem(
                row, _LOGIN_STATUS_COLUMN, login_status_item
            )
