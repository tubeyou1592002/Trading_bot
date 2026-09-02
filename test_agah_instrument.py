from getpass import getpass

from brokers.agaah import AgaahBroker


def main():
    broker = AgaahBroker()

    print("در حال دریافت کپچا...")
    captcha_data = broker.get_captcha()

    broker.save_captcha_image(
        captcha_data,
        "captcha.png",
    )

    print("captcha.png را باز کن.")
    print()

    username = input("نام کاربری آگاه: ").strip()
    password = getpass("رمز عبور آگاه: ")
    captcha = input("کد کپچا: ").strip()

    # ---------------------------------------------
    # Login
    # ---------------------------------------------

    try:
        broker.login(
            username=username,
            password=password,
            captcha=captcha,
            captcha_id=captcha_data["captchaId"],
        )

        print()
        print("LOGIN SUCCESS")

    except Exception as exc:
        print()
        print("LOGIN FAILED")
        print(type(exc).__name__, ":", exc)
        return

    # ---------------------------------------------
    # Instrument
    # ---------------------------------------------

    nsc_id = "IRO1TAMN0001"

    try:
        instrument = broker.get_instrument(nsc_id)

        print()
        print("=" * 50)
        print("INSTRUMENT SUCCESS")
        print("=" * 50)

        print("Name:", instrument.name)
        print("Company:", instrument.company_name)
        print("NSC ID:", instrument.nsc_id)
        print("TSE ID:", instrument.tse_id)
        print("Market:", instrument.market_title)

        print("State:", instrument.state_code)
        print("Group State:", instrument.group_state_code)

        print("Last Price:", instrument.last_trade_price)
        print("Final Price:", instrument.final_price)
        print("Previous Price:", instrument.previous_day_price)

        print("Upper Limit:", instrument.upper_price_threshold)
        print("Lower Limit:", instrument.lower_price_threshold)

        print(
            "Minimum Order Quantity:",
            instrument.minimum_order_quantity
        )

        print("Lot Size:", instrument.lot_size)
        print("Price Tick:", instrument.fixed_price_tick)

        print(
            "Max Buy:",
            instrument.maximum_order_quantity_for_buy
        )

        print(
            "Max Sell:",
            instrument.maximum_order_quantity_for_sell
        )

        print("Is Fund:", instrument.is_fund)

        print("Bid/Ask levels:", len(
            instrument.bid_ask_list or []
        ))

    except Exception as exc:
        print()
        print("=" * 50)
        print("INSTRUMENT FAILED")
        print("=" * 50)
        print(type(exc).__name__, ":", exc)


if __name__ == "__main__":
    main()