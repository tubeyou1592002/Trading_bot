from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.order import BUY, Order
from models.order_validator import (
    OrderValidationError,
    OrderValidator,
)


def main():
    # ---------------------------------------------
    # اطلاعات واقعی خودرو که از API گرفتیم
    # ---------------------------------------------

    instrument = BrokerInstrument(
        name="خودرو",
        company_name="ایران خودرو",
        nsc_id="IRO1IKCO0001",
        tse_id="65883838195688438",
        market_title="بورس",
        state_code="A",
        group_state_code="B",
        last_trade_price=716,
        final_price=715,
        previous_day_price=696,
        upper_price_threshold=716,
        lower_price_threshold=676,
        minimum_order_quantity=1,
        lot_size=1,
        fixed_price_tick=1.0,
        maximum_order_quantity_for_buy=3000000,
        maximum_order_quantity_for_sell=3000000,
        bid_ask_list=[],
        is_fund=False,
    )

    # ---------------------------------------------
    # موجودی نمونه
    #
    # این مقدار فقط برای تست است.
    # ---------------------------------------------

    account = Account(
        tradable_balance_t1=100_000_000
    )

    # ---------------------------------------------
    # سفارش
    # ---------------------------------------------

    order = Order(
        nsc_id=instrument.nsc_id,
        side=BUY,
        price=716,
        quantity=100,
        bank_account_id=0,
    )

    # ---------------------------------------------
    # Validate
    # ---------------------------------------------

    validator = OrderValidator()

    try:
        validator.validate(
            order,
            instrument,
            account,
        )

    except OrderValidationError as exc:
        print("ORDER INVALID")
        print("Reason:", exc)
        return

    # ---------------------------------------------
    # Payload
    # ---------------------------------------------

    payload = order.to_payload()

    print("=" * 50)
    print("ORDER VALID")
    print("=" * 50)

    print("Symbol:", instrument.name)
    print("NSC ID:", order.nsc_id)
    print("Side:", order.side)
    print("Price:", order.price)
    print("Quantity:", order.quantity)

    print()
    print("Payload:")
    print(payload)


if __name__ == "__main__":
    main()