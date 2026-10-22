from dataclasses import dataclass
from enum import Enum


class MarketStatus(Enum):
    """وضعیت نمایشی نماد، برگرفته از نگاشت مستند cEtaval (Decision 020)."""

    PERMITTED = "permitted"
    PERMITTED_RESERVED = "permitted_reserved"
    PERMITTED_BLOCKED = "permitted_blocked"
    PERMITTED_STOPPED = "permitted_stopped"
    FORBIDDEN = "forbidden"
    FORBIDDEN_BLOCKED = "forbidden_blocked"
    FORBIDDEN_STOPPED = "forbidden_stopped"
    FORBIDDEN_RESERVED = "forbidden_reserved"


MARKET_STATUS_LABELS = {
    MarketStatus.PERMITTED: "مجاز",
    MarketStatus.PERMITTED_RESERVED: "مجاز-محفوظ",
    MarketStatus.PERMITTED_BLOCKED: "مجاز-مسدود",
    MarketStatus.PERMITTED_STOPPED: "مجاز-متوقف",
    MarketStatus.FORBIDDEN: "ممنوع",
    MarketStatus.FORBIDDEN_BLOCKED: "ممنوع-مسدود",
    MarketStatus.FORBIDDEN_STOPPED: "ممنوع-متوقف",
    MarketStatus.FORBIDDEN_RESERVED: "ممنوع-محفوظ",
}

MARKET_STATUS_GREEN = frozenset(
    {
        MarketStatus.PERMITTED,
        MarketStatus.PERMITTED_RESERVED,
    }
)

CETAVAL_ALLOWED = frozenset({"A ", "A", "AR"})

CETAVAL_BLOCKED = frozenset(
    {
        "I ",
        "I",
        "AG",
        "AS",
        "IG",
        "IS",
        "IR",
    }
)

_MARKET_STATUS_CODES = {
    "A": MarketStatus.PERMITTED,
    "AR": MarketStatus.PERMITTED_RESERVED,
    "AG": MarketStatus.PERMITTED_BLOCKED,
    "AS": MarketStatus.PERMITTED_STOPPED,
    "I": MarketStatus.FORBIDDEN,
    "IG": MarketStatus.FORBIDDEN_BLOCKED,
    "IS": MarketStatus.FORBIDDEN_STOPPED,
    "IR": MarketStatus.FORBIDDEN_RESERVED,
}


def market_status_from_code(code):
    """نگاشت cEtaval به وضعیت نمایشی؛ مقدار ناشناخته/غایب None است."""
    if not isinstance(code, str):
        return None
    return _MARKET_STATUS_CODES.get(code.strip())


def market_status_label(status):
    """عنوان فارسی وضعیت نمایشی، یا None برای وضعیت ناشناخته."""
    if not isinstance(status, MarketStatus):
        return None
    return MARKET_STATUS_LABELS.get(status)


class TradingStateUnavailable(Exception):
    """
    منبع واقعی وضعیت معاملاتی نماد در دسترس نیست.

    این استثنا تنها زمانی پرتاب می‌شود که broker ادعا
    می‌کند منبع دارد ولی در عمل قادر به دریافت پاسخ
    نیست (مثلاً خطای شبکه، پاسخ نامعتبر، یا قطعی سرویس).

    این استثنا عمداً باریک است؛ خطاهای برنامه‌نویسی
    مانند AttributeError/TypeError/ValueError به‌جای
    بلاک خاموش، باید منتشر شوند تا باگ‌ها پنهان نشوند.
    """


@dataclass
class TradingState:
    """
    وضعیت معاملاتی یک نماد.

    منبع واقعی این اطلاعات (مثلاً endpoint آگاه) هنوز به‌صورت
    رسمی تأیید نشده است؛ بنابراین فیلد `is_verified` صریحاً
    مشخص می‌کند که آیا این نتیجه بر اساس یک منبع معتبر است
    یا خیر.
    """

    is_order_entry_allowed: bool = False
    is_verified: bool = False
    source: str | None = None
    reason: str | None = None
    market_status: MarketStatus | None = None
    market_status_title: str | None = None


VERIFIED_TRADABLE = TradingState(
    is_order_entry_allowed=True,
    is_verified=True,
    source="verified",
)


VERIFIED_BLOCKED = TradingState(
    is_order_entry_allowed=False,
    is_verified=True,
    source="verified",
)


UNVERIFIED = TradingState(
    is_order_entry_allowed=False,
    is_verified=False,
    source="unverified",
    reason="Trading state source not verified.",
)
