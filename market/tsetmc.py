import math
import re
from dataclasses import dataclass

import requests

from models.instrument import Instrument


BASE_URL = "https://cdn.tsetmc.com/api"
# The CDN Loader returns the SPA shell without the inline page variables.
# The old Loader still embeds PSGelStaMin/PSGelStaMax for the InsCode.
PRICE_LIMITS_URL = "https://old.tsetmc.com/Loader.aspx?ParTree=151311&i={ins_code}"

# The Loader page embeds the exchange's daily allowed range in JavaScript.
# Only these two scalar assignments are read; the page itself is never
# logged or stored.
_PS_GEL_STA_MIN_RE = re.compile(
    r"\bPSGelStaMin\s*=\s*(?P<value>[^;,\r\n]+)"
)
_PS_GEL_STA_MAX_RE = re.compile(
    r"\bPSGelStaMax\s*=\s*(?P<value>[^;,\r\n]+)"
)


@dataclass(frozen=True)
class PriceLimits:
    """Daily allowed minimum/maximum price for one TSETMC instrument."""

    price_min: int | None = None
    price_max: int | None = None


class PriceLimitsUnavailable(RuntimeError):
    """The response carried no usable allowed-range fields at all."""


def _parse_exact_integral_text(text):
    """Parse an ASCII integer or an integral decimal string exactly.

    The Loader page is JavaScript, so ``PSGelStaMin``/``PSGelStaMax`` often
    arrive as *strings* such as ``"7630.0"`` even though the value is a whole
    price. A trailing fractional part is accepted only when it is entirely
    zeros; non-zero fractions, exponents, signs and unknown formats are
    rejected rather than truncated.
    """
    text = text.strip()
    if not text or not text.isascii():
        return None
    whole, dot, fraction = text.partition(".")
    if dot:
        if not fraction or not fraction.isdigit():
            return None
        if any(char != "0" for char in fraction):
            return None
    if not whole or not whole.isdigit():
        return None
    return int(whole)


def _validated_limit(value):
    """Return an exact positive integer limit, or ``None``.

    The Loader page may expose the value as a JavaScript number or a quoted
    integral-decimal string (for example ``"7630.0"``). Only an exactly
    integral, positive value is accepted: non-integral numbers, negatives,
    empty/unknown strings and booleans are never rounded, truncated or
    guessed.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        number = int(value)
    elif isinstance(value, str):
        number = _parse_exact_integral_text(value)
        if number is None:
            return None
    else:
        return None
    if number <= 0:
        return None
    return number


def _read_ps_gel_sta_text(html, pattern):
    """Return the raw scalar text for one field, or ``None`` if it is absent."""
    if not isinstance(html, str):
        return None
    match = pattern.search(html)
    if match is None:
        return None
    text = match.group("value").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        text = text[1:-1].strip()
    return text


def _extract_ps_gel_sta(html, pattern):
    """Read one PSGelSta* scalar from the Loader HTML, or return ``None``."""
    text = _read_ps_gel_sta_text(html, pattern)
    if text is None:
        return None
    return _validated_limit(text)


class TSETMC:

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0"
        })

    def search(self, text: str):
        """جستجوی نمادها"""

        text = text.strip()

        if not text:
            return []

        url = f"{BASE_URL}/Instrument/GetInstrumentSearch/{text}"

        response = self.session.get(url, timeout=10)
        response.raise_for_status()

        data = response.json()

        results = []

        for item in data.get("instrumentSearch", []):

            results.append({
                "symbol": item.get("lVal18AFC"),
                "name": item.get("lVal30"),
                "ins_code": item.get("insCode"),
                "flow": item.get("flow"),
                "market": item.get("flowTitle"),
            })

        return results

    def get_info(self, ins_code: str):
        """دریافت اطلاعات کامل نماد"""

        url = f"{BASE_URL}/Instrument/GetInstrumentInfo/{ins_code}"

        response = self.session.get(url, timeout=10)
        response.raise_for_status()

        info = response.json()["instrumentInfo"]

        return Instrument(
            symbol=info.get("lVal18AFC"),
            name=info.get("lVal30"),
            ins_code=info.get("insCode"),
            instrument_id=info.get("instrumentID"),
            isin=info.get("cIsin"),
            market=info.get("flowTitle"),
            flow=info.get("flow"),
        )

    def get_price_limits(self, ins_code: str) -> PriceLimits:
        """Return the exchange's daily allowed range for an InsCode.

        The range is read from ``PSGelStaMin``/``PSGelStaMax`` on the
        TSETMC old Loader page, not from the day's traded low/high values.
        A response that lacks either field raises ``PriceLimitsUnavailable``
        so the UI can distinguish a failed fetch from bad values. When both
        fields are present but a value is invalid, non-positive or the range
        is inverted, ``PriceLimits(None, None)`` is returned — no value is
        guessed or truncated.
        """

        if not isinstance(ins_code, str) or not ins_code.strip():
            raise ValueError("ins_code must be a non-empty string")

        url = PRICE_LIMITS_URL.format(ins_code=ins_code.strip())

        response = self.session.get(url, timeout=10)
        response.raise_for_status()

        html = response.text
        min_text = _read_ps_gel_sta_text(html, _PS_GEL_STA_MIN_RE)
        max_text = _read_ps_gel_sta_text(html, _PS_GEL_STA_MAX_RE)
        if min_text is None or max_text is None:
            raise PriceLimitsUnavailable(
                "TSETMC Loader response has no price limit fields"
            )

        price_min = _validated_limit(min_text)
        price_max = _validated_limit(max_text)

        if (
            price_min is None
            or price_max is None
            or price_min > price_max
        ):
            return PriceLimits(None, None)

        return PriceLimits(price_min=price_min, price_max=price_max)

    def get_trading_state(self, ins_code: str):
        """دریافت وضعیت معاملاتی نماد از TSETMC.

        Endpoint:
            https://cdn.tsetmc.com/api/MarketData/GetInstrumentStateAll/{ins_code}

        Returns a list of instrument state records from TSETMC,
        each containing `cEtaval` and `cEtavalTitle`.

        The caller is responsible for selecting the latest state
        (highest dEven/hEven) and verifying that the returned
        `insCode` matches the requested `ins_code`.

        `cEtaval` is the primary field for trading state mapping
        (see Decision 020). `cEtavalTitle` is informational only.
        """

        url = (
            f"{BASE_URL}/MarketData/"
            f"GetInstrumentStateAll/{ins_code}"
        )

        response = self.session.get(url, timeout=10)
        response.raise_for_status()

        data = response.json()

        states = data.get("instrumentState")

        if not isinstance(states, list):
            return []

        return states