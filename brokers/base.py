from abc import ABC, abstractmethod
from typing import Optional, Tuple

from models.broker_instrument import BrokerInstrument
from models.instrument import Instrument
from models.trading_state import TradingState


class InstrumentLookupError(Exception):
    """
    استثنای رسمی قرارداد InstrumentProvider.

    زمانی پرتاب می‌شود که provider نتواند رابطه‌ی بین
    TSETMC `ins_code` و شناسه‌ی کارگزاری را با اطمینان
    تعیین کند.

    این استثنا در لایه broker interface تعریف شده است
    تا هم providerهای مختلف (آگاه، آینده، ...) و هم
    OrderEngine بتوانند بدون وابستگی به یکدیگر به آن
    ارجاع دهند.
    """


class Broker(ABC):

    @property
    @abstractmethod
    def name(self):
        pass

    @abstractmethod
    def login(self, username, password, **kwargs):
        pass

    @abstractmethod
    def get_account(self):
        pass

    @abstractmethod
    def place_order(self, order, live: bool = False):
        pass

    @abstractmethod
    def cancel_order(self, order_id):
        pass

    @abstractmethod
    def get_trading_state(self, nsc_id: str) -> TradingState:
        """
        وضعیت معاملاتی نماد.

        پیاده‌سازی این متد صریحاً به عهده هر broker است.
        هیچ پیش‌فرض خاموشی در این لایه وجود ندارد؛
        brokerای که منبع معتبری ندارد، باید صریحاً
        `models.trading_state.UNVERIFIED` برگرداند یا
        `models.trading_state.TradingStateUnavailable`
        پرتاب کند. موتور سفارش، حالت UNVERIFIED یا
        استثنای منبع را به‌صورت ایمن بلاک می‌کند.
        """
        pass

    def get_buy_capacity(
        self,
        nsc_id: str,
        side_code: int,
        fund,
        price: int,
    ) -> int:
        """
        حداکثر تعداد قابل‌خرید (ظرفیت) برای یک سفارش
        خرید از سمت broker.

        پیش‌فرض: ``NotImplementedError`` پرتاب می‌شود؛
        یعنی هر brokerی که این متد را override نکند،
        خرید آن‌را به‌صورت fail-closed بلاک می‌کند.
        فقط brokerهای دارای دسترسی به API ظرفیت
        (مثلاً آگاه) باید آن را پیاده‌سازی کنند.
        """
        raise NotImplementedError(
            "این Broker قابلیت دریافت ظرفیت خرید "
            "(get_buy_capacity) را پیاده‌سازی نکرده است."
        )


class InstrumentProvider(ABC):

    @abstractmethod
    def get_instrument(
        self,
        ins_code: str,
    ) -> Tuple[Instrument, BrokerInstrument]:
        """
        بازگرداندن زوج (Instrument, BrokerInstrument) برای
        یک `ins_code` داده‌شده.

        پیاده‌سازی باید `InstrumentLookupError` پرتاب کند
        اگر هر کدام از دو سمت قابل بازیابی نباشد.
        """
        raise NotImplementedError

    @abstractmethod
    def get_nsc_id(
        self,
        ins_code: str,
    ) -> Optional[str]:
        """
        بازگرداندن `nscId` کارگزاری برای `ins_code` داده‌شده.

        در صورت عدم موفقیت، یا `InstrumentLookupError` پرتاب
        می‌شود یا (بسته به سیاست پیاده‌سازی) `None` برگردانده
        می‌شود. رفتار دقیق در مستندات پیاده‌سازی مشخص شده است.
        """
        raise NotImplementedError

    @abstractmethod
    def refresh_cache(self) -> None:
        """
        پاک‌کردن کش داخلی provider در صورت وجود.

        پیاده‌سازی‌های بدون کشِ پایدار می‌توانند این متد را
        به‌صورت `pass` پیاده‌سازی کنند.
        """
        raise NotImplementedError
