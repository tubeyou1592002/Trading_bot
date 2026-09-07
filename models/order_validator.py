from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.order import BUY, SELL, Order


class OrderValidationError(ValueError):
    """خطای اعتبارسنجی سفارش."""


class OrderValidator:

    def validate(
        self,
        order: Order,
        instrument: BrokerInstrument,
        account: Account,
    ) -> None:

        # =================================================
        # Basic
        # =================================================

        if not order.nsc_id:
            raise OrderValidationError(
                "nscId سفارش مشخص نشده است."
            )

        if not instrument.nsc_id:
            raise OrderValidationError(
                "nscId نماد مشخص نشده است."
            )

        if order.nsc_id != instrument.nsc_id:
            raise OrderValidationError(
                "nscId سفارش با نماد انتخاب‌شده یکسان نیست."
            )

        if order.side not in (BUY, SELL):
            raise OrderValidationError(
                "سمت سفارش باید 1 (خرید) یا 2 (فروش) باشد."
            )

        # =================================================
        # Quantity
        # =================================================

        if order.quantity <= 0:
            raise OrderValidationError(
                "تعداد سفارش باید بیشتر از صفر باشد."
            )

        minimum_quantity = instrument.minimum_order_quantity

        if minimum_quantity is None:
            raise OrderValidationError(
                "حداقل حجم سفارش مشخص نیست."
            )

        if order.quantity < minimum_quantity:
            raise OrderValidationError(
                f"حداقل حجم سفارش {minimum_quantity} است."
            )

        lot_size = instrument.lot_size

        if lot_size is None:
            raise OrderValidationError(
                "lot size سفارش مشخص نیست."
            )

        if lot_size <= 0:
            raise OrderValidationError(
                "lot size سفارش معتبر نیست."
            )

        if order.quantity % lot_size != 0:
            raise OrderValidationError(
                f"تعداد سفارش باید مضرب {lot_size} باشد."
            )

        # =================================================
        # Maximum Quantity
        # =================================================

        if order.side == BUY:
            maximum_quantity = (
                instrument.maximum_order_quantity_for_buy
            )
        else:
            maximum_quantity = (
                instrument.maximum_order_quantity_for_sell
            )

        if maximum_quantity is None:
            raise OrderValidationError(
                "حداکثر حجم سفارش مشخص نیست."
            )

        if order.quantity > maximum_quantity:
            raise OrderValidationError(
                f"حداکثر حجم سفارش {maximum_quantity} است."
            )

        # =================================================
        # Price
        # =================================================

        if order.price <= 0:
            raise OrderValidationError(
                "قیمت سفارش باید بیشتر از صفر باشد."
            )

        fixed_price_tick = instrument.fixed_price_tick

        if fixed_price_tick is None:
            raise OrderValidationError(
                "Tick قیمت نماد مشخص نیست."
            )

        if fixed_price_tick <= 0:
            raise OrderValidationError(
                "Tick قیمت نماد معتبر نیست."
            )

        tick = int(fixed_price_tick)

        if order.price % tick != 0:
            raise OrderValidationError(
                "قیمت سفارش با Tick قیمت نماد "
                "مطابقت ندارد."
            )

        # =================================================
        # Price Limits
        # =================================================

        lower_limit = instrument.lower_price_threshold

        if lower_limit is None:
            raise OrderValidationError(
                "حد پایین قیمت مشخص نیست."
            )

        upper_limit = instrument.upper_price_threshold

        if upper_limit is None:
            raise OrderValidationError(
                "حد بالای قیمت مشخص نیست."
            )

        if order.price < lower_limit:
            raise OrderValidationError(
                f"قیمت کمتر از حد پایین مجاز است: "
                f"{lower_limit}"
            )

        if order.price > upper_limit:
            raise OrderValidationError(
                f"قیمت بیشتر از حد بالای مجاز است: "
                f"{upper_limit}"
            )

        # =================================================
        # Buying Power
        # =================================================

        if order.side == BUY:

            if account.tradable_balance_t1 is None:
                raise OrderValidationError(
                    "موجودی قابل معامله T1 مشخص نیست."
                )

            required_cash = (
                order.price * order.quantity
            )

            if required_cash > account.tradable_balance_t1:
                raise OrderValidationError(
                    "موجودی قابل معامله برای این "
                    "سفارش کافی نیست."
                )

        # =================================================
        # Selling
        # =================================================

        if order.side == SELL:
            # در حال حاضر endpoint موجودی حساب،
            # موجودی سهام قابل فروش را در اختیار ما قرار نمی‌دهد.
            #
            # کنترل دارایی فروش را بعداً اضافه می‌کنیم.
            pass