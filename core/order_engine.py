from dataclasses import dataclass

from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.order import Order
from models.order_validator import (
    OrderValidationError,
    OrderValidator,
)


@dataclass
class OrderExecutionResult:
    success: bool
    sent: bool
    mode: str

    order: Order

    broker_name: str | None = None
    message: str | None = None

    response: dict | None = None


class OrderEngine:

    def __init__(self):
        self.validator = OrderValidator()

    def prepare(
        self,
        broker,
        order: Order,
        instrument: BrokerInstrument,
        account: Account,
    ) -> OrderExecutionResult:
        """
        آماده‌سازی سفارش بدون ارسال.
        """

        if broker is None:
            raise ValueError(
                "کارگزاری مشخص نشده است."
            )

        if not isinstance(order, Order):
            raise TypeError(
                "order باید از نوع Order باشد."
            )

        if not isinstance(
            instrument,
            BrokerInstrument,
        ):
            raise TypeError(
                "instrument باید از نوع BrokerInstrument باشد."
            )

        if not isinstance(account, Account):
            raise TypeError(
                "account باید از نوع Account باشد."
            )

        # ---------------------------------------------
        # Trading State
        # ---------------------------------------------

        state = broker.get_trading_state(
            instrument.nsc_id
        )

        if not state.is_order_entry_allowed:
            return OrderExecutionResult(
                success=False,
                sent=False,
                mode="BLOCKED",
                order=order,
                broker_name=broker.name,
                message=(
                    "ثبت سفارش در وضعیت فعلی "
                    "نماد مجاز نیست."
                ),
            )

        # ---------------------------------------------
        # Order Validation
        # ---------------------------------------------

        try:
            self.validator.validate(
                order,
                instrument,
                account,
            )

        except OrderValidationError as exc:
            return OrderExecutionResult(
                success=False,
                sent=False,
                mode="INVALID",
                order=order,
                broker_name=broker.name,
                message=str(exc),
            )

        # ---------------------------------------------
        # Ready
        # ---------------------------------------------

        return OrderExecutionResult(
            success=True,
            sent=False,
            mode="READY",
            order=order,
            broker_name=broker.name,
            message="سفارش برای ارسال آماده است.",
        )

    def execute(
        self,
        broker,
        order: Order,
        instrument: BrokerInstrument,
        account: Account,
        live: bool = False,
    ) -> OrderExecutionResult:
        """
        آماده‌سازی و اجرای سفارش.

        live=False:
            فقط Dry Run.

        live=True:
            درخواست ارسال را به Broker می‌دهد.
            خود Broker نیز باید قفل ایمنی خودش را بررسی کند.
        """

        prepared = self.prepare(
            broker=broker,
            order=order,
            instrument=instrument,
            account=account,
        )

        if not prepared.success:
            return prepared

        try:
            broker_result = broker.place_order(
                order,
                live=live,
            )

        except Exception as exc:
            return OrderExecutionResult(
                success=False,
                sent=False,
                mode="ERROR",
                order=order,
                broker_name=broker.name,
                message=str(exc),
            )

        # ---------------------------------------------
        # Live
        # ---------------------------------------------

        if live:
            return OrderExecutionResult(
                success=True,
                sent=True,
                mode="LIVE",
                order=order,
                broker_name=broker.name,
                message=(
                    "درخواست سفارش به کارگزاری "
                    "ارسال شد."
                ),
                response=broker_result,
            )

        # ---------------------------------------------
        # Dry Run
        # ---------------------------------------------

        return OrderExecutionResult(
            success=True,
            sent=False,
            mode="DRY_RUN",
            order=order,
            broker_name=broker.name,
            message="Dry Run با موفقیت انجام شد.",
            response=broker_result,
        )