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

    def set_response(self, response):
        """Allow tests to reconfigure the search response at runtime."""
        self._response = response


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
# Task 7.3 isolation fixtures
# ============================================================


class FakeInstrumentProviderB:
    """
    Fully offline fake provider for Broker B.

    Maps TEST-001 -> B-TEST-001. It is a test tool only:
    - no network, no API, no login/auth
    - no dependency on AgaahInstrumentProvider
    - no knowledge of the real Agah mapping
    - owns its own mapping and cache dictionaries
    - implements only the minimal InstrumentProvider contract
    """

    def __init__(self, broker, mapping=None):
        self._broker = broker
        self._mapping = dict(mapping or {})
        self._cache = {}
        self._nsc_cache = {}

    def get_instrument(
        self,
        ins_code,
    ):
        if ins_code in self._cache:
            return self._cache[ins_code]

        nsc_id = self._resolve(ins_code)
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

    def get_nsc_id(
        self,
        ins_code,
    ):
        if ins_code in self._nsc_cache:
            return self._nsc_cache[ins_code]

        nsc_id = self._resolve(ins_code)
        self._nsc_cache[ins_code] = nsc_id
        return nsc_id

    def refresh_cache(self):
        self._cache.clear()
        self._nsc_cache.clear()

    def _resolve(self, ins_code):
        if ins_code not in self._mapping:
            raise InstrumentLookupError(
                f"unknown ins_code={ins_code}"
            )
        return self._mapping[ins_code]


def _make_provider_a():
    """
    Build AgaahInstrumentProvider (Provider A) with fully
    offline fakes. Resolves TEST-001 -> A-TEST-001.
    """
    ins_code = "TEST-001"
    instrument = Instrument(
        symbol="فیک-A",
        name="فیک A",
        ins_code=ins_code,
    )
    search_payload = {
        "isSuccess": True,
        "data": [
            {"nscId": "A-TEST-001", "name": "right A"},
        ],
    }
    instrument_by_nsc = {
        "A-TEST-001": _make_broker_instrument(
            "A-TEST-001", ins_code
        ),
    }
    broker = FakeBroker(
        search_response=_FakeResponse(search_payload),
        instrument_by_nsc=instrument_by_nsc,
    )
    tsetmc = FakeTSETMC(instrument=instrument)
    provider = AgaahInstrumentProvider(broker, tsetmc)
    return provider, broker


def _make_provider_b():
    """
    Build FakeInstrumentProviderB (Provider B). Resolves
    TEST-001 -> B-TEST-001.
    """
    broker = FakeBroker()
    provider = FakeInstrumentProviderB(
        broker,
        mapping={"TEST-001": "B-TEST-001"},
    )
    return provider, broker


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


def test_provider_a_isolation():
    """
    Task 7.3-1: Provider A resolves TEST-001 → A-TEST-001.
    """
    provider, _ = _make_provider_a()
    instrument, broker_instrument = provider.get_instrument("TEST-001")
    assert broker_instrument.nsc_id == "A-TEST-001"
    assert broker_instrument.tse_id == "TEST-001"
    assert instrument.ins_code == "TEST-001"


def test_provider_b_isolation():
    """
    Task 7.3-2: Provider B resolves TEST-001 → B-TEST-001.
    """
    provider, _ = _make_provider_b()
    instrument, broker_instrument = provider.get_instrument("TEST-001")
    assert broker_instrument.nsc_id == "B-TEST-001"
    assert broker_instrument.tse_id == "TEST-001"
    assert instrument.ins_code == "TEST-001"


def test_provider_a_and_b_are_different():
    """
    Task 7.3-3: Providers A and B produce different nsc_ids for the same ins_code.
    """
    provider_a, _ = _make_provider_a()
    provider_b, _ = _make_provider_b()

    _, bi_a = provider_a.get_instrument("TEST-001")
    _, bi_b = provider_b.get_instrument("TEST-001")

    assert bi_a.nsc_id != bi_b.nsc_id
    assert bi_a.nsc_id == "A-TEST-001"
    assert bi_b.nsc_id == "B-TEST-001"


def test_tse_id_is_same_for_both():
    """
    Task 7.3-4: Both providers preserve the same tse_id (ins_code) in the result.
    """
    provider_a, _ = _make_provider_a()
    provider_b, _ = _make_provider_b()

    _, bi_a = provider_a.get_instrument("TEST-001")
    _, bi_b = provider_b.get_instrument("TEST-001")

    assert bi_a.tse_id == bi_b.tse_id == "TEST-001"


def test_provider_a_never_returns_b_nsc_id():
    """
    Task 7.3-5: Provider A never returns Provider B's nsc_id.
    """
    provider_a, _ = _make_provider_a()

    _, bi_a = provider_a.get_instrument("TEST-001")
    assert bi_a.nsc_id != "B-TEST-001"
    assert bi_a.nsc_id == "A-TEST-001"


def test_provider_b_never_returns_a_nsc_id():
    """
    Task 7.3-6: Provider B never returns Provider A's nsc_id.
    """
    provider_b, _ = _make_provider_b()

    _, bi_b = provider_b.get_instrument("TEST-001")
    assert bi_b.nsc_id != "A-TEST-001"
    assert bi_b.nsc_id == "B-TEST-001"


def test_provider_a_cache_isolation():
    """
    Task 7.3-7: Provider A cache is isolated from Provider B.
    """
    provider_a, _ = _make_provider_a()
    provider_b, _ = _make_provider_b()

    # Prime caches
    _, bi_a = provider_a.get_instrument("TEST-001")
    _, bi_b = provider_b.get_instrument("TEST-001")

    # They should be different objects
    assert bi_a is not bi_b

    # A should never return B's broker instrument (isolation)
    # (already guaranteed by different mappings, but explicitly check)
    assert bi_a.nsc_id != bi_b.nsc_id


def test_provider_b_cache_isolation():
    """
    Task 7.3-8: Provider B cache is isolated from Provider A.
    """
    provider_a, _ = _make_provider_a()
    provider_b, _ = _make_provider_b()

    # Prime caches
    _, bi_a = provider_a.get_instrument("TEST-001")
    _, bi_b = provider_b.get_instrument("TEST-001")

    # Prime again - should hit cache (same instance)
    _, bi_a2 = provider_a.get_instrument("TEST-001")
    _, bi_b2 = provider_b.get_instrument("TEST-001")

    assert bi_a2 is bi_a
    assert bi_b2 is bi_b


def test_provider_a_broker_identity():
    """
    Task 7.3-9: Provider A wraps Broker A.
    """
    provider_a, broker_a = _make_provider_a()
    assert provider_a._broker is broker_a


def test_provider_b_broker_identity():
    """
    Task 7.3-10: Provider B wraps Broker B.
    """
    provider_b, broker_b = _make_provider_b()
    assert provider_b._broker is broker_b


def test_provider_a_not_b_broker():
    """
    Task 7.3-11: Provider A's broker is not Provider B's broker.
    """
    provider_a, broker_a = _make_provider_a()
    provider_b, broker_b = _make_provider_b()
    assert broker_a is not broker_b


def test_provider_b_not_a_broker():
    """
    Task 7.3-12: Provider B's broker is not Provider A's broker.
    """
    provider_a, broker_a = _make_provider_a()
    provider_b, broker_b = _make_provider_b()
    assert broker_b is not broker_a


def test_nsc_id_provider_a_isolation():
    """
    Task 7.3-13: get_nsc_id for TEST-001 returns A-TEST-001 from Provider A.
    """
    provider_a, _ = _make_provider_a()
    assert provider_a.get_nsc_id("TEST-001") == "A-TEST-001"


def test_nsc_id_provider_b_isolation():
    """
    Task 7.3-14: get_nsc_id for TEST-001 returns B-TEST-001 from Provider B.
    """
    provider_b, _ = _make_provider_b()
    assert provider_b.get_nsc_id("TEST-001") == "B-TEST-001"


def test_nsc_id_a_never_returns_b():
    """
    Task 7.3-15: Provider A's get_nsc_id never returns Provider B's nsc_id.
    """
    provider_a, _ = _make_provider_a()
    assert provider_a.get_nsc_id("TEST-001") != "B-TEST-001"


def test_nsc_id_b_never_returns_a():
    """
    Task 7.3-16: Provider B's get_nsc_id never returns Provider A's nsc_id.
    """
    provider_b, _ = _make_provider_b()
    assert provider_b.get_nsc_id("TEST-001") != "A-TEST-001"


def test_nsc_id_cache_independent():
    """
    Task 7.3-17: NSC id caches are independent across providers.
    """
    provider_a, _ = _make_provider_a()
    provider_b, _ = _make_provider_b()

    assert provider_a.get_nsc_id("TEST-001") == "A-TEST-001"
    assert provider_b.get_nsc_id("TEST-001") == "B-TEST-001"


def test_change_mapping_a_does_not_affect_b():
    """
    Task 7.3-18: Change Provider A's mapping from
    TEST-001 → A-TEST-001 to TEST-001 → A-CHANGED-001,
    then verify Provider B still returns B-TEST-001.
    """
    provider_a, broker_a = _make_provider_a()
    provider_b, _ = _make_provider_b()

    initial_a = provider_a.get_nsc_id("TEST-001")
    initial_b = provider_b.get_nsc_id("TEST-001")
    assert initial_a == "A-TEST-001"
    assert initial_b == "B-TEST-001"

    broker_a.session.search.set_response(
        _FakeResponse({
            "isSuccess": True,
            "data": [{"nscId": "A-CHANGED-001", "name": "changed A"}],
        })
    )
    broker_a._instrument_by_nsc = {
        "A-CHANGED-001": _make_broker_instrument(
            "A-CHANGED-001", "TEST-001"
        ),
    }
    provider_a.refresh_cache()

    changed_a = provider_a.get_nsc_id("TEST-001")
    assert changed_a == "A-CHANGED-001", (
        f"Provider A mapping should change to A-CHANGED-001, "
        f"got {changed_a!r}"
    )

    after_a = provider_b.get_nsc_id("TEST-001")
    assert after_a == "B-TEST-001", (
        f"Provider B must remain B-TEST-001 after A mapping "
        f"changed, got {after_a!r}"
    )


def test_change_mapping_b_does_not_affect_a():
    """
    Task 7.3-18 reverse: Change Provider B's mapping from
    TEST-001 → B-TEST-001 to TEST-001 → B-CHANGED-001,
    then verify Provider A still returns A-TEST-001.
    """
    provider_a, _ = _make_provider_a()
    provider_b, _ = _make_provider_b()

    initial_a = provider_a.get_nsc_id("TEST-001")
    initial_b = provider_b.get_nsc_id("TEST-001")
    assert initial_a == "A-TEST-001"
    assert initial_b == "B-TEST-001"

    provider_b._mapping["TEST-001"] = "B-CHANGED-001"
    provider_b.refresh_cache()

    changed_b = provider_b.get_nsc_id("TEST-001")
    assert changed_b == "B-CHANGED-001", (
        f"Provider B mapping should change to B-CHANGED-001, "
        f"got {changed_b!r}"
    )

    after_b = provider_a.get_nsc_id("TEST-001")
    assert after_b == "A-TEST-001", (
        f"Provider A must remain A-TEST-001 after B mapping "
        f"changed, got {after_b!r}"
    )


def main():
    _run("test_instrument_provider_is_abstract", test_instrument_provider_is_abstract)
    _run("test_exact_match_returns_correct_nsc_id", test_exact_match_returns_correct_nsc_id)
    _run("test_multiple_results_second_matches", test_multiple_results_second_matches)
    _run("test_no_exact_match_raises", test_no_exact_match_raises)
    _run("test_tsetmc_missing_raises", test_tsetmc_missing_raises)
    _run("test_missing_symbol_raises", test_missing_symbol_raises)
    _run("test_agah_http_error_wrapped", test_agah_http_error_wrapped)
    _run("test_nsc_id_cache", test_nsc_id_cache)
    _run("test_get_instrument_cache", test_get_instrument_cache)
    _run("test_no_direct_ins_code_to_broker_get_instrument", test_no_direct_ins_code_to_broker_get_instrument)
    _run("test_no_duplicate_tsetmc_lookup_in_get_instrument", test_no_duplicate_tsetmc_lookup_in_get_instrument)

    # ---------------------------------------------------------------------
    # Task 7.3 isolation tests
    # ---------------------------------------------------------------------
    _run("test_provider_a_isolation", test_provider_a_isolation)
    _run("test_provider_b_isolation", test_provider_b_isolation)
    _run("test_provider_a_and_b_are_different", test_provider_a_and_b_are_different)
    _run("test_tse_id_is_same_for_both", test_tse_id_is_same_for_both)
    _run("test_provider_a_never_returns_b_nsc_id", test_provider_a_never_returns_b_nsc_id)
    _run("test_provider_b_never_returns_a_nsc_id", test_provider_b_never_returns_a_nsc_id)
    _run("test_provider_a_cache_isolation", test_provider_a_cache_isolation)
    _run("test_provider_b_cache_isolation", test_provider_b_cache_isolation)
    _run("test_provider_a_broker_identity", test_provider_a_broker_identity)
    _run("test_provider_b_broker_identity", test_provider_b_broker_identity)
    _run("test_provider_a_not_b_broker", test_provider_a_not_b_broker)
    _run("test_provider_b_not_a_broker", test_provider_b_not_a_broker)
    _run("test_nsc_id_provider_a_isolation", test_nsc_id_provider_a_isolation)
    _run("test_nsc_id_provider_b_isolation", test_nsc_id_provider_b_isolation)
    _run("test_nsc_id_a_never_returns_b", test_nsc_id_a_never_returns_b)
    _run("test_nsc_id_b_never_returns_a", test_nsc_id_b_never_returns_a)
    _run("test_nsc_id_cache_independent", test_nsc_id_cache_independent)
    _run("test_change_mapping_a_does_not_affect_b",
         test_change_mapping_a_does_not_affect_b)
    _run("test_change_mapping_b_does_not_affect_a",
         test_change_mapping_b_does_not_affect_a)


if __name__ == "__main__":
    main()
