from types import SimpleNamespace

import pytest

from brokers.base import InstrumentLookupError
from brokers.mofid.instrument_provider import MofidInstrumentProvider


INS_CODE = "123"
ISIN = "ISIN-123"


class FakeTsetmc:
    def get_info(self, ins_code):
        return SimpleNamespace(instrument_id=ISIN, ins_code=ins_code)


class FakeAdapter:
    def __init__(self, commission="0.01", ratio="0.02"):
        self.commission, self.ratio = commission, ratio

    def _read_symbol_data(self, path, payload):
        if path.endswith("symbols/all"):
            return {"symbols": [{"symbolIsin": ISIN, "buyCommission": self.commission,
                                 "hidePrice": "0.5", "csize": 1,
                                 "minDealableCount": 1}]}
        if path.endswith("marketdata/v2"):
            return [{"symbolIsin": ISIN, "buyRatio": self.ratio,
                     "maxValidBuyVolume": 100}]
        return {"symbolISIN": ISIN}


def test_provider_preserves_validated_catalogue_commission_and_market_ratio():
    _, details = MofidInstrumentProvider(FakeTsetmc(), FakeAdapter()).get_instrument(INS_CODE)
    assert str(details.buy_commission) == "0.01"
    assert str(details.buy_ratio) == "0.02"


@pytest.mark.parametrize("commission,ratio", [
    (None, "0.02"), ("NaN", "0.02"), ("Infinity", "0.02"),
    ("-0.01", "0.02"), ("0.01", None), ("0.01", "NaN"),
    ("0.01", "Infinity"), ("0.01", "-0.02"), (True, "0.02"),
])
def test_provider_rejects_invalid_pricing_fields(commission, ratio):
    provider = MofidInstrumentProvider(FakeTsetmc(), FakeAdapter(commission, ratio))
    with pytest.raises(InstrumentLookupError):
        provider.get_instrument(INS_CODE)


def test_provider_reports_missing_pricing_field_without_response_values():
    provider = MofidInstrumentProvider(FakeTsetmc(), FakeAdapter(commission=None))
    with pytest.raises(InstrumentLookupError) as caught:
        provider.get_instrument(INS_CODE)
    assert caught.value.stage == "pricing_metadata"
    assert caught.value.reason_code == "PRICING_FIELD_INVALID"
    assert caught.value.diagnostic == {"field": "buyCommission"}
    assert "buyCommission" in str(caught.value)


def test_provider_reports_tsetmc_lookup_failure_stage():
    class FailedTsetmc:
        def get_info(self, ins_code):
            raise RuntimeError("private body")

    with pytest.raises(InstrumentLookupError) as caught:
        MofidInstrumentProvider(FailedTsetmc(), FakeAdapter()).get_instrument(INS_CODE)
    assert caught.value.stage == "tsetmc_lookup"
    assert caught.value.reason_code == "LOOKUP_FAILED"
    assert "private body" not in str(caught.value)
