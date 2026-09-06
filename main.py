import sys

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QLabel,
    QComboBox,
    QPushButton,
)

from market.symbol_resolver import SymbolResolver

from brokers.manager import BrokerManager
from brokers.base import InstrumentLookupError

from core.order_engine import OrderEngine

from models.account import Account
from models.order import BUY, Order, SELL

from input.keyboard_layout import (
    get_foreground_keyboard_layout,
    activate_persian_keyboard,
    activate_keyboard_layout,
)


class SymbolSearchWindow(QWidget):

    def __init__(self, previous_keyboard_layout):

        super().__init__()

        self.previous_keyboard_layout = (
            previous_keyboard_layout
        )

        # ---------------------------------------------
        # Broker Manager
        # ---------------------------------------------

        self.broker_manager = BrokerManager()

        self.current_broker = None
        self.current_provider = None
        self.order_engine = OrderEngine()
        self.selected_instrument = None

        # ---------------------------------------------
        # Symbol Resolver
        # ---------------------------------------------

        self.resolver = SymbolResolver()

        # ---------------------------------------------
        # Window
        # ---------------------------------------------

        self.setWindowTitle(
            "Trading Bot"
        )

        self.resize(
            650,
            450
        )

        # ---------------------------------------------
        # Broker selector
        # ---------------------------------------------

        broker_label = QLabel(
            "کارگزاری:"
        )

        self.broker_combo = QComboBox()

        self.broker_combo.addItems(
            self.broker_manager.names()
        )

        self.broker_combo.currentTextChanged.connect(
            self.on_broker_changed
        )

        # ---------------------------------------------
        # Search
        # ---------------------------------------------

        self.search_box = QLineEdit()

        self.search_box.setPlaceholderText(
            "نماد را وارد کنید..."
        )

        self.results_list = QListWidget()

        self.status_label = QLabel(
            "آماده"
        )

        # ---------------------------------------------
        # Order
        # ---------------------------------------------

        self.side_combo = QComboBox()
        self.side_combo.addItems(
            ["خرید", "فروش"]
        )
        self.side_combo.setItemData(
            0, BUY
        )
        self.side_combo.setItemData(
            1, SELL
        )

        self.price_edit = QLineEdit()
        self.price_edit.setPlaceholderText(
            "قیمت"
        )

        self.quantity_edit = QLineEdit()
        self.quantity_edit.setPlaceholderText(
            "تعداد"
        )

        self.send_button = QPushButton(
            "ارسال (Dry Run)"
        )

        self.send_button.clicked.connect(
            self.send_order
        )

        # ---------------------------------------------
        # Layout
        # ---------------------------------------------

        main_layout = QVBoxLayout()

        broker_layout = QHBoxLayout()

        broker_layout.addWidget(
            broker_label
        )

        broker_layout.addWidget(
            self.broker_combo
        )

        main_layout.addLayout(
            broker_layout
        )

        main_layout.addWidget(
            QLabel("نماد:")
        )

        main_layout.addWidget(
            self.search_box
        )

        main_layout.addWidget(
            self.results_list
        )

        order_layout = QHBoxLayout()

        order_layout.addWidget(
            QLabel("سفارش:")
        )

        order_layout.addWidget(
            self.side_combo
        )

        order_layout.addWidget(
            self.price_edit
        )

        order_layout.addWidget(
            self.quantity_edit
        )

        order_layout.addWidget(
            self.send_button
        )

        main_layout.addLayout(
            order_layout
        )

        main_layout.addWidget(
            self.status_label
        )

        self.setLayout(
            main_layout
        )

        # ---------------------------------------------
        # Search timer
        # ---------------------------------------------

        self.timer = QTimer()

        self.timer.setSingleShot(
            True
        )

        self.timer.setInterval(
            300
        )

        # ---------------------------------------------
        # Signals
        # ---------------------------------------------

        self.search_box.textChanged.connect(
            self.on_text_changed
        )

        self.timer.timeout.connect(
            self.perform_search
        )

        self.results_list.itemClicked.connect(
            self.select_symbol
        )

        # ---------------------------------------------
        # Default broker
        # ---------------------------------------------

        self.on_broker_changed(
            self.broker_combo.currentText()
        )

    # =================================================
    # Broker
    # =================================================

    def on_broker_changed(self, broker_name):

        try:

            self.current_broker = (
                self.broker_manager.get(
                    broker_name
                )
            )

            self.current_provider = (
                self.broker_manager.get_instrument_provider(
                    broker_name
                )
            )

            self.status_label.setText(
                f"کارگزاری انتخاب شده: {broker_name}"
            )

            print(
                f"Broker selected: {broker_name}"
            )

        except Exception as e:

            self.current_broker = None
            self.current_provider = None

            self.status_label.setText(
                f"خطا: {e}"
            )

    # =================================================
    # Search
    # =================================================

    def on_text_changed(self, text):

        self.timer.stop()

        self.results_list.clear()

        if not text.strip():

            self.status_label.setText(
                "آماده"
            )

            return

        self.status_label.setText(
            "در حال جستجو..."
        )

        self.timer.start()

    # =================================================
    # TSETMC Search
    # =================================================

    def perform_search(self):

        text = self.search_box.text().strip()

        if not text:
            return

        try:

            results = self.resolver.search(
                text
            )

            self.results_list.clear()

            for result in results:

                symbol = result.get(
                    "symbol",
                    ""
                )

                name = result.get(
                    "name",
                    ""
                )

                item = QListWidgetItem(
                    f"{symbol}    —    {name}"
                )

                item.setData(
                    Qt.UserRole,
                    result
                )

                self.results_list.addItem(
                    item
                )

            self.status_label.setText(
                f"{len(results)} نتیجه"
            )

        except Exception as e:

            self.status_label.setText(
                f"خطا: {e}"
            )

            print(
                "Search Error:",
                e
            )

    # =================================================
    # Select Instrument
    # =================================================

    def select_symbol(self, item):

        data = item.data(
            Qt.UserRole
        )

        try:

            instrument = (
                self.resolver.resolve(
                    data
                )
            )

            self.selected_instrument = instrument

            print()
            print("=" * 50)
            print("Selected Instrument")
            print("=" * 50)

            print(
                "Symbol:",
                instrument.symbol
            )

            print(
                "Name:",
                instrument.name
            )

            print(
                "TSETMC Code:",
                instrument.ins_code
            )

            print(
                "Instrument ID:",
                instrument.instrument_id
            )

            print(
                "ISIN:",
                instrument.isin
            )

            print(
                "Market:",
                instrument.market
            )

            print("=" * 50)

            self.status_label.setText(
                f"انتخاب شد: {instrument.symbol}"
            )

        except Exception as e:

            self.status_label.setText(
                f"خطا: {e}"
            )

            print(
                "Selection Error:",
                e
            )

    # =================================================
    # Order
    # =================================================

    def send_order(self):
        """
        ارسال سفارش (dry-run) از طریق OrderEngine.

        این متد فقط در صورتی اجرا می‌شود که:
        - کارگزاری و provider انتخاب شده باشند
        - نمادی انتخاب شده باشد (selected_instrument)

        سفارش همیشه با live=False (dry-run) ارسال می‌شود.
        هیچ سفارش واقعی ارسال نمی‌شود.
        """

        if self.current_broker is None or (
            self.current_provider is None
        ):
            self.status_label.setText(
                "ابتدا کارگزاری انتخاب کنید."
            )
            return

        if self.selected_instrument is None:
            self.status_label.setText(
                "ابتدا نماد را از لیست انتخاب کنید."
            )
            return

        ins_code = self.selected_instrument.ins_code

        # ---------------------------------------------
        # Step 1: Resolve nsc_id via provider
        # ---------------------------------------------

        try:
            nsc_id = (
                self.current_provider.get_nsc_id(
                    ins_code
                )
            )

        except InstrumentLookupError as exc:
            self.status_label.setText(
                f"خطا در حل نماد: {exc}"
            )
            return

        if not nsc_id:
            self.status_label.setText(
                "نمی‌توان nsc_id را برای نماد "
                "انتخابی حل کرد."
            )
            return

        # ---------------------------------------------
        # Step 2: Build order from UI inputs
        # ---------------------------------------------

        try:
            price = int(
                self.price_edit.text()
            )
            quantity = int(
                self.quantity_edit.text()
            )

        except ValueError:

            self.status_label.setText(
                "قیمت و تعداد باید عدد باشند."
            )
            return

        order = Order(
            nsc_id=nsc_id,
            side=self.side_combo.currentData(),
            price=price,
            quantity=quantity,
            bank_account_id=0,
        )

        # ---------------------------------------------
        # Step 3: Obtain account from broker
        # (requires login — no placeholder)
        # ---------------------------------------------

        try:
            account = (
                self.current_broker.get_account()
            )

        except Exception as exc:

            self.status_label.setText(
                f"خطا در دریافت حساب: {exc}"
            )
            return

        # ---------------------------------------------
        # Step 4: Execute via OrderEngine (dry-run)
        # ---------------------------------------------

        result = self.order_engine.execute_by_ins_code(
            broker=self.current_broker,
            provider=self.current_provider,
            ins_code=ins_code,
            order=order,
            account=account,
            live=False,
        )

        self.status_label.setText(
            f"{result.mode}: {result.message}"
        )

        print(
            f"Order result -- "
            f"mode={result.mode}, "
            f"sent={result.sent}"
        )

    # =================================================
    # Close
    # =================================================

    def closeEvent(self, event):

        try:

            activate_keyboard_layout(
                self.previous_keyboard_layout
            )

            print(
                "Keyboard Layout restored."
            )

        except Exception as e:

            print(
                "Could not restore Keyboard Layout:",
                e
            )

        event.accept()


# =====================================================
# Main
# =====================================================

def main():

    # ---------------------------------------------
    # Save current keyboard layout
    # ---------------------------------------------

    previous_keyboard_layout = (
        get_foreground_keyboard_layout()
    )

    print(
        "Previous Keyboard Layout:",
        hex(previous_keyboard_layout)
    )

    # ---------------------------------------------
    # Persian keyboard
    # ---------------------------------------------

    try:

        activate_persian_keyboard()

        print(
            "Persian Keyboard Layout activated."
        )

    except Exception as e:

        print(
            "Could not activate Persian Keyboard Layout:",
            e
        )

    # ---------------------------------------------
    # Qt
    # ---------------------------------------------

    app = QApplication(
        sys.argv
    )

    window = SymbolSearchWindow(
        previous_keyboard_layout
    )

    window.show()

    sys.exit(
        app.exec()
    )


if __name__ == "__main__":
    main()