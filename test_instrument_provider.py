"""
test_instrument_provider.py — pure unit tests for AgaahInstrumentProvider.

No network, no real Agah, no real TSETMC. Uses FakeBroker and FakeTSETMC.

Run:
    python test_instrument_provider.py
"""

import sys
import traceback


from brokers.agaah import AgaahInstrumentProvider
from brokers.agaah.instrument_provider import InstrumentLookupError
from brokers.base import InstrumentProvider
from models.broker_instrument import BrokerInstrument
from models.instrument import Instrument


# ============================================================
# Test infrastructure
# ============================================================


class _FakeResponse:

    def __init__(self, json_payload=None, status_code=200):
        self._json_payload = json_payload
        self.status_code = status_code
        self.raised = False

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(
                f"HTTP {self.status_code}"
            )
        self.raised = True

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


class _FakeSession:
    """
    Minimal session stand-in used by FakeBroker. Only .get is used by
    the provider for search. _url() and _auth_headers() are called
    on the broker itself, not the session.
    """

    def __init__(self, search_response=None):
        self.search = _FakeSearchSession(search_response or _FakeResponse({}))
        self.posts = []

    def get(self, *args, **kwargs):
        return self.search.get(*args, **kwargs)

    def post(self, *args, **kwargs):
        self.posts.append((args, kwargs))
        raise AssertionError(
            "AgaahInstrumentProvider must not POST"
        )


class FakeBroker:

    def __init__(
        self,
        search_response=None,
        instrument_by_nsc=None,
        instrument_lookup_error=None,
    ):
        self.session = _FakeSession(search_response)
        self._instrument_by_nsc = dict(instrument_by_nsc or {})
        self._instrument_lookup_error = instrument_lookup_error
        self.get_instrument_calls = []

    def _url(self, path):
        return f"https://tseonlineapi.agah.com/api/v1/{path}"

    def _auth_headers(self):
        return {"Authorization": "Bearer test"}

    def get_instrument(self, nsc_id):
        self.get_instrument_calls.append(nsc_id)
        if self._instrument_lookup_error is not None:
            raise self._instrument_lookup_error
        if nsc_id not in self._instrument_by_nsc:
            raise LookupError(f"no instrument for {nsc_id}")
        return self._instrument_by_nsc[nsc_id]


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


def _make_instrument(symbol="شبندر", ins_code="35366681030756042"):
    return Instrument(
        symbol=symbol,
        name="پالایش نفت بندرعباس",
        ins_code=ins_code,
    )


def _make_broker_instrument(nsc_id, tse_id):
    return BrokerInstrument(
        name="test",
        company_name="test co",
        nsc_id=nsc_id,
        tse_id=tse_id,
    )


# ============================================================
# Tests
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


def test_instrument_provider_is_abstract():
    """Test 0: ABC cannot be instantiated directly."""
    try:
        InstrumentProvider()
    except TypeError:
        return
    raise AssertionError(
        "InstrumentProvider() should not be instantiable"
    )


def test_exact_match_returns_correct_nsc_id():
    """
    Test 1: Multiple Agah candidates, the matching one is not first.
    The provider must return the matching candidate's nscId, not
    the first result.
    """
    ins_code = "35366681030756042"
    instrument = _make_instrument(
        symbol="شبندر", ins_code=ins_code
    )

    search_payload = {
        "isSuccess": True,
        "data": [
            {"nscId": "IRO1PNBA0003", "name": "wrong one"},
            {"nscId": "IRO1PNBA0001", "name": "right one"},
            {"nscId": "IRO1PNBA0007", "name": "another wrong"},
        ],
    }

    instrument_by_nsc = {
        "IRO1PNBA0003": _make_broker_instrument(
            "IRO1PNBA0003", "39549984459336635"
        ),
        "IRO1PNBA0001": _make_broker_instrument(
            "IRO1PNBA0001", ins_code
        ),
        "IRO1PNBA0007": _make_broker_instrument(
            "IRO1PNBA0007", "11111111111111111"
        ),
    }

    broker = FakeBroker(
        search_response=_FakeResponse(search_payload),
        instrument_by_nsc=instrument_by_nsc,
    )
    tsetmc = FakeTSETMC(instrument=instrument)
    provider = AgaahInstrumentProvider(broker, tsetmc)

    result = provider.get_nsc_id(ins_code)

    assert result == "IRO1PNBA0001", (
        f"expected IRO1PNBA0001, got {result!r}"
    )


def test_multiple_results_second_matches():
    """
    Test 2: Same idea with a different ordering.
    The matching one is the second result; the provider must still
    select it (not the first).
    """
    ins_code = "33611155027418901"
    instrument = _make_instrument(
        symbol="غشهداب", ins_code=ins_code
    )

    search_payload = {
        "isSuccess": True,
        "data": [
            {"nscId": "IRO3SHHZ0003", "name": "first wrong"},
            {"nscId": "IRO3SHHZ0001", "name": "right one"},
        ],
    }

    instrument_by_nsc = {
        "IRO3SHHZ0003": _make_broker_instrument(
            "IRO3SHHZ0003", "99999999999999999"
        ),
        "IRO3SHHZ0001": _make_broker_instrument(
            "IRO3SHHZ0001", ins_code
        ),
    }

    broker = FakeBroker(
        search_response=_FakeResponse(search_payload),
        instrument_by_nsc=instrument_by_nsc,
    )
    tsetmc = FakeTSETMC(instrument=instrument)
    provider = AgaahInstrumentProvider(broker, tsetmc)

    result = provider.get_nsc_id(ins_code)

    assert result == "IRO3SHHZ0001", (
        f"expected IRO3SHHZ0001, got {result!r}"
    )


def test_no_exact_match_raises():
    """
    Test 3: All candidates have wrong tse_id.
    Provider must raise InstrumentLookupError.
    """
    ins_code = "35366681030756042"
    instrument = _make_instrument(
        symbol="شبندر", ins_code=ins_code
    )

    search_payload = {
        "isSuccess": True,
        "data": [
            {"nscId": "IRO1PNBA0003", "name": "wrong A"},
            {"nscId": "IRO1PNBA0007", "name": "wrong B"},
        ],
    }

    instrument_by_nsc = {
        "IRO1PNBA0003": _make_broker_instrument(
            "IRO1PNBA0003", "39549984459336635"
        ),
        "IRO1PNBA0007": _make_broker_instrument(
            "IRO1PNBA0007", "11111111111111111"
        ),
    }

    broker = FakeBroker(
        search_response=_FakeResponse(search_payload),
        instrument_by_nsc=instrument_by_nsc,
    )
    tsetmc = FakeTSETMC(instrument=instrument)
    provider = AgaahInstrumentProvider(broker, tsetmc)

    try:
        provider.get_nsc_id(ins_code)
    except InstrumentLookupError:
        return
    raise AssertionError(
        "expected InstrumentLookupError, got none"
    )


def test_tsetmc_missing_raises():
    """
    Test 4: TSETMC.get_info returns None.
    Provider must raise InstrumentLookupError.
    """
    ins_code = "35366681030756042"

    broker = FakeBroker()
    tsetmc = FakeTSETMC(instrument=None)
    provider = AgaahInstrumentProvider(broker, tsetmc)

    try:
        provider.get_nsc_id(ins_code)
    except InstrumentLookupError:
        return
    raise AssertionError(
        "expected InstrumentLookupError when TSETMC returns None"
    )


def test_missing_symbol_raises():
    """
    Test 5: Instrument has no symbol.
    Provider must raise InstrumentLookupError.
    """
    ins_code = "35366681030756042"
    instrument = Instrument(
        symbol="",
        name="no symbol",
        ins_code=ins_code,
    )

    broker = FakeBroker()
    tsetmc = FakeTSETMC(instrument=instrument)
    provider = AgaahInstrumentProvider(broker, tsetmc)

    try:
        provider.get_nsc_id(ins_code)
    except InstrumentLookupError:
        return
    raise AssertionError(
        "expected InstrumentLookupError when symbol is missing"
    )


def test_agah_http_error_wrapped():
    """
    Test 6: Agah /instruments/all returns HTTP error.
    requests.RequestException must become InstrumentLookupError.
    """
    ins_code = "35366681030756042"
    instrument = _make_instrument(
        symbol="شبندر", ins_code=ins_code
    )

    import requests
    broker = FakeBroker(
        search_response=_FakeResponse(
            json_payload=None, status_code=500
        ),
    )
    tsetmc = FakeTSETMC(instrument=instrument)
    provider = AgaahInstrumentProvider(broker, tsetmc)

    try:
        provider.get_nsc_id(ins_code)
    except InstrumentLookupError as exc:
        cause = exc.__cause__
        assert isinstance(cause, requests.RequestException), (
            f"expected requests.RequestException cause, got "
            f"{type(cause).__name__}"
        )
        return
    raise AssertionError(
        "expected InstrumentLookupError on HTTP error"
    )


def test_nsc_id_cache():
    """
    Test 7: Repeated get_nsc_id(ins_code) does not re-search.
    """
    ins_code = "35366681030756042"
    instrument = _make_instrument(
        symbol="شبندر", ins_code=ins_code
    )

    search_payload = {
        "isSuccess": True,
        "data": [
            {"nscId": "IRO1PNBA0001", "name": "right"},
        ],
    }
    instrument_by_nsc = {
        "IRO1PNBA0001": _make_broker_instrument(
            "IRO1PNBA0001", ins_code
        ),
    }

    broker = FakeBroker(
        search_response=_FakeResponse(search_payload),
        instrument_by_nsc=instrument_by_nsc,
    )
    tsetmc = FakeTSETMC(instrument=instrument)
    provider = AgaahInstrumentProvider(broker, tsetmc)

    first = provider.get_nsc_id(ins_code)
    second = provider.get_nsc_id(ins_code)

    assert first == "IRO1PNBA0001"
    assert second == "IRO1PNBA0001"

    assert len(broker.session.search.calls) == 1, (
        "search must be called exactly once across two get_nsc_id "
        f"calls; got {len(broker.session.search.calls)}"
    )


def test_get_instrument_cache():
    """
    Test 8: Repeated get_instrument(ins_code) does not re-call
    TSETMC or Agah.
    """
    ins_code = "35366681030756042"
    instrument = _make_instrument(
        symbol="شبندر", ins_code=ins_code
    )

    search_payload = {
        "isSuccess": True,
        "data": [
            {"nscId": "IRO1PNBA0001", "name": "right"},
        ],
    }
    instrument_by_nsc = {
        "IRO1PNBA0001": _make_broker_instrument(
            "IRO1PNBA0001", ins_code
        ),
    }

    broker = FakeBroker(
        search_response=_FakeResponse(search_payload),
        instrument_by_nsc=instrument_by_nsc,
    )
    tsetmc = FakeTSETMC(instrument=instrument)
    provider = AgaahInstrumentProvider(broker, tsetmc)

    first_instrument, first_broker_instrument = (
        provider.get_instrument(ins_code)
    )
    second_instrument, second_broker_instrument = (
        provider.get_instrument(ins_code)
    )

    assert first_instrument is second_instrument, (
        "Instrument must be cached and returned by identity"
    )
    assert first_broker_instrument is second_broker_instrument, (
        "BrokerInstrument must be cached and returned by identity"
    )

    assert len(tsetmc.get_info_calls) == 1, (
        f"TSETMC.get_info must be called exactly once; got "
        f"{len(tsetmc.get_info_calls)}"
    )
    assert len(broker.session.search.calls) == 1, (
        f"search must be called exactly once; got "
        f"{len(broker.session.search.calls)}"
    )


def test_no_direct_ins_code_to_broker_get_instrument():
    """
    Test 9: After resolution, broker.get_instrument is only ever
    called with the resolved nscId, never with ins_code.
    """
    ins_code = "35366681030756042"
    instrument = _make_instrument(
        symbol="شبندر", ins_code=ins_code
    )

    search_payload = {
        "isSuccess": True,
        "data": [
            {"nscId": "IRO1PNBA0001", "name": "right"},
        ],
    }
    instrument_by_nsc = {
        "IRO1PNBA0001": _make_broker_instrument(
            "IRO1PNBA0001", ins_code
        ),
    }

    broker = FakeBroker(
        search_response=_FakeResponse(search_payload),
        instrument_by_nsc=instrument_by_nsc,
    )
    tsetmc = FakeTSETMC(instrument=instrument)
    provider = AgaahInstrumentProvider(broker, tsetmc)

    provider.get_nsc_id(ins_code)
    provider.get_instrument(ins_code)

    for call_arg in broker.get_instrument_calls:
        assert call_arg != ins_code, (
            f"broker.get_instrument must never be called with "
            f"ins_code; saw call with {call_arg!r}"
        )


def test_no_duplicate_tsetmc_lookup_in_get_instrument():
    """
    Test 10: Within a single get_instrument(ins_code) call,
    TSETMC.get_info is called exactly once.
    """
    ins_code = "35366681030756042"
    instrument = _make_instrument(
        symbol="شبندر", ins_code=ins_code
    )

    search_payload = {
        "isSuccess": True,
        "data": [
            {"nscId": "IRO1PNBA0001", "name": "right"},
        ],
    }
    instrument_by_nsc = {
        "IRO1PNBA0001": _make_broker_instrument(
            "IRO1PNBA0001", ins_code
        ),
    }

    broker = FakeBroker(
        search_response=_FakeResponse(search_payload),
        instrument_by_nsc=instrument_by_nsc,
    )
    tsetmc = FakeTSETMC(instrument=instrument)
    provider = AgaahInstrumentProvider(broker, tsetmc)

    provider.get_instrument(ins_code)

    assert len(tsetmc.get_info_calls) == 1, (
        f"TSETMC.get_info must be called exactly once per "
        f"get_instrument; got {len(tsetmc.get_info_calls)}"
    )


# ============================================================
# Runner
# ============================================================


def main():
    _run(
        "test_instrument_provider_is_abstract",
        test_instrument_provider_is_abstract,
    )
    _run(
        "test_exact_match_returns_correct_nsc_id",
        test_exact_match_returns_correct_nsc_id,
    )
    _run(
        "test_multiple_results_second_matches",
        test_multiple_results_second_matches,
    )
    _run(
        "test_no_exact_match_raises",
        test_no_exact_match_raises,
    )
    _run(
        "test_tsetmc_missing_raises",
        test_tsetmc_missing_raises,
    )
    _run(
        "test_missing_symbol_raises",
        test_missing_symbol_raises,
    )
    _run(
        "test_agah_http_error_wrapped",
        test_agah_http_error_wrapped,
    )
    _run(
        "test_nsc_id_cache",
        test_nsc_id_cache,
    )
    _run(
        "test_get_instrument_cache",
        test_get_instrument_cache,
    )
    _run(
        "test_no_direct_ins_code_to_broker_get_instrument",
        test_no_direct_ins_code_to_broker_get_instrument,
    )
    _run(
        "test_no_duplicate_tsetmc_lookup_in_get_instrument",
        test_no_duplicate_tsetmc_lookup_in_get_instrument,
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
