"""
test_broker_manager.py

Unit tests for BrokerManager.get_instrument_provider.

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


def main():
    _run(
        "test_get_instrument_provider_returns_correct_type",
        test_get_instrument_provider_returns_correct_type,
    )
    _run(
        "test_get_instrument_provider_caches_instance",
        test_get_instrument_provider_caches_instance,
    )
    _run(
        "test_get_instrument_provider_uses_same_broker_instance",
        test_get_instrument_provider_uses_same_broker_instance,
    )
    _run(
        "test_get_instrument_provider_unknown_broker_raises",
        test_get_instrument_provider_unknown_broker_raises,
    )
    _run(
        "test_providers_dict_is_lazy",
        test_providers_dict_is_lazy,
    )
    _run(
        "test_get_still_works_alongside_provider",
        test_get_still_works_alongside_provider,
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
