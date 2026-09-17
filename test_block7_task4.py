"""
test_block7_task4.py — Task 7.4 Second Broker Offline Stub Tests.

FakeBrokerB and FakeInstrumentProviderB are fully offline:
- no network
- no HTTP
- no API
- no login
- no credential
- no session
- no live trading

Only consumes base contracts from brokers.base and models.*.

Run:
    python -m pytest test_block7_task4.py test_broker_manager.py test_instrument_provider.py -q
"""

import inspect
import subprocess
import sys
import traceback

from brokers.base import InstrumentLookupError
from brokers.manager import BrokerManager
from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.instrument import Instrument
from models.trading_state import UNVERIFIED


# ============================================================
# Stubs (Task 7.4) — no import from brokers.agaah.*
# ============================================================

class FakeBrokerB:
    """Second Broker Stub — fully offline, deterministic.

    This is NOT a real broker. No network, no API, no login.
    """

    def __init__(self):
        self.name = "فیک"

    def login(self, username, password, **kwargs):
        return {
            "success": True,
            "username": username,
            "token": "fake-token-b",
        }

    def get_account(self):
        return Account(
            account_id=None,
            last_balance=1000000,
            tradable_balance_t1=500000,
            tradable_balance_t2=200000,
        )

    def place_order(self, order, live=False):
        return {"mode": "DRY_RUN", "sent": False, "order_id": "fake-order-b"}

    def cancel_order(self, order_id):
        return {"canceled": True, "order_id": order_id}

    def get_trading_state(self, nsc_id):
        return UNVERIFIED

    def get_buy_capacity(self, nsc_id, side_code, fund, price):
        raise NotImplementedError

    def get_sell_capacity(self, nsc_id, side_code, fund, price):
        raise NotImplementedError


class FakeInstrumentProviderB:
    """Second Broker Provider — fully offline, deterministic.

    Constructor contract: FakeInstrumentProviderB(broker)
    No mapping parameter. No network/API/Login/Session.
    """

    def __init__(self, broker):
        self._broker = broker
        self._mapping = {
            "TEST-001": "B-TEST-001",
        }
        self._cache = {}
        self._nsc_cache = {}

    def get_instrument(self, ins_code):
        if ins_code in self._cache:
            return self._cache[ins_code]

        nsc_id = self._resolve_nsc_id(ins_code)

        instrument = Instrument(
            symbol="فیک-B",
            name="فیک B",
            ins_code=ins_code,
        )

        broker_instrument = BrokerInstrument(
            name="فیک B",
            company_name="فیک B co",
            nsc_id=nsc_id,
            tse_id=ins_code,
        )

        result = (instrument, broker_instrument)
        self._cache[ins_code] = result
        return result

    def get_nsc_id(self, ins_code):
        if ins_code in self._nsc_cache:
            return self._nsc_cache[ins_code]

        nsc_id = self._resolve_nsc_id(ins_code)
        self._nsc_cache[ins_code] = nsc_id
        return nsc_id

    def refresh_cache(self):
        self._cache.clear()
        self._nsc_cache.clear()

    def _resolve_nsc_id(self, ins_code):
        if ins_code not in self._mapping:
            raise InstrumentLookupError(
                f"unknown ins_code={ins_code}"
            )
        return self._mapping[ins_code]


# ============================================================
# Test infrastructure
# ============================================================

TEST_RESULTS = []


def _run(name, fn):
    try:
        fn()
        TEST_RESULTS.append((name, "PASS", None))
    except Exception as exc:
        TEST_RESULTS.append(
            (name, "FAIL", f"{type(exc).__name__}: {exc}")
        )
        traceback.print_exc()


# ============================================================
# Tests (12 required)
# ============================================================

def test_1_registration():
    manager = BrokerManager()
    fake_broker = FakeBrokerB()
    manager.register("فیک", fake_broker, FakeInstrumentProviderB)
    assert "فیک" in manager.names()


def test_2_broker_resolution():
    manager = BrokerManager()
    fake_broker = FakeBrokerB()
    manager.register("فیک", fake_broker, FakeInstrumentProviderB)
    retrieved = manager.get("فیک")
    assert retrieved is fake_broker


def test_3_provider_resolution():
    manager = BrokerManager()
    fake_broker = FakeBrokerB()
    manager.register("فیک", fake_broker, FakeInstrumentProviderB)
    provider = manager.get_instrument_provider("فیک")
    assert type(provider).__name__ == "FakeInstrumentProviderB"


def test_4_broker_provider_identity():
    manager = BrokerManager()
    fake_broker = FakeBrokerB()
    manager.register("فیک", fake_broker, FakeInstrumentProviderB)
    provider = manager.get_instrument_provider("فیک")
    assert provider._broker is fake_broker


def test_5_mapping():
    manager = BrokerManager()
    fake_broker = FakeBrokerB()
    manager.register("فیک", fake_broker, FakeInstrumentProviderB)
    provider = manager.get_instrument_provider("فیک")
    nsc_id = provider.get_nsc_id("TEST-001")
    assert nsc_id == "B-TEST-001"


def test_6_tse_identity():
    manager = BrokerManager()
    fake_broker = FakeBrokerB()
    manager.register("فیک", fake_broker, FakeInstrumentProviderB)
    provider = manager.get_instrument_provider("فیک")
    instrument, broker_instrument = provider.get_instrument("TEST-001")
    assert broker_instrument.tse_id == "TEST-001"


def test_7_unknown_instrument():
    manager = BrokerManager()
    fake_broker = FakeBrokerB()
    manager.register("فیک", fake_broker, FakeInstrumentProviderB)
    provider = manager.get_instrument_provider("فیک")
    try:
        provider.get_nsc_id("TEST-UNKNOWN")
    except InstrumentLookupError:
        pass
    else:
        raise AssertionError(
            "expected InstrumentLookupError for get_nsc_id"
        )
    try:
        provider.get_instrument("TEST-UNKNOWN")
    except InstrumentLookupError:
        pass
    else:
        raise AssertionError(
            "expected InstrumentLookupError for get_instrument"
        )


def test_8_cache():
    manager = BrokerManager()
    fake_broker = FakeBrokerB()
    manager.register("فیک", fake_broker, FakeInstrumentProviderB)
    provider = manager.get_instrument_provider("فیک")
    inst1, bi1 = provider.get_instrument("TEST-001")
    inst2, bi2 = provider.get_instrument("TEST-001")
    assert inst1 is inst2
    assert bi1 is bi2


def test_9_refresh():
    manager = BrokerManager()
    fake_broker = FakeBrokerB()
    manager.register("فیک", fake_broker, FakeInstrumentProviderB)
    provider = manager.get_instrument_provider("فیک")
    provider.get_instrument("TEST-001")
    provider.get_nsc_id("TEST-001")
    assert len(provider._cache) > 0
    assert len(provider._nsc_cache) > 0
    provider.refresh_cache()
    assert len(provider._cache) == 0
    assert len(provider._nsc_cache) == 0


def test_10_dry_run():
    broker = FakeBrokerB()
    result = broker.place_order(object(), live=False)
    assert result["mode"] == "DRY_RUN"
    assert result["sent"] is False


def test_11_no_agah_dependency():
    for cls in [FakeBrokerB, FakeInstrumentProviderB]:
        source = inspect.getsource(cls)
        assert "agaah" not in source.lower(), (
            f"{cls.__name__} has agaah import"
        )


def test_12_agah_regression():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "test_broker_manager.py",
            "test_instrument_provider.py",
            "-q",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Regression tests failed:\n{result.stdout}\n{result.stderr}"
    )


def main():
    tests = [
        ("test_1_registration", test_1_registration),
        ("test_2_broker_resolution", test_2_broker_resolution),
        ("test_3_provider_resolution", test_3_provider_resolution),
        ("test_4_broker_provider_identity", test_4_broker_provider_identity),
        ("test_5_mapping", test_5_mapping),
        ("test_6_tse_identity", test_6_tse_identity),
        ("test_7_unknown_instrument", test_7_unknown_instrument),
        ("test_8_cache", test_8_cache),
        ("test_9_refresh", test_9_refresh),
        ("test_10_dry_run", test_10_dry_run),
        ("test_11_no_agah_dependency", test_11_no_agah_dependency),
        ("test_12_agah_regression", test_12_agah_regression),
    ]

    for name, fn in tests:
        _run(name, fn)

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
