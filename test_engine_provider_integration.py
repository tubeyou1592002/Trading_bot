"""
test_engine_provider_integration.py

Integration tests for the flow:

    ins_code -> AgaahInstrumentProvider -> (Instrument, BrokerInstrument)
             -> OrderEngine.execute_by_ins_code(...)

No network, no real Agah, no real TSETMC, no real order.
All collaborators are in-process fakes.

The tests call the real production method
``OrderEngine.execute_by_ins_code``; they do not re-implement
the orchestration in the test file.
"""

import sys
import traceback


from brokers.agaah import AgaahInstrumentProvider
from brokers.agaah.instrument_provider import InstrumentLookupError
from brokers.base import Broker
from core.order_engine import OrderEngine
from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.instrument import Instrument
from models.order import BUY, Order
from models.trading_state import (
    UNVERIFIED,
    VERIFIED_TRADABLE,
    TradingState,
)


# ============================================================
# Fakes
# ============================================================


class _FakeResponse:

    def __init__(self, json_payload=None, status_code=200):
        self._json_payload = json_payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(
                f"HTTP {self.status_code}"
            )

    def json(self):
        if self._json_payload is None:
            raise ValueError("no json")
        return self._json_payload


class _FakeSearchSession:

    def __init__(self, response):
        self._response = response
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({
            "url": url,
            "params": dict(params or {}),
            "headers": dict(headers or {}),
            "timeout": timeout,
        })
        return self._response

    def post(self, *args, **kwargs):
        raise AssertionError(
            "Provider must not POST in this flow"
        )


class _FakeSession:

    def __init__(self, search_response):
        self.search = _FakeSearchSession(search_response)
        self.posts = []

    def get(self, *args, **kwargs):
        return self.search.get(*args, **kwargs)

    def post(self, *args, **kwargs):
        self.posts.append((args, kwargs))
        raise AssertionError(
            "AgaahInstrumentProvider must not POST"
        )


class FakeAgahLikeBroker(Broker):
    """
    A fake broker that mimics the small slice of AgaahBroker
    surface area that the provider + engine need. It is a
    subclass of brokers.base.Broker so it remains a valid
    'Broker' as far as OrderEngine is concerned, and it
    implements _url/_auth_headers/get_instrument so that
    AgaahInstrumentProvider is happy with it.
    """

    def __init__(
        self,
        search_response=None,
        instrument_by_nsc=None,
        state=UNVERIFIED,
    ):
        self.session = _FakeSession(
            search_response or _FakeResponse({})
        )
        self._instrument_by_nsc = dict(
            instrument_by_nsc or {}
        )
        self._state = state
        self.placed_calls = []
        self.get_instrument_calls = []
        self.get_instrument_by_instrument_id_calls = []
        self.live_trading_enabled = False

    @property
    def name(self):
        return "FakeAgahLikeBroker"

    def _url(self, path):
        return f"https://tseonlineapi.agah.com/api/v1/{path}"

    def _auth_headers(self):
        return {"Authorization": "Bearer test"}

    def login(self, username, password, **kwargs):
        return {"userName": username}

    def get_account(self):
        return Account(tradable_balance_t1=10_000_000)

    def get_trading_state(self, nsc_id):
        return self._state

    def get_instrument(self, nsc_id):
        self.get_instrument_calls.append(nsc_id)
        if nsc_id not in self._instrument_by_nsc:
            raise LookupError(f"no instrument for {nsc_id}")
        return self._instrument_by_nsc[nsc_id]

    def place_order(self, order, live=False):
        self.placed_calls.append({
            "order": order,
            "live": live,
        })
        return {
            "mode": "DRY_RUN" if not live else "LIVE",
            "sent": live,
            "payload": order.to_payload(),
        }

    def cancel_order(self, order_id):
        raise NotImplementedError


class FakeTSETMC:

    def __init__(self, instrument=None, error=None):
        self._instrument = instrument
        self._error = error
        self.get_info_calls = []

    def get_info(self, ins_code):
        self.get_info_calls.append(ins_code)
        if self._error is not None:
            raise self._error
        return self._instrument


# ============================================================
# Orchestration helper (test-only, NOT production code)
# ============================================================
#
# The contract under test is:
#   1) provider.get_instrument(ins_code) must succeed.
#   2) order.nsc_id must equal provider-resolved nsc_id;
#      otherwise execution must be BLOCKED without
#      silently overwriting order.nsc_id.
#   3) If the provider raises InstrumentLookupError,
#      the engine result must be BLOCKED with a message
#      containing "Instrument lookup failed:".
#   4) The legacy broker.get_instrument_by_instrument_id
#      must not be called in this flow.


# ============================================================
# Tests
# ============================================================
# Fixtures
# ============================================================


def _make_tsetmc_instrument(
    symbol="شبندر", ins_code="35366681030756042"
):
    return Instrument(
        symbol=symbol,
        name="پالایش نفت بندرعباس",
        ins_code=ins_code,
    )


def _make_broker_instrument(nsc_id, tse_id):
    return BrokerInstrument(
        name="خودرو",
        company_name="ایران خودرو",
        nsc_id=nsc_id,
        tse_id=tse_id,
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
        maximum_order_quantity_for_buy=3_000_000,
        maximum_order_quantity_for_sell=3_000_000,
        bid_ask_list=[],
        is_fund=False,
    )


def _make_order(nsc_id, price=716, quantity=100):
    return Order(
        nsc_id=nsc_id,
        side=BUY,
        price=price,
        quantity=quantity,
        bank_account_id=0,
    )


def _make_account(balance=100_000_000):
    return Account(tradable_balance_t1=balance)


def _build_provider_for_match(
    ins_code,
    tsetmc_instrument,
    search_payload,
    nsc_id,
):
    broker = FakeAgahLikeBroker(
        search_response=_FakeResponse(search_payload),
        instrument_by_nsc={
            nsc_id: _make_broker_instrument(nsc_id, ins_code),
        },
    )
    tsetmc = FakeTSETMC(instrument=tsetmc_instrument)
    provider = AgaahInstrumentProvider(broker, tsetmc)
    return broker, tsetmc, provider


# ============================================================
# Tests
# ============================================================


TEST_RESULTS = []


def _run(name, fn):
    try:
        fn()
        TEST_RESULTS.append((name, "PASS", None))
    except Exception as exc:
        TEST_RESULTS.append((
            name,
            "FAIL",
            f"{type(exc).__name__}: {exc}",
        ))
        traceback.print_exc()


def test_A_happy_path_dry_run():
    """
    A) ins_code -> Provider -> matching nsc_id
       -> OrderEngine dry-run -> success, sent=False, mode=DRY_RUN
    """
    ins_code = "35366681030756042"
    nsc_id = "IRO1PNBA0001"
    tsetmc_instrument = _make_tsetmc_instrument(
        symbol="شبندر", ins_code=ins_code
    )
    search_payload = {
        "isSuccess": True,
        "data": [
            {"nscId": nsc_id, "name": "right one"},
        ],
    }
    broker, tsetmc, provider = _build_provider_for_match(
        ins_code,
        tsetmc_instrument,
        search_payload,
        nsc_id,
    )
    broker._state = VERIFIED_TRADABLE

    engine = OrderEngine()
    order = _make_order(nsc_id=nsc_id)
    account = _make_account()

    original_nsc_id = order.nsc_id

    result = engine.execute_by_ins_code(
        broker=broker,
        provider=provider,
        ins_code=ins_code,
        order=order,
        account=account,
        live=False,
    )

    assert result.success is True, (
        f"happy path must succeed; got {result.success} "
        f"mode={result.mode} msg={result.message}"
    )
    assert result.sent is False, (
        f"dry-run must not send; sent={result.sent}"
    )
    assert result.mode == "DRY_RUN", (
        f"mode must be DRY_RUN; got {result.mode}"
    )
    assert order.nsc_id == original_nsc_id, (
        "order.nsc_id must not be mutated"
    )
    assert len(broker.placed_calls) == 1, (
        "broker.place_order must be called exactly once"
    )
    assert broker.placed_calls[0]["live"] is False


def test_B_nsc_id_mismatch_blocked_without_overwrite():
    """
    B) Provider returns nsc_id X; order carries nsc_id Y != X.
       Pipeline must BLOCK, and order.nsc_id must remain Y
       (no silent overwrite).
    """
    ins_code = "35366681030756042"
    resolved_nsc_id = "IRO1PNBA0001"
    wrong_order_nsc_id = "IRO1OTHER9999"

    tsetmc_instrument = _make_tsetmc_instrument(
        symbol="شبندر", ins_code=ins_code
    )
    search_payload = {
        "isSuccess": True,
        "data": [
            {"nscId": resolved_nsc_id, "name": "right one"},
        ],
    }
    broker, tsetmc, provider = _build_provider_for_match(
        ins_code,
        tsetmc_instrument,
        search_payload,
        resolved_nsc_id,
    )
    broker._state = VERIFIED_TRADABLE

    engine = OrderEngine()
    order = _make_order(nsc_id=wrong_order_nsc_id)
    account = _make_account()

    result = engine.execute_by_ins_code(
        broker=broker,
        provider=provider,
        ins_code=ins_code,
        order=order,
        account=account,
        live=False,
    )

    assert result.success is False, (
        "mismatch must NOT succeed"
    )
    assert result.sent is False
    assert result.mode == "BLOCKED", (
        f"mode must be BLOCKED; got {result.mode}"
    )
    assert order.nsc_id == wrong_order_nsc_id, (
        f"order.nsc_id must NOT be overwritten; "
        f"expected {wrong_order_nsc_id}, got {order.nsc_id!r}"
    )
    assert len(broker.placed_calls) == 0, (
        "broker.place_order must not be called on mismatch"
    )


def test_C_instrument_lookup_failure_blocked():
    """
    C) Provider raises InstrumentLookupError.
       Result must be BLOCKED with message containing
       'Instrument lookup failed:' and broker.place_order
       must not be called.
    """
    ins_code = "35366681030756042"
    tsetmc_instrument = _make_tsetmc_instrument(
        symbol="شبندر", ins_code=ins_code
    )
    search_payload = {
        "isSuccess": True,
        "data": [
            {"nscId": "IRO1PNBA0003", "name": "wrong tse_id"},
        ],
    }
    broker = FakeAgahLikeBroker(
        search_response=_FakeResponse(search_payload),
        instrument_by_nsc={
            "IRO1PNBA0003": _make_broker_instrument(
                "IRO1PNBA0003", "39549984459336635"
            ),
        },
        state=VERIFIED_TRADABLE,
    )
    tsetmc = FakeTSETMC(instrument=tsetmc_instrument)
    provider = AgaahInstrumentProvider(broker, tsetmc)

    engine = OrderEngine()
    order = _make_order(nsc_id="IRO1PNBA0001")
    account = _make_account()

    result = engine.execute_by_ins_code(
        broker=broker,
        provider=provider,
        ins_code=ins_code,
        order=order,
        account=account,
        live=False,
    )

    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED", (
        f"mode must be BLOCKED; got {result.mode}"
    )
    assert result.message is not None
    assert "Instrument lookup failed:" in result.message, (
        f"message must contain 'Instrument lookup failed:'; "
        f"got: {result.message!r}"
    )
    assert len(broker.placed_calls) == 0, (
        "broker.place_order must not be called on lookup failure"
    )


def test_D_legacy_lookup_not_used():
    """
    D) In this flow, broker.get_instrument_by_instrument_id
       must NOT be called. Only provider.get_instrument and
       broker.get_instrument(nsc_id) (called by the provider
       internally for tse_id verification) may be used.
    """
    ins_code = "35366681030756042"
    nsc_id = "IRO1PNBA0001"
    tsetmc_instrument = _make_tsetmc_instrument(
        symbol="شبندر", ins_code=ins_code
    )
    search_payload = {
        "isSuccess": True,
        "data": [
            {"nscId": nsc_id, "name": "right one"},
        ],
    }
    broker, tsetmc, provider = _build_provider_for_match(
        ins_code,
        tsetmc_instrument,
        search_payload,
        nsc_id,
    )
    broker._state = VERIFIED_TRADABLE

    engine = OrderEngine()
    order = _make_order(nsc_id=nsc_id)
    account = _make_account()

    result = engine.execute_by_ins_code(
        broker=broker,
        provider=provider,
        ins_code=ins_code,
        order=order,
        account=account,
        live=False,
    )

    assert result.success is True
    assert result.mode == "DRY_RUN"

    assert (
        len(broker.get_instrument_by_instrument_id_calls) == 0
    ), (
        "legacy broker.get_instrument_by_instrument_id "
        "must not be called in this flow"
    )


# ============================================================
# Runner
# ============================================================


def main():
    _run(
        "test_A_happy_path_dry_run",
        test_A_happy_path_dry_run,
    )
    _run(
        "test_B_nsc_id_mismatch_blocked_without_overwrite",
        test_B_nsc_id_mismatch_blocked_without_overwrite,
    )
    _run(
        "test_C_instrument_lookup_failure_blocked",
        test_C_instrument_lookup_failure_blocked,
    )
    _run(
        "test_D_legacy_lookup_not_used",
        test_D_legacy_lookup_not_used,
    )

    print()
    print("=" * 60)
    passed = sum(1 for _, s, _ in TEST_RESULTS if s == "PASS")
    failed = sum(1 for _, s, _ in TEST_RESULTS if s == "FAIL")
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    for name, status, msg in TEST_RESULTS:
        line = f"  [{status}] {name}"
        if msg:
            line += f"  -- {msg}"
        print(line)

    if failed:
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
