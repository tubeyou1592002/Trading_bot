"""Offline tests for trace destination, sanitization, and UI health display."""

import json
import os
from importlib import reload

import pytest
from PySide6.QtWidgets import QApplication

from ui import manual_live_trace


def _logger(monkeypatch, directory):
    monkeypatch.setenv("TRADING_BOT_TRACE_DIR", str(directory))
    return reload(manual_live_trace)


def test_default_relative_and_absolute_paths_are_stable_across_cwd(tmp_path, monkeypatch):
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "."))
    monkeypatch.delenv("TRADING_BOT_TRACE_DIR", raising=False)
    logger = reload(manual_live_trace)
    assert logger.trace_path() == os.path.join(root, "traces", "manual_live_trace.jsonl")
    original = os.getcwd()
    try:
        os.chdir(tmp_path)
        assert logger.trace_path() == os.path.join(root, "traces", "manual_live_trace.jsonl")
    finally:
        os.chdir(original)

    logger = _logger(monkeypatch, "relative-traces")
    expected = os.path.join(root, "relative-traces", "manual_live_trace.jsonl")
    original = os.getcwd()
    try:
        os.chdir(tmp_path)
        assert logger.trace_path() == expected
    finally:
        os.chdir(original)

    absolute = tmp_path / "absolute-traces"
    logger = _logger(monkeypatch, absolute)
    expected = str(absolute / "manual_live_trace.jsonl")
    original = os.getcwd()
    try:
        os.chdir(root)
        assert logger.trace_path() == expected
    finally:
        os.chdir(original)


def test_sanitizer_accepts_only_typed_metadata_and_fixed_enums():
    clean = manual_live_trace._sanitize_extra({
        "classification": "UNKNOWN", "ui_result": "SUCCESS", "http_status": 503,
    })
    assert clean == {"classification": "UNKNOWN", "ui_result": "SUCCESS", "http_status": 503}
    for extra in (
        {"classification": "secret"}, {"ui_result": "LIVE"},
        {"http_status": True}, {"http_status": 700},
        {"classification": {"token": "secret"}},
        {"note": "secret"}, {"stage_note": "secret"},
        {"classification": "UNKNOWN", "payload": "secret"},
    ):
        assert manual_live_trace._sanitize_extra(extra) is None


def test_logger_io_failure_and_success_recovery(tmp_path, monkeypatch):
    logger = _logger(monkeypatch, tmp_path / "trace")
    assert logger.diagnostic_status()["writable"] is None
    target = tmp_path / "trace" / "manual_live_trace.jsonl"
    original_open = type(target).open
    monkeypatch.setattr(type(target), "open", lambda *_a, **_k: (_ for _ in ()).throw(OSError("secret")))
    logger.log_event("trace-test", "probe")
    assert logger.last_error()["code"] == "OPEN_FAILED"
    assert logger.diagnostic_status()["writable"] is False
    monkeypatch.setattr(type(target), "open", original_open)
    logger.log_event("trace-test", "probe", extra={"http_status": 200, "note": "secret"})
    assert logger.last_error()["code"] is None
    assert logger.diagnostic_status()["writable"] is True
    record = json.loads(target.read_text(encoding="utf-8"))
    assert "extra" not in record


def test_logger_write_failure_is_reported_and_recovers(tmp_path, monkeypatch):
    logger = _logger(monkeypatch, tmp_path / "trace")
    target = logger._TRACE_FILE
    real_open = type(target).open

    class FailingWrite:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def write(self, _text):
            raise OSError("controlled write failure")

    monkeypatch.setattr(type(target), "open", lambda *_a, **_k: FailingWrite())
    logger.log_event("trace-test", "probe")
    assert logger.last_error()["code"] == "WRITE_FAILED"
    assert logger.diagnostic_status()["writable"] is False
    monkeypatch.setattr(type(target), "open", real_open)
    logger.log_event("trace-test", "probe")
    assert logger.last_error()["code"] is None
    assert logger.diagnostic_status()["writable"] is True


def test_logger_mkdir_and_rotation_failures_recover(tmp_path, monkeypatch):
    logger = _logger(monkeypatch, tmp_path / "trace")
    real_mkdir = type(logger._TRACE_DIR).mkdir
    monkeypatch.setattr(type(logger._TRACE_DIR), "mkdir", lambda *_a, **_k: (_ for _ in ()).throw(OSError()))
    logger.log_event("trace-test", "probe")
    assert logger.last_error()["code"] == "DIR_CREATE_FAILED"
    monkeypatch.setattr(type(logger._TRACE_DIR), "mkdir", real_mkdir)
    logger.log_event("trace-test", "probe")
    logger._TRACE_FILE.write_text("x", encoding="utf-8")
    real_rename = type(logger._TRACE_FILE).rename
    monkeypatch.setattr(type(logger._TRACE_FILE), "rename", lambda *_a, **_k: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(logger, "_MAX_BYTES", 0)
    logger.log_event("trace-test", "probe")
    assert logger.last_error()["code"] == "ROTATION_FAILED"
    monkeypatch.setattr(type(logger._TRACE_FILE), "rename", real_rename)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_diagnostic_ui_refresh_shows_path_and_nonblocking_error(qapp, monkeypatch):
    from ui.order_configuration_page import OrderConfigurationPage
    from ui import account_store
    from core.order_queue import OrderQueue

    page = OrderConfigurationPage(account_store.AccountStore(), order_queue=OrderQueue())
    try:
        status = {"path": "C:/offline/manual_live_trace.jsonl", "error": {"code": None}, "writable": None}
        monkeypatch.setattr(manual_live_trace, "diagnostic_status", lambda: status)
        page._refresh_diagnostic_display()
        assert "C:/offline/manual_live_trace.jsonl" in page.trace_logger_status_label.text()
        assert "هنوز نوشتن موفقی" in page.trace_logger_status_label.text()
        status = {"path": "C:/offline/manual_live_trace.jsonl", "error": {"code": "WRITE_FAILED"}, "writable": False}
        page._refresh_diagnostic_display()
        assert "ثبت گزارش با خطا" in page.trace_logger_status_label.text()
        assert not page.trace_logger_status_label.isHidden()
    finally:
        page.close()


def test_logger_failure_does_not_change_fake_order_result_or_cleanup(monkeypatch, tmp_path):
    from test_manual_live_trace_instrumentation import _setup, _Response

    class IndependentTransport:
        def __init__(self):
            self.posts = 0
            self.closed = 0
            self.require_trace_event = False
            self.headers = {}

        def update_headers(self, headers):
            self.headers.update(headers)

        def post(self, *_args, **_kwargs):
            self.posts += 1
            return _Response({"isSuccess": True})

        def close(self):
            self.closed += 1

        def __getattr__(self, name):
            if name == "update":
                return self.update_headers
            raise AttributeError(name)

    def run_with_logger(trace_directory, fail_write):
        logger = _logger(monkeypatch, trace_directory)
        target = logger._TRACE_FILE
        target.parent.mkdir(parents=True, exist_ok=True)
        transport = IndependentTransport()
        original_open = type(target).open

        if fail_write:
            class FailingWrite:
                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def write(self, _text):
                    raise OSError("controlled write failure")

            def controlled_open(path, *args, **kwargs):
                if path == target:
                    return FailingWrite()
                return original_open(path, *args, **kwargs)

            monkeypatch.setattr(type(target), "open", controlled_open)

        transport.require_trace_event = False
        result, _broker, setup_transport, _events = _setup(
            monkeypatch,
            response=_Response({"isSuccess": True}),
            log_callback=logger.log_event,
            transport_override=transport,
        )
        assert setup_transport is transport
        assert transport.posts == 1
        assert transport.closed == 1
        return result, logger, transport

    healthy, healthy_logger, healthy_transport = run_with_logger(
        tmp_path / "healthy", fail_write=False
    )
    healthy_error = healthy_logger.last_error()["code"]
    monkeypatch.undo()
    failed, failed_logger, failed_transport = run_with_logger(
        tmp_path / "failed", fail_write=True
    )

    assert healthy.mode == failed.mode == "LIVE"
    assert healthy_transport.posts == failed_transport.posts == 1
    assert healthy_transport.closed == failed_transport.closed == 1
    assert healthy_error is None
    assert failed_logger.last_error()["code"] == "WRITE_FAILED"


def test_diagnostic_status_failure_does_not_affect_fake_order(monkeypatch, tmp_path):
    from ui.order_configuration_page import OrderConfigurationPage
    from ui.account_store import AccountStore
    from core.order_queue import OrderQueue

    logger = _logger(monkeypatch, tmp_path / "trace")
    monkeypatch.setattr(logger, "diagnostic_status", lambda: (_ for _ in ()).throw(OSError("status secret")))
    app = QApplication.instance() or QApplication([])
    page = OrderConfigurationPage(AccountStore(), order_queue=OrderQueue())
    page._refresh_trace_logger_status()
    assert "وضعیت ثبت گزارش در دسترس نیست" in page.trace_logger_status_label.text()
    page.close()
