"""
test_broker_manager.py

Unit tests for BrokerManager multi-broker support.

These tests are fully offline:
- no network
- no login
- no captcha
- no real order
- no TSETMC call
- no Agah API call

Construction of AgaahBroker and AgaahInstrumentProvider does
not perform network I/O on its own (it only stores the broker
reference and creates an empty cache), so the wiring can be
exercised without any real Agah session.

Run:
    python test_broker_manager.py
"""

import sys
import traceback

from brokers.agaah import (
    AgaahBroker,
    AgaahInstrumentProvider,
)
from brokers.manager import BrokerManager


class FakeBroker:
    """Minimal fake broker for testing multi-broker registration."""

    def __init__(self):
        self.name = "فیک"
        self._called = False

    def get_instrument(self, nsc_id):
        return FakeBrokerInstrument(nsc_id)

    def get_account(self):
        return None

    def place_order(self, order, live=False):
        return {"mode": "DRY_RUN", "sent": False}

    def cancel_order(self, order_id):
        raise NotImplementedError

    def get_trading_state(self, nsc_id):
        return "UNVERIFIED"

    def get_buy_capacity(self, nsc_id, side_code, fund, price):
        raise NotImplementedError

    def get_sell_capacity(self, nsc_id, side_code, fund, price):
        raise NotImplementedError


class FakeInstrumentProvider:
    """Minimal fake instrument provider that stores the broker reference."""

    def __init__(self, broker):
        self._broker = broker
        self._cache = {}

    def get_instrument(self, ins_code):
        return (None, None)

    def get_nsc_id(self, ins_code):
        return None

    def refresh_cache(self):
        self._cache.clear()


class FakeBrokerInstrument:
    """Minimal fake broker instrument."""

    def __init__(self, nsc_id):
        self.nsc_id = nsc_id
        self.tse_id = nsc_id


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


# =====================================================================
# Existing tests (must still pass)
# =====================================================================

def test_get_instrument_provider_returns_correct_type():
    """
    Test 1: get_instrument_provider('آگاه') returns
    an AgaahInstrumentProvider instance.
    """
    manager = BrokerManager()

    provider = manager.get_instrument_provider("آگاه")

    assert isinstance(provider, AgaahInstrumentProvider), (
        f"expected AgaahInstrumentProvider, got "
        f"{type(provider).__name__}"
    )


def test_get_instrument_provider_caches_instance():
    """
    Test 2: Two calls return the same instance (lazy cache).
    """
    manager = BrokerManager()

    provider1 = manager.get_instrument_provider("آگاه")
    provider2 = manager.get_instrument_provider("آگاه")

    assert provider1 is provider2, (
        "get_instrument_provider must return the same "
        "cached instance on repeated calls"
    )


def test_get_instrument_provider_uses_same_broker_instance():
    """
    Test 3: The provider's internal broker is the exact
    same instance stored in BrokerManager.brokers (no new
    AgaahBroker is constructed by the manager).
    """
    manager = BrokerManager()

    expected_broker = manager.brokers["آگاه"]
    assert isinstance(expected_broker, AgaahBroker)

    initial_broker_id = id(expected_broker)

    provider = manager.get_instrument_provider("آگاه")

    actual_broker = provider._broker

    assert actual_broker is expected_broker, (
        "provider must wrap the existing AgaahBroker "
        "instance from BrokerManager.brokers, not a "
        "freshly constructed one"
    )
    assert id(actual_broker) == initial_broker_id, (
        "broker identity must be preserved"
    )


def test_get_instrument_provider_unknown_broker_raises():
    """
    Test 4: get_instrument_provider with an unknown
    broker name raises ValueError (same behavior as
    BrokerManager.get).
    """
    manager = BrokerManager()

    try:
        manager.get_instrument_provider("نامعلوم")
    except ValueError:
        return

    raise AssertionError(
        "expected ValueError for unknown broker, got none"
    )


def test_providers_dict_is_lazy():
    """
    Test 5 (extra): providers dict is not populated in
    __init__; it is populated only after the first
    get_instrument_provider call.
    """
    manager = BrokerManager()

    assert "آگاه" not in manager.providers, (
        "providers cache must be lazy; no provider should "
        "exist in __init__"
    )

    manager.get_instrument_provider("آگاه")

    assert "آگاه" in manager.providers, (
        "after get_instrument_provider, the provider "
        "should be cached in self.providers"
    )


def test_get_still_works_alongside_provider():
    """
    Test 6 (extra): The pre-existing BrokerManager.get(...)
    still works and is not affected by the new
    get_instrument_provider method.
    """
    manager = BrokerManager()

    broker = manager.get("آگاه")

    assert isinstance(broker, AgaahBroker)


# =====================================================================
# Task 7.2 required tests
# =====================================================================

def test_agah_broker_resolves_as_before():
    """
    Test 7.2-1: Broker آگاه مثل قبل resolve می‌شود.
    """
    manager = BrokerManager()

    broker = manager.get("آگاه")

    assert isinstance(broker, AgaahBroker)


def test_agah_provider_is_lazy():
    """
    Test 7.2-2: Provider آگاه lazy ساخته می‌شود.
    """
    manager = BrokerManager()

    assert "آگاه" not in manager.providers

    provider = manager.get_instrument_provider("آگاه")

    assert "آگاه" in manager.providers
    assert isinstance(provider, AgaahInstrumentProvider)


def test_agah_provider_is_cached():
    """
    Test 7.2-3: Provider آگاه cache می‌شود.
    """
    manager = BrokerManager()

    provider1 = manager.get_instrument_provider("آگاه")
    provider2 = manager.get_instrument_provider("آگاه")

    assert provider1 is provider2, (
        "Provider آگاه باید کش شود؛ دو بار همون instance برگردانده شود"
    )


def test_agah_provider_uses_same_broker_instance():
    """
    Test 7.2-4: Provider آگاه همان AgaahBroker instance
    مدیریت‌شده را دریافت می‌کند.
    """
    manager = BrokerManager()

    expected_broker = manager.brokers["آگاه"]
    provider = manager.get_instrument_provider("آگاه")

    assert provider._broker is expected_broker, (
        "Provider آگاه باید همان AgaahBroker instance را داشته باشد"
    )


def test_second_broker_can_be_registered():
    """
    Test 7.2-5: یک Broker دوم fake/offline قابل ثبت است.
    """
    manager = BrokerManager()

    fake_broker = FakeBroker()
    manager.register("فیک", fake_broker, FakeInstrumentProvider)

    assert "فیک" in manager.names()


def test_second_broker_resolves_by_name():
    """
    Test 7.2-6: Broker دوم با نام خودش resolve می‌شود.
    """
    manager = BrokerManager()

    fake_broker = FakeBroker()
    manager.register("فیک", fake_broker, FakeInstrumentProvider)

    retrieved = manager.get("فیک")

    assert retrieved is fake_broker
    assert isinstance(retrieved, FakeBroker)


def test_second_broker_provider_is_created():
    """
    Test 7.2-7: Provider دوم با Broker دوم ساخته می‌شود.
    """
    manager = BrokerManager()

    fake_broker = FakeBroker()
    manager.register("فیک", fake_broker, FakeInstrumentProvider)

    provider = manager.get_instrument_provider("فیک")

    assert isinstance(provider, FakeInstrumentProvider)
    assert provider._broker is fake_broker


def test_second_provider_is_not_same_as_agah():
    """
    Test 7.2-8: Provider دوم با Provider آگاه قاطی نمی‌شود.
    """
    manager = BrokerManager()

    fake_broker = FakeBroker()
    manager.register("فیک", fake_broker, FakeInstrumentProvider)

    agah_provider = manager.get_instrument_provider("آگاه")
    fake_provider = manager.get_instrument_provider("فیک")

    assert agah_provider is not fake_provider, (
        "Provider دوم نباید با Provider آگاه قاطی شود"
    )


def test_two_broker_caches_are_independent():
    """
    Test 7.2-9: cache دو Broker مستقل است.
    """
    manager = BrokerManager()

    fake_broker = FakeBroker()
    manager.register("فیک", fake_broker, FakeInstrumentProvider)

    agah_provider1 = manager.get_instrument_provider("آگاه")
    agah_provider2 = manager.get_instrument_provider("آگاه")
    fake_provider1 = manager.get_instrument_provider("فیک")
    fake_provider2 = manager.get_instrument_provider("فیک")

    assert agah_provider1 is agah_provider2, (
        "دو بار آگاه باید همون instance برگردانده شود"
    )
    assert fake_provider1 is fake_provider2, (
        "دو بار فیک باید همون instance برگردانده شود"
    )
    assert agah_provider1 is not fake_provider1, (
        "cache آگاه و فیک باید مستقل باشد"
    )


def test_unknown_broker_raises_valueerror():
    """
    Test 7.2-10: Broker ناشناخته → ValueError.
    """
    manager = BrokerManager()

    try:
        manager.get("نامعلوم")
    except ValueError:
        return

    raise AssertionError(
        "expected ValueError for unknown broker, got none"
    )


def test_unknown_provider_raises_valueerror():
    """
    Test 7.2-11: Provider ناشناخته → ValueError.
    """
    manager = BrokerManager()

    try:
        manager.get_instrument_provider("نامعلوم")
    except ValueError:
        return

    raise AssertionError(
        "expected ValueError for unknown provider, got none"
    )


def test_duplicate_registration_raises():
    """
    Test 7.2-12: Registering a broker with a name that
    already exists raises ValueError. Broker and Provider
    remain unchanged.
    """
    manager = BrokerManager()

    broker1 = FakeBroker()
    manager.register("X", broker1, FakeInstrumentProvider)

    provider1 = manager.get_instrument_provider("X")
    assert provider1._broker is broker1

    broker2 = FakeBroker()
    provider2 = FakeInstrumentProvider(broker2)

    try:
        manager.register("X", broker2, provider2.__class__)
    except ValueError:
        pass
    else:
        raise AssertionError(
            "expected ValueError for duplicate registration, got none"
        )

    assert manager.get("X") is broker1, (
        "Broker 1 must remain unchanged after failed duplicate registration"
    )

    provider_after = manager.get_instrument_provider("X")
    assert provider_after is provider1, (
        "Provider must remain unchanged after failed duplicate registration"
    )

    assert "X" in manager.brokers
    assert manager.brokers["X"] is broker1
    assert broker2 not in manager.brokers.values(), (
        "Broker 2 must not be in the manager"
    )


def main():
    tests = [
        # Existing tests
        ("test_get_instrument_provider_returns_correct_type",
         test_get_instrument_provider_returns_correct_type),
        ("test_get_instrument_provider_caches_instance",
         test_get_instrument_provider_caches_instance),
        ("test_get_instrument_provider_uses_same_broker_instance",
         test_get_instrument_provider_uses_same_broker_instance),
        ("test_get_instrument_provider_unknown_broker_raises",
         test_get_instrument_provider_unknown_broker_raises),
        ("test_providers_dict_is_lazy",
         test_providers_dict_is_lazy),
        ("test_get_still_works_alongside_provider",
         test_get_still_works_alongside_provider),
        # Task 7.2 required tests
        ("test_agah_broker_resolves_as_before",
         test_agah_broker_resolves_as_before),
        ("test_agah_provider_is_lazy",
         test_agah_provider_is_lazy),
        ("test_agah_provider_is_cached",
         test_agah_provider_is_cached),
        ("test_agah_provider_uses_same_broker_instance",
         test_agah_provider_uses_same_broker_instance),
        ("test_second_broker_can_be_registered",
         test_second_broker_can_be_registered),
        ("test_second_broker_resolves_by_name",
         test_second_broker_resolves_by_name),
        ("test_second_broker_provider_is_created",
         test_second_broker_provider_is_created),
        ("test_second_provider_is_not_same_as_agah",
         test_second_provider_is_not_same_as_agah),
        ("test_two_broker_caches_are_independent",
         test_two_broker_caches_are_independent),
        ("test_unknown_broker_raises_valueerror",
         test_unknown_broker_raises_valueerror),
        ("test_unknown_provider_raises_valueerror",
         test_unknown_provider_raises_valueerror),
        ("test_duplicate_registration_raises",
         test_duplicate_registration_raises),
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
