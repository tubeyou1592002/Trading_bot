from dataclasses import dataclass


@dataclass
class Account:
    last_balance: int | float | None = None
    adjusted_balance_t2: int | float | None = None

    tradable_balance_t1: int | float | None = None
    tradable_balance_t2: int | float | None = None

    payable_balance_with_agah_credit_t0: int | float | None = None
    payable_balance_with_agah_credit_t1: int | float | None = None
    payable_balance_with_agah_credit_t2: int | float | None = None

    payable_balance_without_agah_credit_t0: int | float | None = None

    block: int | float | None = None
    credit: int | float | None = None

    settlement_date_t0: str | None = None
    settlement_date_t1: str | None = None
    settlement_date_t2: str | None = None