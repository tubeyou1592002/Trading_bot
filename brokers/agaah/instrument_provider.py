from typing import Dict, Optional, Tuple

import requests

from brokers.agaah.broker import AgaahBroker
from brokers.base import InstrumentLookupError, InstrumentProvider
from market.tsetmc import TSETMC
from models.broker_instrument import BrokerInstrument
from models.instrument import Instrument


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
                f"TSETMC.get_info برای {ins_code} شکست خورد: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        if instrument is None:
            raise InstrumentLookupError(
                f"نمادی با ins_code={ins_code} در TSETMC "
                f"پیدا نشد."
            )

        symbol = getattr(instrument, "symbol", None)
        if not symbol:
            raise InstrumentLookupError(
                f"TSETMC instrument برای {ins_code} فاقد "
                f"symbol است."
            )

        return instrument

    def _search_candidates(
        self,
        symbol: str,
    ) -> list:
        try:
            response = self._broker.session.get(
                self._broker._url(self.SEARCH_PATH),
                params={
                    "query": symbol,
                    "count": self.SEARCH_COUNT,
                },
                headers=self._broker._auth_headers(),
                timeout=self.SEARCH_TIMEOUT,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise InstrumentLookupError(
                f"Agah search برای symbol={symbol} شکست خورد: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise InstrumentLookupError(
                f"Agah search برای symbol={symbol} پاسخ JSON "
                f"نامعتبر برگرداند."
            ) from exc

        if not isinstance(data, dict):
            raise InstrumentLookupError(
                f"Agah search برای symbol={symbol} پاسخی غیر "
                f"از object برگرداند."
            )

        inner = data.get("data")
        if not isinstance(inner, list):
            raise InstrumentLookupError(
                f"Agah search برای symbol={symbol} فاقد data "
                f"لیست‌مانند است."
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

        raw_candidates = self._search_candidates(symbol)

        verified: list = []
        for item in raw_candidates:
            if not isinstance(item, dict):
                continue
            nsc_id = item.get("nscId")
            if not nsc_id:
                continue
            nsc_id = nsc_id.strip()
            if not nsc_id:
                continue
            verified.append(nsc_id)

        if not verified:
            raise InstrumentLookupError(
                f"Agah search برای symbol={symbol} هیچ "
                f"کاندیدایی برنگرداند."
            )

        for nsc_id in verified:
            try:
                broker_instrument = self._broker.get_instrument(
                    nsc_id
                )
            except Exception as exc:
                raise InstrumentLookupError(
                    f"broker.get_instrument({nsc_id}) شکست خورد: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc

            tse_id = getattr(broker_instrument, "tse_id", None)
            if tse_id == ins_code:
                self._nsc_cache[ins_code] = nsc_id
                return nsc_id, broker_instrument

        raise InstrumentLookupError(
            f"هیچ کاندیدای Agah برای symbol={symbol} دارای "
            f"tse_id == {ins_code} نبود."
        )
