import pytest
from PySide6.QtWidgets import QApplication

from models.instrument import Instrument
from ui.account_store import AccountStore
from ui.order_config_state import OrderConfiguration
from ui.order_configuration_page import OrderConfigurationPage
from ui.session_manager import SessionManager
from ui import manual_live_trace

ACCOUNT = "mapping-test-account"
BROKER = "آگاه"


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


class Provider:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def get_nsc_id(self, ins_code):
        self.calls.append(ins_code)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome

    def diagnostic_mapping(self, ins_code):
        self.calls.append(ins_code)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def make_page(qapp, provider=None, *, logged_in=True):
    store = AccountStore(repository=False)
    store.add(ACCOUNT, BROKER, "Test account")
    store.set_active(ACCOUNT)
    sessions = SessionManager()
    sessions.register(ACCOUNT, BROKER)
    if logged_in:
        sessions.begin_login(ACCOUNT)
        sessions.mark_logged_in(ACCOUNT, "private-token")
    config = OrderConfiguration()
    config.select_instrument(Instrument("نماد", "نام", "123456"))
    page = OrderConfigurationPage(store, config=config)
    page.set_session_manager(sessions)
    if provider is not None:
        page.set_order_identity_factory(lambda account, broker: provider)
    return page, provider


def finish(page):
    worker = page._mapping_diagnostic_worker
    assert worker is not None
    assert worker.wait(5000)
    QApplication.processEvents()


def test_mapping_diagnostic_passes_selected_ins_code_and_shows_copyable_match(qapp):
    provider = Provider({
        "nsc_id": "agah-987",
        "candidates": [{"nscId": "agah-987", "tseId": "123456", "name": "نام کاندیدا", "exact_match": True}],
    })
    page, _ = make_page(qapp, provider)
    page._run_agah_mapping_diagnostic()
    finish(page)
    result = page.agah_mapping_result.toPlainText()
    assert provider.calls == ["123456"]
    assert "Symbol: نماد" in result
    assert "ins_code: 123456" in result
    assert "nscId: agah-987" in result
    assert "Candidate 1 tseId: 123456" in result
    assert "Candidate 1 name: نام کاندیدا" in result
    assert "Candidate 1 exact match: yes" in result
    assert page.agah_mapping_result.isReadOnly()
    assert not hasattr(page, "place_order")
    page.close()


def test_mapping_diagnostic_requires_authenticated_session(qapp):
    page, provider = make_page(qapp, Provider("unused"), logged_in=False)
    page._run_agah_mapping_diagnostic()
    assert "No authenticated session" in page.agah_mapping_result.toPlainText()
    assert provider.calls == []
    page.close()


def test_entering_page_before_account_session_is_ready_then_account_activates(qapp):
    store = AccountStore(repository=False)
    store.add(ACCOUNT, BROKER, "Test account")
    sessions = SessionManager()
    sessions.register(ACCOUNT, BROKER)
    page = OrderConfigurationPage(store, config=OrderConfiguration())
    page.set_session_manager(sessions)
    from models.instrument import Instrument
    page.config.select_instrument(Instrument("نماد", "نام", "123456"))
    page.refresh_active_account()
    assert page._order_nsc_id is None
    store.set_active(ACCOUNT)
    sessions.begin_login(ACCOUNT)
    sessions.mark_logged_in(ACCOUNT, "offline-test-token")
    page.refresh_active_account()
    assert page._order_identity_thread is not None
    page.close()


@pytest.mark.parametrize(("error", "expected"), [
    (RuntimeError("HTTP 401 unauthorized"), "Access not accepted"),
    (LookupError("هیچ کاندیدای Agah نبود"), "No matching Agah instrument"),
])
def test_mapping_diagnostic_safe_failure_outcomes(qapp, error, expected):
    provider = Provider(error)
    page, _ = make_page(qapp, provider)
    page._run_agah_mapping_diagnostic()
    finish(page)
    text = page.agah_mapping_result.toPlainText()
    assert expected in text
    assert str(error) not in text
    assert provider.calls == ["123456"]
    page.close()


def test_mapping_diagnostic_none_result_is_no_match(qapp):
    provider = Provider({
        "nsc_id": None,
        "candidates": [{"nscId": "other", "tseId": "different", "name": "Other", "exact_match": False}],
    })
    page, _ = make_page(qapp, provider)
    page._run_agah_mapping_diagnostic()
    finish(page)
    text = page.agah_mapping_result.toPlainText()
    assert "No matching Agah instrument" in text
    assert "Candidate 1 exact match: no" in text
    assert "Outcome: exact match" not in text
    page.close()


def test_mapping_diagnostic_401_is_not_reported_as_no_match(qapp):
    provider = Provider({"nsc_id": None, "candidates": [], "search_status": 401,
                         "source": "lookup", "candidate_count": 0})
    page, _ = make_page(qapp, provider)
    page._run_agah_mapping_diagnostic()
    finish(page)
    text = page.agah_mapping_result.toPlainText()
    assert "Access not accepted" in text
    assert "No matching Agah instrument" not in text
    page.close()


def test_mapping_diagnostic_connection_error_is_distinct(qapp):
    provider = Provider({"nsc_id": None, "candidates": [], "connection_error": True})
    page, _ = make_page(qapp, provider)
    page._run_agah_mapping_diagnostic()
    finish(page)
    assert "Connection error" in page.agah_mapping_result.toPlainText()
    assert "No matching Agah instrument" not in page.agah_mapping_result.toPlainText()
    page.close()


def test_mapping_diagnostic_stale_symbol_response_is_discarded(qapp):
    page, _ = make_page(qapp, Provider({"nsc_id": "nsc", "candidates": []}))
    identity = (ACCOUNT, BROKER, "123456")
    page._mapping_diagnostic_identity = identity
    page._mapping_diagnostic_symbol = "نماد"
    from models.instrument import Instrument
    page.config.select_instrument(Instrument("جديد", "نام جدید", "654321"))
    page._on_mapping_diagnostic_succeeded(identity, "123456", {
        "nsc_id": "nsc", "candidates": [], "source": "lookup"
    })
    assert not page.agah_mapping_result.isVisible()
    page.close()


def test_account_can_become_ready_after_page_entry(qapp):
    store = AccountStore(repository=False)
    store.add(ACCOUNT, BROKER, "Test account")
    sessions = SessionManager()
    sessions.register(ACCOUNT, BROKER)
    page = OrderConfigurationPage(store, config=OrderConfiguration())
    page.set_session_manager(sessions)
    page.set_order_identity_factory(lambda *_: Provider("agah-id"))
    from models.instrument import Instrument
    instrument = Instrument("نماد", "نام", "123456")
    page.config.select_instrument(instrument)
    assert page._order_nsc_id is None
    store.set_active(ACCOUNT)
    sessions.begin_login(ACCOUNT)
    sessions.mark_logged_in(ACCOUNT, "offline-test-token")
    page.refresh_active_account()
    page.wait_for_order_identity_workers()
    qapp.processEvents()
    assert page._order_nsc_id == "agah-id"
    page.close()


def test_calculator_readiness_reports_specific_missing_requirement(qapp):
    store = AccountStore(repository=False)
    page = OrderConfigurationPage(store, config=OrderConfiguration())
    with pytest.raises(ValueError, match="حساب فعال انتخاب نشده"):
        page._buy_preview_snapshot()
    page.close()


def test_diagnostic_logger_failure_does_not_change_lookup_result(qapp, monkeypatch):
    provider = Provider({"nsc_id": "agah-987", "candidates": []})
    page, _ = make_page(qapp, provider)
    monkeypatch.setattr(manual_live_trace, "log_event", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk")))
    page._run_agah_mapping_diagnostic()
    finish(page)
    assert "exact match" in page.agah_mapping_result.toPlainText()
    assert provider.calls == ["123456"]
    page.close()


def test_mapping_success_after_401_is_a_new_attempt_and_applies(qapp):
    provider = Provider(RuntimeError("HTTP 401 unauthorized"))
    page, _ = make_page(qapp, provider)
    page._run_agah_mapping_diagnostic()
    finish(page)
    assert "Access not accepted" in page.agah_mapping_result.toPlainText()
    provider.outcome = {"nsc_id": "agah-987", "candidates": [], "search_status": 200}
    page._run_agah_mapping_diagnostic()
    finish(page)
    assert "Outcome: exact match" in page.agah_mapping_result.toPlainText()
    assert provider.calls == ["123456", "123456"]
    page.close()


def test_order_identity_out_of_order_responses_keep_source_attempt_and_reject_old(qapp, monkeypatch):
    from ui import order_configuration_page as page_module
    page, _ = make_page(qapp)
    current_identity = (ACCOUNT, BROKER, "123456")
    page._order_identity_scope = current_identity
    page._order_identity_scope = current_identity
    page._order_identity_request_id = "req-new"
    page._order_identity_instrument = "123456"
    page._order_identity_broker = BROKER
    page._order_identity_account = ACCOUNT
    logged = []
    monkeypatch.setattr(page, "_log_identity_diagnostic",
                        lambda request_id, stage, identity, query, **kw: logged.append((request_id, stage, query, kw)))
    old = page_module._OrderIdentityWorker("123456", lambda: None, identity=current_identity, request_id="req-old")
    old.symbol = "source-old"
    new = page_module._OrderIdentityWorker("123456", lambda: None, identity=current_identity, request_id="req-new")
    new.symbol = "source-new"
    page._order_identity_worker = new

    page._on_order_identity_succeeded(current_identity, "123456", "old-nsc", "req-old", "source-old")
    assert page._order_nsc_id is None
    page._on_order_identity_succeeded(current_identity, "123456", "new-nsc", "req-new", "source-new")
    assert page._order_nsc_id == "new-nsc"
    assert [(rid, stage, symbol) for rid, stage, symbol, _ in logged[:2]] == [
        ("req-old", "lookup_response", "source-old"),
        ("req-old", "ui_apply", "source-old"),
    ]
    assert all(rid == "req-new" and symbol == "source-new" for rid, stage, symbol, _ in logged[2:4])
    page.close()


def test_same_account_symbol_starts_distinct_identity_attempts(qapp):
    page, provider = make_page(qapp, Provider("same-nsc"))
    instrument = page.config.selected_instrument
    page._start_order_identity_resolution(instrument)
    first = page._order_identity_worker
    first_id = first.request_id
    page._start_order_identity_resolution(instrument)
    second = page._order_identity_worker
    assert second is not first
    assert second.request_id != first_id
    assert second.identity == first.identity
    assert second.ins_code == first.ins_code
    first.wait(3000)
    second.wait(3000)
    qapp.processEvents()
    assert provider.calls == ["123456", "123456"]
    page.close()


def test_automatic_identity_401_callback_is_safe_and_uses_source_request(qapp, monkeypatch):
    from ui import order_configuration_page as page_module
    class Response:
        status_code = 401
    from requests import HTTPError
    error = HTTPError("do not expose this")
    error.response = Response()
    provider = Provider(error)
    page, _ = make_page(qapp, provider)
    page.set_order_identity_factory(lambda *_: provider)
    page._start_order_identity_resolution(page.config.selected_instrument)
    worker = page._order_identity_worker
    logged = []
    monkeypatch.setattr(page, "_log_identity_diagnostic",
                        lambda *args, **kwargs: logged.append((args, kwargs)))
    assert worker.wait(5000)
    qapp.processEvents()
    identity = (ACCOUNT, BROKER, "123456")
    assert worker.http_status == 401
    assert worker.error_code == "LOOKUP_401"
    assert "عدم پذیرش دسترسی" in page.fee_label.text()
    assert any(args[0] == worker.request_id and args[3] == "نماد" for args, _ in logged)
    page.close()


def test_identity_worker_http_401_metadata_reaches_callback_without_raw_exception(qapp, monkeypatch):
    from requests import HTTPError
    class Response:
        status_code = 401

    error = HTTPError("secret/raw exception detail")
    error.response = Response()
    provider = Provider(error)
    page, _ = make_page(qapp, provider)
    identity = (ACCOUNT, BROKER, "123456")
    page.set_order_identity_factory(lambda *_: provider)
    page._start_order_identity_resolution(page.config.selected_instrument)
    worker = page._order_identity_worker
    logged = []
    monkeypatch.setattr(page, "_log_identity_diagnostic",
                        lambda request_id, stage, identity, query, **kw:
                        logged.append((request_id, stage, query, kw)))
    assert worker.wait(5000)
    qapp.processEvents()
    assert page.fee_label.text() == "عدم پذیرش دسترسی درخواست دریافت شناسهٔ آگاه (HTTP 401)"
    assert worker.http_status == 401 and worker.error_code == "LOOKUP_401"
    assert any(entry[3].get("reason_code") == "LOOKUP_401"
               and entry[3].get("http_status") == 401 for entry in logged)
    assert all("secret/raw exception detail" not in repr(entry) for entry in logged)
    page.close()


def test_late_identity_failure_keeps_origin_metadata_and_is_discarded(qapp, monkeypatch):
    from requests import HTTPError
    from ui import order_configuration_page as page_module

    class Response:
        status_code = 401

    error = HTTPError("old private error")
    error.response = Response()
    identity = (ACCOUNT, BROKER, "123456")
    page, _ = make_page(qapp, Provider(error))
    page._order_identity_scope = identity
    page._order_identity_request_id = "req-current"
    page._order_identity_instrument = "123456"
    page._order_identity_broker = BROKER
    page._order_identity_account = ACCOUNT
    logs = []
    monkeypatch.setattr(page, "_log_identity_diagnostic",
                        lambda request_id, stage, identity, query, **kw:
                        logs.append((request_id, stage, query, kw)))

    # Use a local provider with a deterministic HTTPError; no transport is invoked.
    class FailingProvider:
        def get_nsc_id(self, _):
            raise error
    old = page_module._OrderIdentityWorker(
        "123456", lambda: FailingProvider(), identity=identity, request_id="req-old"
    )
    old.symbol = "old-source-symbol"
    old.identity_failed.connect(page._on_order_identity_failed)
    page._order_identity_worker = page_module._OrderIdentityWorker(
        "123456", lambda: None, identity=identity, request_id="req-current"
    )
    page._order_identity_worker.symbol = "current-symbol"
    page.set_order_identity_factory(lambda *_: Provider(error))
    old.start()
    assert old.wait(5000)
    qapp.processEvents()

    response = next(entry for entry in logs if entry[1] == "lookup_response")
    assert response[0:3] == ("req-old", "lookup_response", "old-source-symbol")
    assert response[3]["reason_code"] == "LOOKUP_401"
    assert response[3]["source"] == "lookup" and response[3]["http_status"] == 401
    assert any(entry[0] == "req-old" and entry[1] == "ui_apply"
               and entry[3]["reason_code"] == "LOOKUP_STALE_RESPONSE" for entry in logs)
    assert page._order_nsc_id is None
    page.close()


@pytest.mark.parametrize("stage,reason,status", [
    ("instruments_all", "SEARCH_HTTP_ERROR", 401),
    ("instruments", "DETAIL_HTTP_ERROR", 401),
    ("instruments_all", "SEARCH_FAILED", None),
    ("instruments", "DETAIL_FAILED", None),
])
def test_provider_failure_reaches_jsonl_offline(qapp, monkeypatch, tmp_path, stage, reason, status):
    import json
    from unittest.mock import MagicMock
    from requests import HTTPError
    from brokers.agaah.instrument_provider import AgaahInstrumentProvider

    trace_file = tmp_path / "manual_live_trace.jsonl"
    monkeypatch.setattr(manual_live_trace, "_TRACE_DIR", tmp_path)
    monkeypatch.setattr(manual_live_trace, "_TRACE_FILE", trace_file)
    error = HTTPError("secret raw exception and header") if status else RuntimeError("secret raw exception and header")
    if status:
        error.response = type("Response", (), {"status_code": status})()
    broker = MagicMock()
    if stage == "instruments_all":
        broker._authed_get_with_recovery.side_effect = error
    else:
        broker._authed_get_with_recovery.return_value.json.return_value = {"data": [{"nscId": "candidate"}]}
        broker.get_instrument.side_effect = error
    tsetmc = MagicMock()
    tsetmc.get_info.return_value = Instrument("نماد", "نام", "123456")
    provider = AgaahInstrumentProvider(broker, tsetmc)
    page, _ = make_page(qapp, provider)
    page._start_order_identity_resolution(page.config.selected_instrument)
    worker = page._order_identity_worker
    assert worker.wait(5000)
    qapp.processEvents()

    text = trace_file.read_text(encoding="utf-8")
    records = [json.loads(line) for line in text.splitlines()]
    matching = [record for record in records if record.get("reason_code") == reason]
    assert len(matching) == 1
    record = matching[0]
    assert record["trace_id"] == worker.request_id
    assert record.get("extra", {}).get("request_id", worker.request_id) == worker.request_id
    assert record["extra"]["provider_stage"] == stage
    assert record["extra"].get("http_status") == status
    assert "secret raw exception" not in text
    assert "header" not in text.lower()
    assert broker._authed_get_with_recovery.call_count == 1
    assert broker.get_instrument.call_count == (stage == "instruments")


@pytest.mark.parametrize("case,stage,reason", [
    ("tsetmc", "tsetmc_info", "TSETMC_INFO_FAILED"),
    ("json", "instruments_all", "SEARCH_JSON_INVALID"),
    ("structure", "instruments_all", "SEARCH_RESPONSE_INVALID"),
    ("empty", "instruments_all", "SEARCH_NO_CANDIDATES"),
    ("invalid_candidates", "instruments_all", "SEARCH_CANDIDATES_INVALID"),
    ("api_failure", "instruments_all", "SEARCH_API_FAILED"),
    ("no_match", "instruments", "DETAIL_NO_MATCH"),
])
def test_unclassified_lookup_failures_reach_jsonl_offline(
    qapp, monkeypatch, tmp_path, case, stage, reason
):
    import json
    from unittest.mock import MagicMock
    from brokers.agaah.instrument_provider import AgaahInstrumentProvider

    trace_file = tmp_path / "manual_live_trace.jsonl"
    monkeypatch.setattr(manual_live_trace, "_TRACE_DIR", tmp_path)
    monkeypatch.setattr(manual_live_trace, "_TRACE_FILE", trace_file)
    broker = MagicMock()
    tsetmc = MagicMock()
    if case == "tsetmc":
        tsetmc.get_info.side_effect = RuntimeError("private TSETMC payload")
    else:
        tsetmc.get_info.return_value = Instrument("نماد", "نام", "123456")
        response = broker._authed_get_with_recovery.return_value
        response.status_code = 200
        if case == "json":
            response.json.side_effect = ValueError("private response body")
        elif case == "structure":
            response.json.return_value = {"data": {"secret": "private"}}
        elif case == "empty":
            response.json.return_value = {"data": []}
        elif case == "invalid_candidates":
            response.json.return_value = {"data": [{"nscId": 123}, {"nscId": " "}]}
        elif case == "api_failure":
            response.json.return_value = {"isSuccess": False, "message": "private api message", "data": []}
        else:
            response.json.return_value = {"data": [{"nscId": "candidate"}]}
            broker.get_instrument.return_value = type("BrokerInstrumentStub", (), {"tse_id": "different"})()

    provider = AgaahInstrumentProvider(broker, tsetmc)
    page, _ = make_page(qapp, provider)
    page._start_order_identity_resolution(page.config.selected_instrument)
    worker = page._order_identity_worker
    assert worker.wait(5000)
    qapp.processEvents()

    text = trace_file.read_text(encoding="utf-8")
    records = [json.loads(line) for line in text.splitlines()]
    matching = [record for record in records if record.get("reason_code") == reason]
    assert len(matching) == 1
    record = matching[0]
    assert record["trace_id"] == worker.request_id
    assert record["extra"]["request_id"] == worker.request_id
    assert record["extra"]["provider_stage"] == stage
    expected_api_class = {
        "tsetmc": None, "json": "INVALID_JSON", "structure": "INVALID_STRUCTURE",
        "empty": "SUCCESS", "invalid_candidates": "SUCCESS", "api_failure": "API_FAILURE",
        "no_match": "SUCCESS",
    }[case]
    if expected_api_class is not None:
        assert record["extra"]["api_classification"] == expected_api_class
    if case in {"empty", "invalid_candidates", "api_failure", "no_match"}:
        expected_total = 2 if case == "invalid_candidates" else 1 if case == "no_match" else 0
        assert record["extra"]["total_candidates"] == expected_total
    if case in {"empty", "invalid_candidates", "api_failure", "no_match"}:
        assert record["extra"]["valid_nsc_id_candidates"] == (1 if case == "no_match" else 0)
    if case not in {"tsetmc", "json", "structure"}:
        assert record["extra"]["normalization"] == "symbol_resolver_unchanged"
    assert "private" not in text
    assert broker._authed_get_with_recovery.call_count == (case != "tsetmc")
    assert broker.get_instrument.call_count == (case == "no_match")
    page.close()


@pytest.mark.parametrize(("query", "expected"), [
    ("شپلي", "شپلی"),
    ("شپلی", "شپلی"),
    ("شپديس", "شپدیس"),
    ("شپدیس", "شپدیس"),
])
def test_agah_lookup_uses_project_symbol_normalization_offline(qapp, query, expected):
    from unittest.mock import MagicMock
    from brokers.agaah.instrument_provider import AgaahInstrumentProvider
    from market.symbol_resolver import SymbolResolver

    assert SymbolResolver.normalize(query) == expected
    broker = MagicMock()
    broker._authed_get_with_recovery.return_value.status_code = 200
    broker._authed_get_with_recovery.return_value.json.return_value = {"data": []}
    tsetmc = MagicMock()
    tsetmc.get_info.return_value = Instrument(query, "نام", "123456")
    provider = AgaahInstrumentProvider(broker, tsetmc)
    from brokers.base import InstrumentLookupError
    with pytest.raises(InstrumentLookupError):
        provider.get_nsc_id("123456")
    assert broker._authed_get_with_recovery.call_args.kwargs["params"]["query"] == expected


def test_agah_lookup_still_requires_exact_tse_id_match_offline():
    from unittest.mock import MagicMock
    from brokers.agaah.instrument_provider import AgaahInstrumentProvider
    from brokers.base import InstrumentLookupError

    broker = MagicMock()
    broker._authed_get_with_recovery.return_value.status_code = 200
    broker._authed_get_with_recovery.return_value.json.return_value = {
        "isSuccess": True, "data": [{"nscId": "candidate"}]
    }
    broker.get_instrument.return_value = type("BrokerInstrumentStub", (), {"tse_id": "other"})()
    provider = AgaahInstrumentProvider(
        broker, MagicMock(get_info=MagicMock(return_value=Instrument("شپلی", "نام", "123456")))
    )
    with pytest.raises(InstrumentLookupError) as error:
        provider.get_nsc_id("123456")
    assert error.value.reason_code == "DETAIL_NO_MATCH"
