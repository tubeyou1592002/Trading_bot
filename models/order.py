from dataclasses import dataclass
from datetime import datetime, timezone


BUY = 1
SELL = 2

DEFAULT_CATEGORY_ID = (
    "3859b5fc-8ae2-46a6-84b8-d8914c3b2292"
)


@dataclass
class Order:
    nsc_id: str
    side: int
    price: int
    quantity: int

    validity_type: int = 1
    category_id: str = DEFAULT_CATEGORY_ID
    bank_account_id: int = 0

    creation_date: datetime | None = None

    disclosed_quantity: int | None = None
    minimum_quantity: int | None = None
    validity_date: datetime | None = None

    def __post_init__(self):
        if self.creation_date is None:
            self.creation_date = datetime.now(
                timezone.utc
            )

    def to_payload(self) -> dict:
        creation_date = None

        if self.creation_date:
            utc_date = self.creation_date.astimezone(
                timezone.utc
            )

            creation_date = (
                utc_date.isoformat()
                .replace("+00:00", "Z")
            )

        return {
            "nscId": self.nsc_id,
            "orderSide": self.side,
            "price": self.price,
            "quantity": self.quantity,
            "validityType": self.validity_type,
            "categoryId": self.category_id,
            "bankAccountId": self.bank_account_id,
            "creationDate": creation_date,
            "disclosedQuantity": self.disclosed_quantity,
            "minimumQuantity": self.minimum_quantity,
            "validityDate": self.validity_date,
        }