import unittest
from unittest.mock import MagicMock
import logging

import pytest

from brokers.agaah.instrument_provider import AgaahInstrumentProvider
from brokers.agaah.broker import AgaahBroker


class TestDiagnosticSearch(unittest.TestCase):
    def test_single_shot_no_retry_on_401(self):
        broker = MagicMock(spec=AgaahBroker)
        broker.session = MagicMock()
        broker._url = lambda p: f"https://example.com/api/v1/{p}"
        broker._auth_headers.return_value = {
            "Authorization": "Bearer offline-test",
            "UserIdentifier": "offline-user",
        }
        resp = MagicMock()
        resp.status_code = 401
        resp.json.return_value = {"message": "unauthorized"}
        broker.session.get.return_value = resp

        provider = AgaahInstrumentProvider(broker)
        result = provider.diagnostic_search_once("شستا")

        self.assertEqual(result["status"], 401)
        self.assertEqual(broker.session.get.call_count, 1)
        self.assertEqual(
            broker.session.get.call_args.kwargs["headers"],
            broker._auth_headers.return_value,
        )
        # no retry / recovery
        self.assertNotIn("retry", str(broker.session.get.call_args))

    def test_field_names_extracted(self):
        broker = MagicMock(spec=AgaahBroker)
        broker.session = MagicMock()
        broker._url = lambda p: f"https://example.com/api/v1/{p}"
        broker._auth_headers.return_value = {
            "Authorization": "Bearer offline-test",
            "UserIdentifier": "offline-user",
        }
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"data": [{"nscId": "x", "tseId": "y"}]}
        resp.raise_for_status.return_value = None
        broker.session.get.return_value = resp

        provider = AgaahInstrumentProvider(broker)
        result = provider.diagnostic_search_once("شستا")
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["candidates"][0]["nscId"], "x")


class _OfflineTsetmc:
    def get_info(self, ins_code):
        from models.instrument import Instrument
        return Instrument(symbol="test-symbol", name="test", ins_code=ins_code)


def _http_error(status):
    import requests
    response = MagicMock()
    response.status_code = status
    error = requests.HTTPError("secret raw failure")
    error.response = response
    return error


@pytest.mark.parametrize(
    "failed_stage, expected_reason",
    [("instruments_all", "SEARCH_HTTP_ERROR"),
     ("instruments", "DETAIL_HTTP_ERROR")],
)
def test_automatic_lookup_logs_401_stage_without_sensitive_exception(
    caplog, failed_stage, expected_reason,
):
    broker = MagicMock(spec=AgaahBroker)
    if failed_stage == "instruments_all":
        broker._authed_get_with_recovery.side_effect = _http_error(401)
    else:
        broker._authed_get_with_recovery.return_value = type("Response", (), {
            "status_code": 200,
            "json": lambda self: {
                "isSuccess": True,
                "data": [{"nscId": "candidate-1"}],
            },
            "raise_for_status": lambda self: None,
        })()
    if failed_stage == "instruments":
        broker.get_instrument.side_effect = _http_error(401)
    provider = AgaahInstrumentProvider(broker, _OfflineTsetmc())

    with caplog.at_level(logging.WARNING, logger="brokers.agaah.instrument_provider"):
        with pytest.raises(Exception):
            provider.get_nsc_id("offline-ins-code")

    if failed_stage == "instruments_all":
        assert broker.get_instrument.call_count == 0
    else:
        assert broker.get_instrument.call_count == 1
    assert f"stage={failed_stage} status=401 reason={expected_reason}" in caplog.text
    assert "secret raw failure" not in caplog.text


if __name__ == "__main__":
    unittest.main()
