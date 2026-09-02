from models.order import BUY, Order
from brokers.agaah import AgaahBroker


def main():
    broker = AgaahBroker()

    order = Order(
        nsc_id="IRO1IKCO0001",
        side=BUY,
        price=716,
        quantity=100,
        bank_account_id=0,
    )

    result = broker.place_order(
        order,
        live=False,
    )

    print("=" * 50)
    print("BROKER DRY RUN")
    print("=" * 50)

    print("Mode:", result["mode"])
    print("Sent:", result["sent"])

    print()
    print("Payload:")
    print(result["payload"])

    print()
    print("=" * 50)
    print("NO HTTP ORDER REQUEST WAS SENT")
    print("=" * 50)


if __name__ == "__main__":
    main()