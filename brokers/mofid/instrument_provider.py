"""Account-scoped, read-only Mofid symbol identity/detail provider."""

from brokers.base import InstrumentLookupError, InstrumentProvider
from models.broker_instrument import BrokerInstrument
from decimal import Decimal, InvalidOperation


def _value(record, *keys):
    for key in keys:
        value = record.get(key)
        if value is not None and value != "":
            return value
    return None


def _nonnegative_decimal(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError("Invalid Mofid decimal")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("Invalid Mofid decimal") from None
    if not number.is_finite() or number < 0:
        raise ValueError("Invalid Mofid decimal")
    return number


class MofidInstrumentProvider(InstrumentProvider):
    def __init__(self, tsetmc_client, adapter):
        self._tsetmc = tsetmc_client
        self._adapter = adapter
        self._cache = {}

    def _catalogue_symbol(self, isin):
        catalogue = self._adapter._read_symbol_data(
            "/symbols/api/symbols/all", {"hash": "null"}
        )
        symbols = catalogue["symbols"]
        matches = [item for item in symbols if type(item) is dict and item.get("symbolIsin") == isin]
        if len(matches) != 1:
            raise InstrumentLookupError("Mofid catalogue identity is not unique")
        return matches[0]

    def get_instrument(self, ins_code):
        if ins_code in self._cache:
            return self._cache[ins_code]
        stage = "tsetmc_lookup"
        try:
            instrument = self._tsetmc.get_info(ins_code)
            isin = getattr(instrument, "instrument_id", None)
            if not isinstance(isin, str) or not isin.strip():
                raise ValueError
            # The TSETMC endpoint is queried by ins_code; its returned
            # instrument_id is the cross-market identity (ISIN), not the
            # TSETMC identifier. Keep the two identifiers distinct.
            tse_id = getattr(instrument, "ins_code", None)
            if not isinstance(tse_id, str) or not tse_id.strip() or tse_id != ins_code:
                raise ValueError
            if isinstance(instrument, dict):
                instrument_id = instrument.get("instrument_id", instrument.get("instrumentID"))
                returned_ins_code = instrument.get("ins_code", instrument.get("insCode"))
                if instrument_id != isin or returned_ins_code != ins_code:
                    raise ValueError
            stage = "symbol_catalogue"
            catalogue = self._catalogue_symbol(isin)
            stage = "market_data"
            marketdata = self._adapter._read_symbol_data(
                "/symbols/api/marketdata/v2", [isin]
            )
            rows = [row for row in marketdata
                    if _value(row, "symbolIsin", "symbolISIN") == isin]
            if len(rows) != 1:
                raise InstrumentLookupError("Mofid market data is empty or ambiguous",
                                            stage=stage, reason_code="DETAILS_EMPTY")
            market = rows[0]
            stage = "symbol_info"
            info = self._adapter._read_symbol_data(
                "/symbols/api/MarketData/symbol-info-data", {"isin": isin}
            )
            if info.get("symbolISIN", info.get("symbolIsin", isin)) != isin:
                raise ValueError
            stage = "pricing_metadata"
            try:
                buy_commission = _nonnegative_decimal(_value(catalogue, "buyCommission"))
            except ValueError:
                raise InstrumentLookupError("Mofid pricing field buyCommission is missing or invalid",
                                            stage=stage, reason_code="PRICING_FIELD_INVALID",
                                            diagnostic={"field": "buyCommission"}) from None
            try:
                buy_ratio = _nonnegative_decimal(_value(market, "buyRatio"))
            except ValueError:
                raise InstrumentLookupError("Mofid pricing field buyRatio is missing or invalid",
                                            stage=stage, reason_code="PRICING_FIELD_INVALID",
                                            diagnostic={"field": "buyRatio"}) from None
            broker_instrument = BrokerInstrument(
                nsc_id=isin,
                tse_id=tse_id,
                name=_value(catalogue, "symbolName", "title"),
                state_code=_value(market, "stateCode", "symbolState"),
                upper_price_threshold=_value(market, "highAllowedPrice") or _value(info, "highAllowedPrice"),
                lower_price_threshold=_value(market, "lowAllowedPrice") or _value(info, "lowAllowedPrice"),
                minimum_order_quantity=_value(catalogue, "minDealableCount"),
                lot_size=_value(catalogue, "minDealableCount"),
                maximum_order_quantity_for_buy=_value(market, "maxValidBuyVolume"),
                maximum_order_quantity_for_sell=_value(market, "maxValidSellVolume"),
                fixed_price_tick=_value(market, "priceTickSize"),
                buy_commission=buy_commission,
                hide_price=_value(catalogue, "hidePrice"),
                csize=_value(catalogue, "csize"),
                buy_ratio=buy_ratio,
            )
            result = (instrument, broker_instrument)
            self._cache[ins_code] = result
            return result
        except InstrumentLookupError:
            raise
        except Exception:
            raise InstrumentLookupError("Mofid instrument lookup failed",
                                        stage=stage, reason_code="LOOKUP_FAILED") from None

    def get_nsc_id(self, ins_code):
        return self.get_instrument(ins_code)[1].nsc_id

    def refresh_cache(self):
        self._cache.clear()
