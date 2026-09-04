from getpass import getpass

from brokers.agaah import (
    AgaahBroker,
    AgaahInstrumentProvider,
)
from market.symbol_resolver import SymbolResolver
from models.order import BUY, SELL, Order
from models.order_validator import (
    OrderValidationError,
    OrderValidator,
)


def get_int_input(prompt: str) -> int:
    while True:
        try:
            return int(input(prompt).strip())
        except ValueError:
            print("لطفاً فقط عدد وارد کنید.")


def main():
    # =================================================
    # 1. TSETMC
    # =================================================

    resolver = SymbolResolver()

    symbol_text = input(
        "نماد را وارد کنید (مثلاً خودرو): "
    ).strip()

    print()
    print("در حال جستجوی TSETMC...")

    try:
        results = resolver.search(symbol_text)
    except Exception as exc:
        print(
            "TSETMC Search Error:",
            type(exc).__name__,
            ":",
            exc,
        )
        return

    if not results:
        print("نمادی پیدا نشد.")
        return

    print()
    print("=" * 50)
    print("TSETMC RESULTS")
    print("=" * 50)

    for index, result in enumerate(results[:10]):
        print(
            f"{index}: "
            f"{result.get('symbol')} - "
            f"{result.get('name')} - "
            f"{result.get('ins_code')}"
        )

    selected_index = get_int_input(
        "\nشماره نماد موردنظر: "
    )

    if selected_index < 0 or selected_index >= min(
        len(results),
        10,
    ):
        print("انتخاب نامعتبر است.")
        return

    selected_result = results[selected_index]

    # =================================================
    # 2. Full TSETMC instrument
    # =================================================

    try:
        instrument = resolver.resolve(
            selected_result
        )
    except Exception as exc:
        print(
            "TSETMC Instrument Error:",
            type(exc).__name__,
            ":",
            exc,
        )
        return

    if not instrument.instrument_id:
        print("نماد instrument_id ندارد.")
        return

    print()
    print("=" * 50)
    print("TSETMC INSTRUMENT")
    print("=" * 50)

    print("Symbol:", instrument.symbol)
    print("Name:", instrument.name)
    print("ISIN:", instrument.isin)
    print("InsCode:", instrument.ins_code)
    print("Instrument ID:", instrument.instrument_id)

    # =================================================
    # 3. Agaah Login
    # =================================================

    broker = AgaahBroker()

    print()
    print("در حال دریافت کپچا...")

    try:
        captcha_data = broker.get_captcha()

        broker.save_captcha_image(
            captcha_data,
            "captcha.png",
        )

    except Exception as exc:
        print(
            "Captcha Error:",
            type(exc).__name__,
            ":",
            exc,
        )
        return

    print("captcha.png را باز کن.")
    print()

    username = input(
        "نام کاربری آگاه: "
    ).strip()

    password = getpass(
        "رمز عبور آگاه: "
    )

    captcha = input(
        "کد کپچا: "
    ).strip()

    try:
        broker.login(
            username=username,
            password=password,
            captcha=captcha,
            captcha_id=captcha_data["captchaId"],
        )
    except Exception as exc:
        print(
            "Login Error:",
            type(exc).__name__,
            ":",
            exc,
        )
        return

    print("LOGIN SUCCESS")

    # =================================================
    # 4. Agaah instrument information
    # =================================================
    # مسیر امن: ins_code (از TSETMC) -> Provider
    # -> نماد آگاه با تأیید tseId

    provider = AgaahInstrumentProvider(broker)

    try:
        _, broker_instrument = (
            provider.get_instrument(
                instrument.ins_code
            )
        )
    except Exception as exc:
        print(
            "Agaah Instrument Error:",
            type(exc).__name__,
            ":",
            exc,
        )
        return

    print()
    print("=" * 50)
    print("AGAAH INSTRUMENT")
    print("=" * 50)

    print("Name:", broker_instrument.name)
    print("NSC ID:", broker_instrument.nsc_id)
    print("State:", broker_instrument.state_code)
    print(
        "Group State:",
        broker_instrument.group_state_code
    )
    print(
        "Last Price:",
        broker_instrument.last_trade_price
    )
    print(
        "Final Price:",
        broker_instrument.final_price
    )
    print(
        "Lower Limit:",
        broker_instrument.lower_price_threshold
    )
    print(
        "Upper Limit:",
        broker_instrument.upper_price_threshold
    )
    print(
        "Min Quantity:",
        broker_instrument.minimum_order_quantity
    )
    print(
        "Max Buy:",
        broker_instrument.maximum_order_quantity_for_buy
    )
    print(
        "Max Sell:",
        broker_instrument.maximum_order_quantity_for_sell
    )

    # =================================================
    # 5. Account
    # =================================================

    try:
        account = broker.get_account()
    except Exception as exc:
        print(
            "Account Error:",
            type(exc).__name__,
            ":",
            exc,
        )
        return

    print()
    print("=" * 50)
    print("ACCOUNT")
    print("=" * 50)

    print(
        "Tradable T1:",
        account.tradable_balance_t1
    )

    print(
        "Tradable T2:",
        account.tradable_balance_t2
    )

    # =================================================
    # 6. Order input
    # =================================================

    print()
    print("=" * 50)
    print("ORDER INPUT")
    print("=" * 50)

    print("1 = BUY")
    print("2 = SELL")

    side = get_int_input(
        "سمت سفارش: "
    )

    if side not in (BUY, SELL):
        print("سمت سفارش نامعتبر است.")
        return

    price = get_int_input(
        "قیمت: "
    )

    quantity = get_int_input(
        "تعداد: "
    )

    # =================================================
    # 7. Build Order
    # =================================================

    order = Order(
        nsc_id=broker_instrument.nsc_id,
        side=side,
        price=price,
        quantity=quantity,
        category_id=None,
        bank_account_id=0,
    )

    # =================================================
    # 8. Validate
    # =================================================

    validator = OrderValidator()

    try:
        validator.validate(
            order,
            broker_instrument,
            account,
        )

    except OrderValidationError as exc:
        print()
        print("=" * 50)
        print("ORDER INVALID")
        print("=" * 50)
        print("Reason:", exc)
        return

    # =================================================
    # 9. Dry Run
    # =================================================

    payload = order.to_payload()

    print()
    print("=" * 50)
    print("DRY RUN SUCCESS")
    print("=" * 50)

    print("Symbol:", broker_instrument.name)
    print("NSC ID:", order.nsc_id)
    print(
        "Side:",
        "BUY" if order.side == BUY else "SELL"
    )
    print("Price:", order.price)
    print("Quantity:", order.quantity)

    print()
    print("Payload:")
    print(payload)

    print()
    print("=" * 50)
    print("NO ORDER WAS SENT")
    print("=" * 50)


if __name__ == "__main__":
    main()