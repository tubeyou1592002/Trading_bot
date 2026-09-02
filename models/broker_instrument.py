from dataclasses import dataclass


@dataclass
class BrokerInstrument:
    name: str | None = None
    company_name: str | None = None

    nsc_id: str | None = None
    tse_id: str | None = None

    market_title: str | None = None

    state_code: str | None = None
    group_state_code: str | None = None

    last_trade_price: int | float | None = None
    final_price: int | float | None = None
    previous_day_price: int | float | None = None

    upper_price_threshold: int | float | None = None
    lower_price_threshold: int | float | None = None

    minimum_order_quantity: int | None = None
    lot_size: int | float | None = None
    fixed_price_tick: int | float | None = None

    maximum_order_quantity_for_buy: int | None = None
    maximum_order_quantity_for_sell: int | None = None

    bid_ask_list: list | None = None

    is_fund: bool = False
