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

    print("کپچا ذخیره شد: captcha.png")
    print(f"Captcha ID: {captcha_data['captchaId']}")
    print()
    print("captcha.png را باز کن و متن کپچا را وارد کن.")
    print()

    username = input("نام کاربری آگاه: ").strip()
    password = getpass("رمز عبور آگاه: ")
    captcha = input("کد کپچا: ").strip()

    # ---------------------------------------------
    # Login
    # ---------------------------------------------

    try:
        result = broker.login(
            username=username,
            password=password,
            captcha=captcha,
            captcha_id=captcha_data["captchaId"],
        )

        print()
        print("=" * 50)
        print("LOGIN SUCCESS")
        print("=" * 50)

        print("Username:", result.get("userName"))

        print(
            "UserIdentifier دریافت شد:",
            bool(result.get("userIdentifier"))
        )

        print(
            "RefreshToken دریافت شد:",
            result.get("hasRefreshToken")
        )

    except Exception as exc:
        print()
        print("=" * 50)
        print("LOGIN FAILED")
        print("=" * 50)
        print(type(exc).__name__, ":", exc)
        return

    # ---------------------------------------------
    # Account / Balance
    # ---------------------------------------------

    print()
    print("در حال دریافت موجودی حساب...")

    try:
        account = broker.get_account()

        print()
        print("=" * 50)
        print("ACCOUNT SUCCESS")
        print("=" * 50)

        print("Account type:", type(account).__name__)
        print("Last balance:", account.last_balance)
        print(
            "Tradable T1:",
            account.tradable_balance_t1
        )
        print(
            "Tradable T2:",
            account.tradable_balance_t2
        )
        print("Block:", account.block)
        print("Credit:", account.credit)

        print(
            "Settlement T0:",
            account.settlement_date_t0
        )

        print(
            "Settlement T1:",
            account.settlement_date_t1
        )

        print(
            "Settlement T2:",
            account.settlement_date_t2
        )

    except Exception as exc:
        print()
        print("=" * 50)
        print("ACCOUNT FAILED")
        print("=" * 50)
        print(type(exc).__name__, ":", exc)


if __name__ == "__main__":
    main()