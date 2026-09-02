from getpass import getpass

from brokers.agaah import AgaahBroker
from core.order_engine import OrderEngine
from market.symbol_resolver import SymbolResolver
from models.order import BUY, Order


def main():

    # =================================================
    # TSETMC
    # =================================================

    resolver = SymbolResolver()

    symbol = input(
        "نماد را وارد کنید: "
    ).strip()

    print()
    print("در حال جستجوی نماد...")

    results = resolver.search(symbol)

    if not results:
        print("نمادی پیدا نشد.")
        return

    for index, result in enumerate(results[:10]):
        print(
            f"{index}: "
            f"{result.get('symbol')} - "
            f"{result.get('name')}"
        )

    try:
        selected = int(
            input("شماره نماد: ")
        )

        selected_result = results[selected]

    except (ValueError, IndexError):
        print("انتخاب نامعتبر است.")
        return

    instrument = resolver.resolve(
        selected_result
    )

    if not instrument.instrument_id:
        print("instrument_id موجود نیست.")
        return

    # =================================================
    # Broker
    # =================================================

    broker = AgaahBroker()

    captcha_data = broker.get_captcha()

    broker.save_captcha_image(
        captcha_data,
        "captcha.png",
    )

    print()
    print("captcha.png را باز کن.")

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
            "LOGIN FAILED:",
            type(exc).__name__,
            ":",
            exc,
        )
        return

    print("LOGIN SUCCESS")

    # =================================================
    # Broker Instrument
    # =================================================

    broker_instrument = (
        broker.get_instrument_by_instrument_id(
            instrument.instrument_id
        )
    )

    # =================================================
    # Account
    # =================================================

    account = broker.get_account()

    # =================================================
    # Order
    # =================================================

    price = int(
        input(
            f"قیمت "
            f"(مثلاً {broker_instrument.last_trade_price}): "
        )
    )

    quantity = int(
        input("تعداد: ")
    )

    order = Order(
        nsc_id=broker_instrument.nsc_id,
        side=BUY,
        price=price,
        quantity=quantity,
        bank_account_id=0,
    )

    # =================================================
    # Engine
    # =================================================

    engine = OrderEngine()

    result = engine.execute(
        broker=broker,
        order=order,
        instrument=broker_instrument,
        account=account,
        live=False,
    )

    print()
    print("=" * 50)
    print("ORDER ENGINE RESULT")
    print("=" * 50)

    print("Success:", result.success)
    print("Sent:", result.sent)
    print("Mode:", result.mode)
    print("Broker:", result.broker_name)
    print("Message:", result.message)

    if result.response:
        print()
        print("Broker response:")
        print(result.response)

    print()
    print("=" * 50)
    print("NO LIVE ORDER WAS SENT")
    print("=" * 50)


if __name__ == "__main__":
    main()