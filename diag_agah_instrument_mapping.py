"""
diag_agah_instrument_mapping.py — TEMPORARY one-off diagnostic.

Purpose:
    Investigate whether TSETMC `instrumentID` (e.g. 35366681030756042)
    and an ISIN-shaped value (e.g. IRO1PNBA0001) are interchangeable
    as values for the Agah `nscIds` query parameter on
    `GET /api/v1/instruments`.

This script:
    * Reuses the existing AgaahBroker session + login flow.
    * Sends only GET requests to /instruments.
    * Does NOT place, modify or cancel any order.
    * Does NOT print any credential, token, cookie, Authorization,
      UserIdentifier, password, or full request/response headers.

This file is for one-off investigation only and must not be
imported by main.py, core/, or any other application module.
"""


def _safe_field(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    return value


def _print_record(label, payload):
    print("=" * 50)
    print(label)
    print("=" * 50)

    print("HTTP status:", payload.get("status"))
    print("isSuccess:", payload.get("isSuccess"))
    print("list length:", payload.get("list_length"))

    items = payload.get("items") or []
    if not items:
        print("(no items)")
        return

    for index, item in enumerate(items):
        print(f"--- item {index} ---")
        print("name:", _safe_field(item.get("name")))
        print(
            "companyName:",
            _safe_field(item.get("companyName")),
        )
        print("nscId:", _safe_field(item.get("nscId")))
        print("tseId:", _safe_field(item.get("tseId")))


def _do_get(broker, nsc_id):
    """
    Issue a single GET /instruments?nscIds=<nsc_id> using the
    existing broker session and the same auth-header mechanism
    already used by AgaahBroker.get_instrument.
    """

    url = f"{broker._url('instruments')}"

    response = broker.session.get(
        url,
        params={"nscIds": nsc_id},
        headers=broker._auth_headers(),
        timeout=10,
    )

    http_status = response.status_code
    is_success = None
    items = []
    list_length = 0

    try:
        data = response.json()
    except ValueError:
        data = None

    if isinstance(data, dict):
        is_success = data.get("isSuccess")

        inner = data.get("data")

        if isinstance(inner, list):
            list_length = len(inner)
            items = inner
        else:
            list_length = 0
            items = []

    return {
        "status": http_status,
        "isSuccess": is_success,
        "list_length": list_length,
        "items": items,
    }


def main():
    from getpass import getpass

    from brokers.agaah import AgaahBroker

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

    try:
        broker.login(
            username=username,
            password=password,
            captcha=captcha,
            captcha_id=captcha_data["captchaId"],
        )
    except Exception as exc:
        print("LOGIN FAILED:", type(exc).__name__, ":", exc)
        return

    print("LOGIN SUCCESS")
    print()

    for label, probe in (
        ("PROBE 1 — ISIN-shaped value", "IRO1PNBA0001"),
        (
            "PROBE 2 — TSETMC instrumentID",
            "35366681030756042",
        ),
    ):
        try:
            payload = _do_get(broker, probe)
        except Exception as exc:
            print("=" * 50)
            print(label)
            print("=" * 50)
            print("HTTP status: ERROR")
            print("isSuccess: ERROR")
            print("list length: 0")
            print(
                "error:",
                type(exc).__name__,
                ":",
                exc,
            )
            print()
            continue

        _print_record(label, payload)
        print()


if __name__ == "__main__":
    main()
