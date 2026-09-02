from getpass import getpass

from brokers.agaah import AgaahBroker
from market.symbol_resolver import SymbolResolver


def main():
    # ---------------------------------------------
    # Symbol Resolver
    # ---------------------------------------------

    resolver = SymbolResolver()

    symbol = input(
        "نماد را وارد کنید (مثلاً شستا): "
    ).strip()

    print()
    print("در حال جستجوی TSETMC...")

    try:
        results = resolver.search(symbol)

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

    try:
        selected_index = int(
            input(
                "\nشماره نماد موردنظر را انتخاب کنید: "
            )
        )

        result = results[selected_index]

    except (ValueError, IndexError):
        print("انتخاب نامعتبر است.")
        return

    # ---------------------------------------------
    # Resolve full TSETMC instrument
    # ---------------------------------------------

    try:
        instrument = resolver.resolve(result)

    except Exception as exc:
        print(
            "Instrument Resolve Error:",
            type(exc).__name__,
            ":",
            exc,
        )
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
    print("Market:", instrument.market)

    if not instrument.instrument_id:
        print("این نماد instrument_id ندارد.")
        return

    # ---------------------------------------------
    # Agaah Login
    # ---------------------------------------------

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

    print()
    print("LOGIN SUCCESS")

    # ---------------------------------------------
    # Agaah Instrument
    # ---------------------------------------------

    print()
    print(
        "در حال دریافت اطلاعات نماد از آگاه..."
    )

    try:
        broker_instrument = (
            broker.get_instrument_by_instrument_id(
                instrument.instrument_id
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
    print("TSETMC -> AGAAH SUCCESS")
    print("=" * 50)

    print("TSETMC Symbol:", instrument.symbol)
    print("TSETMC ISIN:", instrument.isin)

    print(
        "Agaah Name:",
        broker_instrument.name
    )

    print(
        "Agaah NSC ID:",
        broker_instrument.nsc_id
    )

    print(
        "Agaah TSE ID:",
        broker_instrument.tse_id
    )

    print(
        "Agaah State:",
        broker_instrument.state_code
    )

    print(
        "Agaah Group State:",
        broker_instrument.group_state_code
    )

    print(
        "Agaah Last Price:",
        broker_instrument.last_trade_price
    )

    print(
        "Agaah Final Price:",
        broker_instrument.final_price
    )


if __name__ == "__main__":
    main()