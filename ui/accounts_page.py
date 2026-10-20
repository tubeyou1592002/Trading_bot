"""RTL account management page with isolated, explicitly triggered authentication."""

import base64
import math
import uuid

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from models.account import AccountValidationError
from ui.account_store import AccountStoreError
from ui.credential_store import CredentialStoreError
from ui import strings as STRINGS

AVAILABLE_BROKERS = ("آگاه",)
_ID, _DISPLAY, _ACTIVE, _STATUS, _PURCHASE_POWER, _ACTIONS = range(6)


def _configure_chevron_combo(combo, object_name):
    """Opt one account-page combo into the shared chevron-down icon."""
    combo.setObjectName(object_name)
    combo.setProperty("chevron", True)


class AccountsPage(QWidget):
    def __init__(self, account_store, parent=None, *,
                 authentication_service_factory=None,
                 credential_store_factory=None, session_manager_factory=None,
                 lifecycle_listener=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.RightToLeft)
        self.store = account_store
        self._authentication_service_factory = authentication_service_factory
        self._credential_store_factory = credential_store_factory
        self._session_manager_factory = session_manager_factory
        # Block 9 Task 9B: optional observer notified of account lifecycle
        # events ("logout" / "delete" / "broker_changed"). It lets the owner
        # (MainWindow) stop only the affected account's feedback runtime.
        # Absent for direct/offline construction — the page stays usable.
        self._lifecycle_listener = lifecycle_listener
        self._pending_login_account_id = None
        self._pending_authentication_service = None
        self._login_status_by_account = {}
        # account_id -> validated numeric tradable balance (purchase power).
        # Fetched only on a successful login; table rebuilds/sorts read this
        # cache and never call the broker API again.
        self._purchase_power_by_account = {}
        self._captcha_dialog = None
        self._cancelled_login_account_id = None

        root = QVBoxLayout(self)
        title = QLabel(STRINGS.ACCOUNTS_PAGE_TITLE, self)
        title.setObjectName("pageTitle")
        root.addWidget(title)
        subtitle = QLabel(STRINGS.ACCOUNTS_PAGE_SUBTITLE, self)
        subtitle.setWordWrap(True)
        subtitle.setObjectName("pageSubtitle")
        root.addWidget(subtitle)

        # The add-account form lives inside a right-to-left popup, opened from
        # the button under the accounts table. Nothing of it is rendered on the
        # main view; its widgets still exist as page attributes so the existing
        # validation / credential behavior is unchanged.
        add_dialog = QDialog(self)
        add_dialog.setWindowTitle(STRINGS.ADD_ACCOUNT_DIALOG_TITLE)
        add_dialog.setLayoutDirection(Qt.RightToLeft)
        add_dialog.setModal(True)
        self._add_dialog = add_dialog
        dialog_layout = QVBoxLayout(add_dialog)

        add_group = QGroupBox(STRINGS.GROUP_ADD_ACCOUNT, add_dialog)
        form = QGridLayout(add_group)
        self.display_name_input = QLineEdit(add_group)
        self.display_name_input.setPlaceholderText(STRINGS.PLACEHOLDER_DISPLAY_NAME)
        self.broker_selector = QComboBox(add_group)
        _configure_chevron_combo(
            self.broker_selector, "addAccountBrokerCombo"
        )
        self.broker_selector.addItems(AVAILABLE_BROKERS)
        self.username_input = QLineEdit(add_group)
        self.username_input.setPlaceholderText(STRINGS.PLACEHOLDER_USERNAME)
        self.password_input = QLineEdit(add_group)
        self.password_input.setPlaceholderText(STRINGS.PLACEHOLDER_PASSWORD)
        self.password_input.setEchoMode(QLineEdit.Password)
        for col, (label, widget) in enumerate((
            (STRINGS.LABEL_DISPLAY_NAME, self.display_name_input),
            (STRINGS.LABEL_BROKER, self.broker_selector),
            (STRINGS.LABEL_USERNAME, self.username_input),
            (STRINGS.LABEL_PASSWORD, self.password_input),
        )):
            form.addWidget(QLabel(label, add_group), 0, col)
            form.addWidget(widget, 1, col)
        self.add_button = QPushButton(STRINGS.BUTTON_REGISTER_ACCOUNT, add_group)
        self.add_button.clicked.connect(self._on_add_clicked)
        form.addWidget(self.add_button, 2, 0, 1, 2)
        self.cancel_add_button = QPushButton(STRINGS.BUTTON_CANCEL, add_group)
        self.cancel_add_button.clicked.connect(self._on_add_cancel_clicked)
        form.addWidget(self.cancel_add_button, 2, 2, 1, 2)
        auto_id_note = QLabel(STRINGS.NOTE_AUTO_ACCOUNT_ID, add_group)
        form.addWidget(auto_id_note, 3, 0, 1, 4)
        self.validation_error_label = QLabel("", add_group)
        self.validation_error_label.setProperty("role", "danger")
        self.validation_error_label.setWordWrap(True)
        self.validation_error_label.hide()
        form.addWidget(self.validation_error_label, 4, 0, 1, 4)
        dialog_layout.addWidget(add_group)

        group = QGroupBox(STRINGS.GROUP_ACCOUNTS, self)
        list_layout = QVBoxLayout(group)
        list_layout.addWidget(QLabel(STRINGS.ACCOUNTS_LIST_SUBTITLE, group))
        tools = QHBoxLayout()
        tools.addWidget(QLabel(STRINGS.LABEL_SORT, group))
        self.sort_selector = QComboBox(group)
        _configure_chevron_combo(self.sort_selector, "sortAccountsCombo")
        self.sort_selector.addItem(STRINGS.SORT_MANUAL, "manual")
        self.sort_selector.addItem(STRINGS.SORT_BY_NAME_ASC, "name")
        self.sort_selector.currentIndexChanged.connect(self._refresh_list)
        tools.addWidget(self.sort_selector)
        self.refresh_status_button = QPushButton(STRINGS.BUTTON_REFRESH_STATUS, group)
        self.refresh_status_button.clicked.connect(self._on_refresh_status_clicked)
        tools.addWidget(self.refresh_status_button)
        self.logout_button = QPushButton(STRINGS.BUTTON_LOGOUT, group)
        self.logout_button.clicked.connect(self._on_logout_clicked)
        tools.addWidget(self.logout_button)
        tools.addStretch(1)
        list_layout.addLayout(tools)
        self.accounts_table = QTableWidget(0, 6, group)
        self.accounts_table.setHorizontalHeaderLabels([
            "شناسهٔ داخلی", STRINGS.TABLE_HEADER_ACCOUNT_BROKER,
            STRINGS.TABLE_HEADER_CURRENT_USE, STRINGS.TABLE_HEADER_LOGIN_STATUS,
            STRINGS.TABLE_HEADER_PURCHASE_POWER, STRINGS.TABLE_HEADER_ACTIONS,
        ])
        self.accounts_table.setColumnHidden(_ID, True)
        self.accounts_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.accounts_table.setSelectionMode(QTableWidget.SingleSelection)
        self.accounts_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.accounts_table.verticalHeader().hide()
        self.accounts_table.horizontalHeader().setSectionResizeMode(_DISPLAY, QHeaderView.Stretch)
        self.accounts_table.horizontalHeader().setSectionResizeMode(_ACTIONS, QHeaderView.ResizeToContents)
        self.accounts_table.horizontalHeader().setStretchLastSection(True)
        list_layout.addWidget(self.accounts_table, 1)
        self.accounts_table.itemSelectionChanged.connect(
            self._update_selection_actions)
        add_row = QHBoxLayout()
        self.add_account_button = QPushButton(STRINGS.BUTTON_ADD_ACCOUNT, group)
        self.add_account_button.clicked.connect(self._open_add_dialog)
        add_row.addWidget(self.add_account_button)
        self.edit_account_button = QPushButton(STRINGS.BUTTON_EDIT, group)
        self.edit_account_button.clicked.connect(self._on_edit_clicked)
        self.edit_account_button.setEnabled(False)
        add_row.addWidget(self.edit_account_button)
        self.delete_account_button = QPushButton(STRINGS.BUTTON_DELETE, group)
        self.delete_account_button.clicked.connect(self._on_delete_clicked)
        self.delete_account_button.setEnabled(False)
        add_row.addWidget(self.delete_account_button)
        add_row.addStretch(1)
        list_layout.addLayout(add_row)
        self.login_message_label = QLabel("", group)
        self.login_message_label.setWordWrap(True)
        self.login_message_label.hide()
        list_layout.addWidget(self.login_message_label)
        list_layout.addWidget(QLabel(STRINGS.ACCOUNTS_SECURITY_NOTE, group))
        root.addWidget(group, 1)
        self.refresh()

    def _records(self):
        records = list(self.store.all_accounts())
        if self.sort_selector.currentData() == "name":
            records.sort(key=lambda record: record.display_name.casefold())
        return records

    def _refresh_list(self, *_):
        records = self._records()
        active_id = self.store.active_account_id()
        selected_id = self._selected_account_id()
        self.accounts_table.setRowCount(len(records))
        selection_restored = False
        for row, record in enumerate(records):
            identity = QTableWidgetItem(record.account_id)
            identity.setData(Qt.UserRole, record.account_id)
            self.accounts_table.setItem(row, _ID, identity)
            details = QTableWidgetItem(f"{record.display_name}\n{record.broker_name}")
            details.setData(Qt.UserRole, record.account_id)
            self.accounts_table.setItem(row, _DISPLAY, details)
            status = self._login_status_by_account.get(record.account_id)
            text = (STRINGS.LOGIN_STATUS_UNKNOWN if status is None else
                    STRINGS.LOGIN_STATUS_LOGGED_IN if status else STRINGS.LOGIN_STATUS_LOGGED_OUT)
            is_active = record.account_id == active_id
            self.accounts_table.setItem(row, _ACTIVE, QTableWidgetItem(
                STRINGS.CURRENT_USE_ACTIVE if is_active else STRINGS.CURRENT_USE_INACTIVE))
            self.accounts_table.setItem(row, _STATUS, QTableWidgetItem(text))
            power = self._purchase_power_by_account.get(record.account_id)
            power_item = QTableWidgetItem(
                STRINGS.PURCHASE_POWER_UNKNOWN
                if power is None else STRINGS.format_grouped(power)
            )
            if power is not None:
                power_item.setData(Qt.UserRole, power)
            self.accounts_table.setItem(row, _PURCHASE_POWER, power_item)
            actions = QWidget(self.accounts_table)
            row_layout = QHBoxLayout(actions)
            row_layout.setContentsMargins(4, 3, 4, 3)
            self._button(row_layout, STRINGS.BUTTON_SET_ACTIVE, lambda _, i=record.account_id: self._activate(i), not is_active)
            self._button(row_layout, STRINGS.BUTTON_LOGIN if self._pending_login_account_id != record.account_id else STRINGS.BUTTON_LOGIN_PENDING,
                         lambda _, i=record.account_id: self._begin_login(i), self._pending_login_account_id is None)
            if status:
                self._button(row_layout, STRINGS.BUTTON_LOGOUT, lambda _, i=record.account_id: self._logout(i))
            if self.sort_selector.currentData() == "manual":
                self._button(row_layout, "↑", lambda _, i=record.account_id, r=row: self._move(i, r-1), row > 0)
                self._button(row_layout, "↓", lambda _, i=record.account_id, r=row: self._move(i, r+1), row < len(records)-1)
            row_layout.addStretch(1)
            self.accounts_table.setCellWidget(row, _ACTIONS, actions)
            self.accounts_table.setRowHeight(row, 58)
            if selected_id == record.account_id:
                self.accounts_table.setCurrentCell(row, _DISPLAY)
                selection_restored = True
        if selected_id is not None and not selection_restored:
            # The previously selected account no longer exists: drop the
            # selection (Qt would otherwise keep pointing at a shifted row).
            self.accounts_table.clearSelection()
            self.accounts_table.setCurrentItem(None)
        self.accounts_table.setColumnHidden(_ID, True)
        self.accounts_table.setColumnHidden(_ID, True)
        self.accounts_table.setColumnWidth(_DISPLAY, 250)
        self.accounts_table.setColumnWidth(_ACTIVE, 130)
        self.accounts_table.setColumnWidth(_STATUS, 160)
        self.accounts_table.setColumnWidth(_PURCHASE_POWER, 140)
        # Action widgets are deliberately placed in the visible last column.
        self._update_selection_actions()

    def _button(self, layout, text, callback, enabled=True):
        button = QPushButton(text, self.accounts_table)
        button.setEnabled(enabled)
        button.clicked.connect(callback)
        layout.addWidget(button)

    def _selected_account_id(self):
        row = self.accounts_table.currentRow() if hasattr(self, "accounts_table") else -1
        details = self.accounts_table.item(row, _DISPLAY) if row >= 0 else None
        return details.data(Qt.UserRole) if details is not None else None

    def _selected_account_record(self):
        account_id = self._selected_account_id()
        return next((r for r in self.store.all_accounts() if r.account_id == account_id), None)

    def _update_selection_actions(self, *_):
        """Edit/Delete stay disabled until a row (an existing account) is selected."""
        has_selection = self._selected_account_id() is not None
        self.edit_account_button.setEnabled(has_selection)
        self.delete_account_button.setEnabled(has_selection)

    def _on_edit_clicked(self):
        account_id = self._selected_account_id()
        if account_id is None:
            return
        self._edit_account(account_id)

    def _on_delete_clicked(self):
        account_id = self._selected_account_id()
        if account_id is None:
            return
        self._delete_account(account_id)

    def _report(self, message, error=False):
        self.login_message_label.setText(message)
        self.login_message_label.setProperty("role", "danger" if error else "success")
        self.login_message_label.setVisible(bool(message))

    @staticmethod
    def _valid_purchase_power(value):
        """Return a displayable account balance, or None when unusable."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not math.isfinite(value) or value < 0:
            return None
        return value

    def _read_purchase_power(self, service, account_id):
        """
        Read this account's tradable balance through the generic contract.

        The service/adapter owns broker-specific details and the
        account-scoped runtime/session; the page never selects a broker or
        builds an endpoint path itself. Missing support is treated exactly
        like a failed read (unknown display), never guessed.
        """
        getter = getattr(service, "get_purchase_power", None)
        if not callable(getter):
            getter = getattr(service, "get_tradable_balance", None)
        if callable(getter):
            return getter(account_id)

        adapter_getter = getattr(service, "get_adapter", None)
        if callable(adapter_getter):
            adapter = adapter_getter(account_id)
            if adapter is not None:
                for name in ("get_purchase_power", "get_tradable_balance"):
                    method = getattr(adapter, name, None)
                    if callable(method):
                        return method()
        raise AttributeError("purchase power is not available")

    def _load_purchase_power(self, service, account_id):
        """
        Fetch once after a successful login and cache per account.

        Any failure (unsupported broker, network/API error, invalid value)
        resolves to the safe "unknown" state. Provider details are never
        shown in the UI.
        """
        try:
            value = self._valid_purchase_power(
                self._read_purchase_power(service, account_id)
            )
        except Exception:
            value = None
        self._purchase_power_by_account.pop(account_id, None)
        if value is not None:
            self._purchase_power_by_account[account_id] = value

    def _notify_lifecycle(self, event, account_id, broker_name=None):
        """Report an account lifecycle event to the optional observer."""
        listener = self._lifecycle_listener
        if listener is None:
            return
        try:
            listener(event, account_id, broker_name)
        except Exception:
            # The observer is best-effort: a failing listener must never
            # disturb the account UI flow.
            pass

    def _on_add_clicked(self):
        display = self.display_name_input.text().strip()
        username, password = self.username_input.text(), self.password_input.text()
        if not display:
            self._show_validation_error(STRINGS.FORM_DISPLAY_NAME_REQUIRED)
            return
        if not username.strip() or not password.strip():
            self._show_validation_error(STRINGS.FORM_CREDENTIALS_REQUIRED)
            return
        account_id = "ACC-" + uuid.uuid4().hex
        try:
            self.store.add(account_id, self.broker_selector.currentText(), display)
            if self._credential_store_factory is None:
                self.store.delete(account_id)
                raise CredentialStoreError("Credential storage unavailable")
            self._credential_store_factory().save_credentials(
                account_id, self.broker_selector.currentText(), username, password)
        except Exception:
            try:
                if any(r.account_id == account_id for r in self.store.all_accounts()):
                    self.store.delete(account_id)
            except Exception:
                pass
            self._show_validation_error(STRINGS.ACCOUNT_OPERATION_FAILED)
            return
        for widget in (self.display_name_input, self.username_input, self.password_input):
            widget.clear()
        self._clear_validation_error()
        self._report(STRINGS.ACCOUNT_ADD_SUCCESS)
        self._add_dialog.close()
        self._refresh_list()

    def _open_add_dialog(self):
        """Open the right-to-left add-account popup with a clean form."""
        for widget in (self.display_name_input, self.username_input, self.password_input):
            widget.clear()
        self._clear_validation_error()
        self._add_dialog.show()

    def _on_add_cancel_clicked(self):
        """Dismiss the add-account popup without creating any account."""
        for widget in (self.display_name_input, self.username_input, self.password_input):
            widget.clear()
        self._clear_validation_error()
        self._add_dialog.close()

    def _activate(self, account_id):
        try:
            self.store.set_active(account_id)
            self._refresh_list()
        except AccountStoreError:
            self._report(STRINGS.ACCOUNT_OPERATION_FAILED, True)

    def _begin_login(self, account_id):
        from brokers.authentication import CHALLENGE_CAPTCHA_IMAGE, LoginChallenge
        if self._pending_login_account_id is not None:
            self._report(STRINGS.LOGIN_PENDING, True)
            return
        if self._authentication_service_factory is None:
            self._report(STRINGS.ACCOUNT_OPERATION_FAILED, True)
            return
        service = None
        challenge_received = False
        try:
            service = self._authentication_service_factory()
            challenge = service.begin_login(account_id)
            challenge_received = True
            if not isinstance(challenge, LoginChallenge):
                candidate = getattr(challenge, "challenge", None)
                if isinstance(candidate, LoginChallenge):
                    challenge = candidate
            if not isinstance(challenge, LoginChallenge) or challenge.kind != CHALLENGE_CAPTCHA_IMAGE:
                raise ValueError
            if not isinstance(challenge.display_payload, str):
                raise ValueError
            data = base64.b64decode(challenge.display_payload, validate=True)
            pixmap = QPixmap()
            if not pixmap.loadFromData(data) or pixmap.isNull():
                raise ValueError
        except Exception:
            if service is not None and challenge_received:
                try:
                    service.cancel_login(account_id)
                except Exception:
                    # Never surface provider details; keep this account out of
                    # the pending UI state even if cleanup itself fails.
                    self._pending_login_account_id = None
                    self._pending_authentication_service = None
                    self._captcha_dialog = None
            self._report(STRINGS.LOGIN_CHALLENGE_UNAVAILABLE, True)
            return
        self._pending_login_account_id = account_id
        self._pending_authentication_service = service
        self._cancelled_login_account_id = None
        dialog = QDialog(self)
        dialog.setWindowTitle(STRINGS.CAPTCHA_DIALOG_TITLE)
        dialog.setLayoutDirection(Qt.RightToLeft)
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        prompt = QLabel(STRINGS.CAPTCHA_DIALOG_PROMPT.format(self.store.get(account_id).display_name), dialog)
        prompt.setWordWrap(True)
        layout.addWidget(prompt)
        image = QLabel(dialog)
        image.setAlignment(Qt.AlignCenter)
        image.setPixmap(pixmap.scaled(420, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(image)
        entry = QLineEdit(dialog)
        entry.setPlaceholderText(STRINGS.CAPTCHA_RESPONSE_PLACEHOLDER)
        entry.setAccessibleName(STRINGS.CAPTCHA_RESPONSE_LABEL)
        layout.addWidget(entry)
        error = QLabel("", dialog)
        error.setProperty("role", "danger")
        layout.addWidget(error)
        buttons = QDialogButtonBox(dialog)
        confirm = buttons.addButton(STRINGS.BUTTON_CAPTCHA_CONFIRM, QDialogButtonBox.AcceptRole)
        cancel = buttons.addButton(STRINGS.BUTTON_CANCEL, QDialogButtonBox.RejectRole)
        layout.addWidget(buttons)
        confirm.clicked.connect(lambda: self._complete_login_dialog(account_id, entry, error, dialog))
        cancel.clicked.connect(lambda: self._cancel_login(dialog))
        dialog.rejected.connect(lambda: self._cancel_login(dialog) if self._pending_login_account_id else None)
        self._captcha_dialog = dialog
        self._refresh_list()
        dialog.show()

    def _complete_login_dialog(self, account_id, entry, error, dialog):
        response = entry.text()
        if not response.strip():
            error.setText(STRINGS.CAPTCHA_RESPONSE_REQUIRED)
            return
        service = self._pending_authentication_service
        try:
            service.complete_login(account_id, response)
        except Exception:
            self._login_status_by_account[account_id] = None
            self._purchase_power_by_account.pop(account_id, None)
            self._report(STRINGS.ACCOUNT_OPERATION_FAILED, True)
            self._finish_login(dialog)
            return
        self._login_status_by_account[account_id] = True
        # Fetch the account's tradable balance once, only after this exact
        # account's login succeeded. Later table rebuilds/sorts use the cache.
        self._load_purchase_power(service, account_id)
        self._report(STRINGS.LOGIN_COMPLETED)
        self._finish_login(dialog)
        self._refresh_list()

    def _cancel_login(self, dialog=None):
        account_id = self._pending_login_account_id
        service = self._pending_authentication_service
        if account_id is None:
            return
        try:
            service.cancel_login(account_id)
        except Exception:
            self._report(STRINGS.ACCOUNT_OPERATION_FAILED, True)
        else:
            self._cancelled_login_account_id = account_id
            self._report(STRINGS.LOGIN_CANCELLED)
        self._finish_login(dialog)
        self._refresh_list()

    def _finish_login(self, dialog=None):
        self._pending_login_account_id = None
        self._pending_authentication_service = None
        self._captcha_dialog = None
        if dialog is not None:
            dialog.close()

    def _on_begin_login_clicked(self):
        account_id = self._selected_account_id()
        if account_id is None:
            self._report(STRINGS.LOGIN_SELECT_ACCOUNT, True)
            return
        self._begin_login(account_id)

    def _on_cancel_login_clicked(self):
        self._cancel_login(self._captcha_dialog)

    def _on_complete_login_clicked(self):
        # The response editor belongs exclusively to the active challenge dialog.
        if self._captcha_dialog is None:
            return
        entry = self._captcha_dialog.findChild(QLineEdit)
        labels = self._captcha_dialog.findChildren(QLabel)
        error = next((label for label in labels if label.text() == ""), None)
        if entry is not None and error is not None:
            self._complete_login_dialog(
                self._pending_login_account_id, entry, error, self._captcha_dialog
            )

    def _logout(self, account_id):
        service = None
        logged_out = False
        try:
            service = self._authentication_service_factory()
            service.logout(account_id)
            self._login_status_by_account[account_id] = False
            self._report(STRINGS.LOGOUT_COMPLETED)
            logged_out = True
        except Exception:
            try:
                if service is None:
                    service = self._authentication_service_factory()
                status = service.is_logged_in(account_id)
                self._login_status_by_account[account_id] = status if isinstance(status, bool) else None
            except Exception:
                self._login_status_by_account[account_id] = None
            self._report(STRINGS.LOGIN_OPERATION_FAILED, True)
        if logged_out:
            self._purchase_power_by_account.pop(account_id, None)
            self._notify_lifecycle(
                "logout", account_id, self._broker_name_of(account_id)
            )
        self._refresh_list()

    def _broker_name_of(self, account_id):
        """The account's current broker name, or None (fail-closed)."""
        try:
            return self.store.get(account_id).broker_name
        except Exception:
            return None

    def _on_logout_clicked(self):
        account_id = self._selected_account_id()
        if account_id is None:
            self._report(STRINGS.LOGIN_SELECT_ACCOUNT, True)
        elif account_id == self._pending_login_account_id:
            self._report(STRINGS.LOGOUT_PENDING_LOGIN, True)
        else:
            self._logout(account_id)

    def _on_refresh_status_clicked(self):
        if self._authentication_service_factory is None:
            self._report(STRINGS.LOGIN_STATUS_REFRESH_FAILED, True)
            return
        try:
            service = self._authentication_service_factory()
        except Exception:
            self._report(STRINGS.LOGIN_STATUS_REFRESH_FAILED, True)
            return
        failed = False
        for record in self.store.all_accounts():
            try:
                result = service.is_logged_in(record.account_id)
                if not isinstance(result, bool):
                    raise ValueError("invalid login status")
                self._login_status_by_account[record.account_id] = result
            except Exception:
                self._login_status_by_account[record.account_id] = None
                failed = True
        self._refresh_list()
        if failed:
            self._report(STRINGS.LOGIN_STATUS_REFRESH_FAILED, True)

    def _edit_account(self, account_id):
        record = self.store.get(account_id)
        dialog = QDialog(self)
        dialog.setWindowTitle(STRINGS.EDIT_DIALOG_TITLE)
        dialog.setLayoutDirection(Qt.RightToLeft)
        layout = QFormLayout(dialog)
        name = QLineEdit(record.display_name, dialog)
        broker = QComboBox(dialog)
        _configure_chevron_combo(broker, "editAccountBrokerCombo")
        broker.addItems(AVAILABLE_BROKERS)
        broker.setCurrentText(record.broker_name)
        username = QLineEdit(dialog)
        new_password = QLineEdit(dialog)
        new_password.setEchoMode(QLineEdit.Password)
        new_password.setPlaceholderText(STRINGS.PLACEHOLDER_NEW_PASSWORD)
        layout.addRow(STRINGS.LABEL_DISPLAY_NAME, name)
        layout.addRow(STRINGS.LABEL_BROKER, broker)
        layout.addRow(STRINGS.LABEL_USERNAME, username)
        layout.addRow(STRINGS.LABEL_NEW_PASSWORD, new_password)
        layout.addRow(QLabel(STRINGS.EDIT_PASSWORD_NOTE, dialog))
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, parent=dialog)
        buttons.button(QDialogButtonBox.Save).setText(STRINGS.BUTTON_SAVE_CHANGES)
        buttons.button(QDialogButtonBox.Cancel).setText(STRINGS.BUTTON_CANCEL)
        layout.addRow(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec() != QDialog.Accepted:
            return
        if not name.text().strip():
            self._report(STRINGS.EDIT_DISPLAY_NAME_REQUIRED, True)
            return
        if username.text().strip() or new_password.text():
            if not username.text().strip() or not new_password.text():
                self._report(STRINGS.EDIT_CREDENTIALS_PAIR_REQUIRED, True)
                return
            try:
                self._credential_store_factory().save_credentials(
                    account_id, broker.currentText(), username.text(), new_password.text())
            except Exception:
                self._report(STRINGS.ACCOUNT_OPERATION_FAILED, True)
                return
        try:
            updated = self.store.update(account_id, broker_name=broker.currentText(), display_name=name.text())
        except Exception:
            self._report(STRINGS.ACCOUNT_OPERATION_FAILED, True)
            return
        if record.broker_name != updated.broker_name:
            # The account moved to another broker: stop the old runtime only
            # and drop the previous broker's cached balance.
            self._purchase_power_by_account.pop(account_id, None)
            self._notify_lifecycle(
                "broker_changed", account_id, record.broker_name
            )
        self._refresh_list()

    def _delete_account(self, account_id):
        record = self.store.get(account_id)
        answer = QMessageBox.question(self, STRINGS.DELETE_DIALOG_TITLE,
                                      STRINGS.DELETE_DIALOG_CONFIRM.format(record.display_name))
        if answer != QMessageBox.Yes:
            return
        deleted = False
        try:
            if self._credential_store_factory is not None:
                try:
                    self._credential_store_factory().delete_credentials(account_id, record.broker_name)
                except Exception:
                    pass
            self.store.delete(account_id)
            self._login_status_by_account.pop(account_id, None)
            self._purchase_power_by_account.pop(account_id, None)
            deleted = True
        except Exception:
            self._report(STRINGS.ACCOUNT_OPERATION_FAILED, True)
        if deleted:
            self._notify_lifecycle("delete", account_id, record.broker_name)
        self._refresh_list()

    def _move(self, account_id, position):
        try:
            records = list(self.store.all_accounts())
            self.store.move(account_id, max(0, min(position, len(records)-1)))
            self._refresh_list()
        except Exception:
            self._report(STRINGS.ACCOUNT_OPERATION_FAILED, True)

    def _show_validation_error(self, message):
        self.validation_error_label.setText(message)
        self.validation_error_label.show()

    def _clear_validation_error(self):
        self.validation_error_label.clear()
        self.validation_error_label.hide()

    def refresh(self):
        self._refresh_list()
