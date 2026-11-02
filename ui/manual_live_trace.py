"""Safe local trace logging for manual Live submission path."""

import json
import os
import threading
import time
import uuid
from pathlib import Path

_TRACE_LOCK = threading.Lock()
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CONFIGURED_TRACE_DIR = os.environ.get("TRADING_BOT_TRACE_DIR")
_TRACE_DIR = (
    Path(_CONFIGURED_TRACE_DIR).expanduser()
    if _CONFIGURED_TRACE_DIR and Path(_CONFIGURED_TRACE_DIR).is_absolute()
    else (_PROJECT_ROOT / _CONFIGURED_TRACE_DIR).expanduser()
    if _CONFIGURED_TRACE_DIR
    else _PROJECT_ROOT / "traces"
).resolve()
_TRACE_FILE = _TRACE_DIR / "manual_live_trace.jsonl"
_MAX_BYTES = 5 * 1024 * 1024

_ALLOWED_CLASSIFICATIONS = {"ACCEPTED", "REJECTED", "UNKNOWN", "BLOCKED", "ERROR", "LIVE", "OK", "ALLOWED", "UNAUTHORIZED", "NO_MATCH", "CONNECTION_ERROR", "STALE", "CACHE", "LOOKUP", "READY"}
_ALLOWED_UI_RESULTS = {"SUCCESS", "BLOCKED", "NOT_SENT", "ERROR", "UNKNOWN"}
_HTTP_STATUSES = range(100, 600)
_DIAGNOSTIC_FIELDS = {
    "request_id", "symbol_id", "query", "account_alias", "session_generation",
    "connection_generation", "account_ready", "session_ready", "source",
    "candidate_count", "account_changed", "symbol_changed", "turn_changed",
    "logger_path", "logger_writable", "provider_stage", "api_classification",
    "total_candidates", "valid_nsc_id_candidates", "normalization",
}
_DIAGNOSTIC_STAGES = {
    "lookup_dispatch", "lookup_response", "ui_apply", "calculator_readiness",
    "account_snapshot", "session_snapshot",
}
_DIAGNOSTIC_REASONS = {
    "LOOKUP_401", "LOOKUP_NO_MATCH", "LOOKUP_CONNECTION_ERROR", "LOOKUP_FAILED",
    "LOOKUP_STALE_RESPONSE", "LOOKUP_APPLIED", "TSETMC_INFO_FAILED", "TSETMC_INFO_INVALID",
    "SEARCH_JSON_INVALID", "SEARCH_RESPONSE_INVALID", "SEARCH_NO_CANDIDATES",
    "SEARCH_API_FAILED", "SEARCH_CANDIDATES_INVALID", "DETAIL_NO_MATCH",
    "SEARCH_HTTP_ERROR", "SEARCH_FAILED", "DETAIL_HTTP_ERROR", "DETAIL_FAILED",
    "ACCOUNT_MISSING", "SESSION_NOT_READY",
    "SYMBOL_MISSING", "INSTRUMENT_ID_MISSING", "BROKER_MISMATCH", "IDENTITY_PENDING",
    "IDENTITY_READY", "SIDE_NOT_BUY", "PRICE_INVALID", "QUANTITY_INVALID",
    "LOGGER_UNAVAILABLE", "RESPONSE_STATUS_ERROR", "RESPONSE_INVALID",
}

_LAST_ERROR = {"code": None, "path": None}
_HAS_WRITTEN = False


def _ensure_dir():
    global _LAST_ERROR
    try:
        _TRACE_DIR.mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        _LAST_ERROR = {"code": "DIR_CREATE_FAILED", "path": str(_TRACE_FILE)}
        return False


def new_trace_id():
    return f"mlt-{uuid.uuid4().hex}"


def trace_path():
    return str(_TRACE_FILE)


def last_error():
    return dict(_LAST_ERROR)


def _record_error(code):
    global _LAST_ERROR
    _LAST_ERROR = {"code": code, "path": str(_TRACE_FILE)}


def _clear_error():
    global _LAST_ERROR
    _LAST_ERROR = {"code": None, "path": None}


def _sanitize_extra(extra):
    if not isinstance(extra, dict):
        return None
    out = {}
    if set(extra) - ({"http_status", "classification", "ui_result"} | _DIAGNOSTIC_FIELDS):
        return None
    for key, value in extra.items():
        if key == "http_status" and type(value) is int and value in _HTTP_STATUSES:
            out[key] = value
        elif key == "classification" and type(value) is str and value in _ALLOWED_CLASSIFICATIONS:
            out[key] = value
        elif key == "ui_result" and type(value) is str and value in _ALLOWED_UI_RESULTS:
            out[key] = value
        elif key in {"request_id", "symbol_id", "query", "account_alias", "logger_path"} and type(value) is str and len(value) <= 160 and not any(ord(char) < 32 for char in value):
            out[key] = value
        elif key in {"session_generation", "connection_generation", "candidate_count", "http_status"} and type(value) is int and value >= 0 and (key != "http_status" or value in _HTTP_STATUSES):
            out[key] = value
        elif key in {"account_ready", "session_ready", "account_changed", "symbol_changed", "turn_changed", "logger_writable"} and type(value) is bool:
            out[key] = value
        elif key == "source" and value in {"cache", "lookup"}:
            out[key] = value
        elif key == "provider_stage" and value in {"tsetmc_info", "instruments_all", "instruments"}:
            out[key] = value
        elif key == "api_classification" and value in {"SUCCESS", "API_FAILURE", "INVALID_JSON", "INVALID_STRUCTURE", "HTTP_ERROR", "REQUEST_FAILED"}:
            out[key] = value
        elif key == "normalization" and value in {"symbol_resolver_unchanged", "symbol_resolver_changed", "symbol_resolver", "none"}:
            out[key] = value
        elif key in {"total_candidates", "valid_nsc_id_candidates"} and type(value) is int and value >= 0:
            out[key] = value
        else:
            return None
    return out if out else None


def log_event(trace_id, stage, order_index=None, reason_code=None, extra=None):
    global _HAS_WRITTEN
    try:
        record = {
            "ts": time.time(),
            "trace_id": trace_id,
            "stage": stage,
        }
        if order_index is not None:
            record["order_index"] = order_index
        if reason_code is not None:
            record["reason_code"] = reason_code
        sanitized = _sanitize_extra(extra) if extra else None
        if sanitized:
            record["extra"] = sanitized
        line = json.dumps(record, ensure_ascii=False)
        with _TRACE_LOCK:
            if not _ensure_dir():
                return
            try:
                if _TRACE_FILE.exists() and _TRACE_FILE.stat().st_size > _MAX_BYTES:
                    _TRACE_FILE.rename(_TRACE_FILE.with_suffix(".jsonl.1"))
            except OSError:
                _record_error("ROTATION_FAILED")
                return
            try:
                stream = _TRACE_FILE.open("a", encoding="utf-8")
            except OSError:
                _record_error("OPEN_FAILED")
                return
            try:
                with stream as f:
                    f.write(line + "\n")
            except OSError:
                _record_error("WRITE_FAILED")
                return
            _HAS_WRITTEN = True
        _clear_error()
    except Exception:
        _record_error("LOG_FAILED")


def clear_traces():
    global _LAST_ERROR
    with _TRACE_LOCK:
        try:
            if _TRACE_FILE.exists():
                _TRACE_FILE.unlink()
        except OSError:
            _record_error("CLEAR_FAILED")
            return
    _clear_error()


def diagnostic_status():
    """Non-blocking consumer of logger health for UI/diagnostics."""
    try:
        return {
            "path": trace_path(),
            "error": last_error(),
            "writable": True if _HAS_WRITTEN and last_error().get("code") is None else False if last_error().get("code") else None,
        }
    except Exception:
        return {"path": None, "error": {"code": "DIAGNOSTIC_FAILED", "path": None}, "writable": False}
