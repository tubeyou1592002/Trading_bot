import logging
from typing import Dict, Optional, Tuple

from brokers.agaah.broker import AgaahBroker
from brokers.base import InstrumentLookupError, InstrumentProvider
from market.tsetmc import TSETMC
from models.broker_instrument import BrokerInstrument
from models.instrument import Instrument
from market.symbol_resolver import SymbolResolver


class AgaahInstrumentProvider(InstrumentProvider):
    """
    تبدیل TSETMC `ins_code` به Agah `nscId` از مسیر
    ایمن و تأییدشده:

        TSETMC ins_code
            -> TSETMC.get_info()
            -> Instrument.symbol
            -> Agah GET /instruments/all?query=<symbol>&count=50
            -> بررسی هر نتیجه با
               broker.get_instrument(nscId) و مقایسه‌ی
               tse_id برگشتی با ins_code
            -> nsc_id متناظر

    هیچ fallback مبتنی بر cIsin، ساختار nscId، یا
    انتخاب نتیجه‌ی اول وجود ندارد. در صورت عدم تطابق
    دقیق `tse_id == ins_code`، این provider
    `InstrumentLookupError` پرتاب می‌کند.

    هیچ فایل کش پایداری نگه نمی‌دارد؛ فقط کش حافظه‌ای
    در سطح نمونه.
    """

    SEARCH_PATH = "instruments/all"
    SEARCH_COUNT = 50
    SEARCH_TIMEOUT = 10

    def __init__(
        self,
        agaah_broker: AgaahBroker,
        tsetmc_client: Optional[TSETMC] = None,
    ):
        self._broker = agaah_broker
        self._tsetmc = tsetmc_client or TSETMC()

        self._cache: Dict[
            str, Tuple[Instrument, BrokerInstrument]
        ] = {}
        self._nsc_cache: Dict[str, str] = {}

    # =================================================
    # Public API (InstrumentProvider ABC)
    # =================================================

    def get_instrument(
        self,
        ins_code: str,
    ) -> Tuple[Instrument, BrokerInstrument]:
        if ins_code in self._cache:
            return self._cache[ins_code]

        instrument = self._fetch_tsetmc_instrument(ins_code)

        nsc_id, broker_instrument = self._resolve_nsc_id(
            ins_code, instrument=instrument
        )

        result = (instrument, broker_instrument)
        self._cache[ins_code] = result
        return result

    def get_nsc_id(
        self,
        ins_code: str,
    ) -> Optional[str]:
        if ins_code in self._nsc_cache:
            return self._nsc_cache[ins_code]

        instrument = self._fetch_tsetmc_instrument(ins_code)

        nsc_id, _ = self._resolve_nsc_id(
            ins_code, instrument=instrument
        )

        return nsc_id

    def refresh_cache(self) -> None:
        self._cache.clear()
        self._nsc_cache.clear()

    def diagnostic_search_once(self, symbol: str):
        logger = logging.getLogger(__name__)
        try:
            response = self._broker.session.get(
                self._broker._url(self.SEARCH_PATH),
                params={"query": symbol, "count": self.SEARCH_COUNT},
                headers=self._broker._auth_headers(),
                timeout=self.SEARCH_TIMEOUT,
            )
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            logger.warning(
                "lookup stage=diagnostic_search status=%s reason=DIAGNOSTIC_REQUEST_FAILED",
                status,
            )
            return {"status": status, "candidates": [], "connection_error": True}
        status = response.status_code
        candidates = []
        try:
            data = response.json()
            if isinstance(data, dict):
                inner = data.get("data")
                if isinstance(inner, list):
                    for item in inner:
                        if isinstance(item, dict):
                            candidates.append({
                                "nscId": item.get("nscId"),
                                "tseId": item.get("tseId"),
                                "name": item.get("name"),
                            })
        except Exception:
            pass
        logger.info("diagnostic search status=%s candidates=%s", status, len(candidates))
        return {"status": status, "candidates": candidates}

    def diagnostic_mapping(self, ins_code: str, instrument: Optional[Instrument] = None,
                           *, request_id=None):
        if ins_code in self._nsc_cache:
            return {"nsc_id": self._nsc_cache[ins_code], "candidates": [],
                    "source": "cache", "candidate_count": 0, "search_status": None}
        instrument = instrument or self._fetch_tsetmc_instrument(ins_code)
        symbol = instrument.symbol
        diag = self.diagnostic_search_once(symbol)
        candidates = diag.get("candidates", [])
        if diag.get("connection_error"):
            return {"nsc_id": None, "candidates": candidates, "symbol": symbol,
                    "ins_code": ins_code, "search_status": None, "source": "lookup",
                    "candidate_count": 0, "connection_error": True}
        if diag.get("status") == 401:
            return {"nsc_id": None, "candidates": candidates, "symbol": symbol,
                    "ins_code": ins_code, "search_status": 401, "source": "lookup",
                    "candidate_count": len(candidates)}
        matched = None
        for c in candidates:
            c["exact_match"] = (c.get("tseId") == ins_code)
            if c["exact_match"] and matched is None:
                matched = c.get("nscId")
        status = diag.get("status")
        return {"nsc_id": matched, "candidates": candidates, "symbol": symbol,
                "ins_code": ins_code, "search_status": status, "source": "lookup",
                "candidate_count": len(candidates)}

    # =================================================
    # Internal helpers
    # =================================================

    def _fetch_tsetmc_instrument(
        self,
        ins_code: str,
    ) -> Instrument:
        try:
            instrument = self._tsetmc.get_info(ins_code)
        except Exception as exc:
            raise InstrumentLookupError(
                "TSETMC instrument lookup failed.", stage="tsetmc_info",
                reason_code="TSETMC_INFO_FAILED",
            ) from exc

        if instrument is None:
            raise InstrumentLookupError(
                "TSETMC instrument was not found.", stage="tsetmc_info",
                reason_code="TSETMC_INFO_FAILED",
            )

        symbol = getattr(instrument, "symbol", None)
        if not symbol:
            raise InstrumentLookupError(
                "TSETMC instrument response was invalid.", stage="tsetmc_info",
                reason_code="TSETMC_INFO_INVALID",
            )

        return instrument

    def _search_candidates(
        self,
        symbol: str,
        *,
        normalization="symbol_resolver",
    ) -> list:
        """
        جست‌وجوی کاندیداها از Agah.

        این فراخوانی از مسیر احراز‌شده‌ی بروکر
        (``_authed_get_with_recovery``) عبور می‌کند تا یک HTTP 401 واقعی
        بتواند از طریق بازیابی حساب‌محور نصب‌شده یک‌بار تازه‌سازی و
        تکرار شود. هیچ مسیر جایگزینی مبتنی بر ``session.get`` مستقیم
        اینجا وجود ندارد و هیچ لایه‌ی retry دومی اعمال نمی‌شود؛
        helper بروکر مالک حداکثر یک تکرار است و در نبود handler
        به‌صورت fail-closed شکست می‌خورد. مهلت ثابت helper (۱۰ ثانیه)
        با ``SEARCH_TIMEOUT`` این provider هم‌ارز است.
        """
        try:
            response = self._broker._authed_get_with_recovery(
                self.SEARCH_PATH,
                params={
                    "query": symbol,
                    "count": self.SEARCH_COUNT,
                },
            )
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            reason = "SEARCH_HTTP_ERROR" if status is not None else "SEARCH_FAILED"
            logging.getLogger(__name__).warning(
                "lookup stage=instruments_all status=%s reason=%s", status, reason
            )
            raise InstrumentLookupError(
                "Agah instrument search failed.", stage="instruments_all",
                http_status=status, reason_code=reason,
                diagnostic={"http_status": status,
                            "api_classification": "HTTP_ERROR" if status is not None else "REQUEST_FAILED",
                            "total_candidates": 0, "valid_nsc_id_candidates": 0,
                            "normalization": normalization},
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise InstrumentLookupError(
                "Agah search returned invalid JSON.", stage="instruments_all",
                http_status=getattr(response, "status_code", None),
                reason_code="SEARCH_JSON_INVALID",
                diagnostic={"http_status": getattr(response, "status_code", None),
                            "api_classification": "INVALID_JSON",
                            "total_candidates": 0, "valid_nsc_id_candidates": 0,
                            "normalization": normalization},
            ) from exc

        if isinstance(data, dict) and data.get("isSuccess") is False:
            raise InstrumentLookupError(
                "Agah search API reported failure.", stage="instruments_all",
                http_status=getattr(response, "status_code", None),
                reason_code="SEARCH_API_FAILED",
                diagnostic={"http_status": getattr(response, "status_code", None),
                            "api_classification": "API_FAILURE",
                            "total_candidates": 0, "valid_nsc_id_candidates": 0,
                            "normalization": normalization},
            )

        if not isinstance(data, dict):
            raise InstrumentLookupError(
                "Agah search response structure was invalid.", stage="instruments_all",
                http_status=getattr(response, "status_code", None),
                reason_code="SEARCH_RESPONSE_INVALID",
                diagnostic={"http_status": getattr(response, "status_code", None),
                            "api_classification": "INVALID_STRUCTURE",
                            "total_candidates": 0, "valid_nsc_id_candidates": 0,
                            "normalization": normalization},
            )

        inner = data.get("data")
        if not isinstance(inner, list):
            raise InstrumentLookupError(
                "Agah search response structure was invalid.", stage="instruments_all",
                http_status=getattr(response, "status_code", None),
                reason_code="SEARCH_RESPONSE_INVALID",
                diagnostic={"http_status": getattr(response, "status_code", None),
                            "api_classification": "INVALID_STRUCTURE",
                            "total_candidates": 0, "valid_nsc_id_candidates": 0,
                            "normalization": normalization},
            )

        valid_nsc_id_count = sum(
            isinstance(item, dict) and isinstance(item.get("nscId"), str)
            and bool(item["nscId"].strip()) for item in inner
        )
        self._last_search_diagnostic = {
            "http_status": getattr(response, "status_code", None),
            "api_classification": "SUCCESS",
            "total_candidates": len(inner),
            "valid_nsc_id_candidates": valid_nsc_id_count,
            "normalization": normalization,
        }
        if inner and valid_nsc_id_count == 0:
            raise InstrumentLookupError(
                "Agah search candidates contained no valid identifiers.",
                stage="instruments_all",
                http_status=getattr(response, "status_code", None),
                reason_code="SEARCH_CANDIDATES_INVALID",
                diagnostic=self._last_search_diagnostic,
            )
        return inner

    def _resolve_nsc_id(
        self,
        ins_code: str,
        instrument: Optional[Instrument] = None,
    ) -> Tuple[str, BrokerInstrument]:
        """
        منطق اصلی mapping.

        اگر `instrument` داده شود، از TSETMC.get_info
        مجدد صرف‌نظر می‌شود. در غیر این صورت، خودش
        TSETMC را فراخوانی می‌کند.

        خروجی: (nsc_id, BrokerInstrument)
        BrokerInstrument داده‌شده همان نمونه‌ای است که
        تطبیق tse_id روی آن تأیید شده است.
        """

        if instrument is None:
            instrument = self._fetch_tsetmc_instrument(ins_code)

        symbol = instrument.symbol

        normalized_symbol = SymbolResolver.normalize(symbol)
        normalization = ("symbol_resolver_unchanged" if normalized_symbol == symbol
                         else "symbol_resolver_changed")
        raw_candidates = self._search_candidates(normalized_symbol, normalization=normalization)
        search_diagnostic = getattr(self, "_last_search_diagnostic", {})

        verified: list = []
        for item in raw_candidates:
            if not isinstance(item, dict):
                continue
            nsc_id = item.get("nscId")
            if not isinstance(nsc_id, str) or not nsc_id.strip():
                continue
            nsc_id = nsc_id.strip()
            if not nsc_id:
                continue
            verified.append(nsc_id)

        if not verified:
            raise InstrumentLookupError(
                "Agah search returned no usable candidates.", stage="instruments_all",
                http_status=search_diagnostic.get("http_status"),
                reason_code=("SEARCH_NO_CANDIDATES" if not raw_candidates
                             else "SEARCH_CANDIDATES_INVALID"),
                diagnostic=search_diagnostic,
            )

        for nsc_id in verified:
            try:
                broker_instrument = self._broker.get_instrument(
                    nsc_id
                )
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                reason = "DETAIL_HTTP_ERROR" if status is not None else "DETAIL_FAILED"
                logging.getLogger(__name__).warning(
                    "lookup stage=instruments status=%s reason=%s", status, reason
                )
                raise InstrumentLookupError(
                    "Agah instrument detail lookup failed.", stage="instruments",
                    http_status=status, reason_code=reason,
                ) from exc

            tse_id = getattr(broker_instrument, "tse_id", None)
            if tse_id == ins_code:
                self._nsc_cache[ins_code] = nsc_id
                return nsc_id, broker_instrument

        raise InstrumentLookupError(
            "No Agah candidate matched the requested instrument.",
            stage="instruments",
            http_status=search_diagnostic.get("http_status"),
            reason_code="DETAIL_NO_MATCH", diagnostic=search_diagnostic,
        )
