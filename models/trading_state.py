from dataclasses import dataclass


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
