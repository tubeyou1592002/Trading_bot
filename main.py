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
)

from market.symbol_resolver import SymbolResolver

from brokers.manager import BrokerManager

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

            self.status_label.setText(
                f"کارگزاری انتخاب شده: {broker_name}"
            )

            print(
                f"Broker selected: {broker_name}"
            )

        except Exception as e:

            self.current_broker = None

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