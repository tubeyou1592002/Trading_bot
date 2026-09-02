from dataclasses import dataclass


@dataclass
class Instrument:
    symbol: str
    name: str
    ins_code: str
    instrument_id: str | None = None
    isin: str | None = None
    market: str | None = None
    flow: int | None = None