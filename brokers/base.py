from abc import ABC, abstractmethod
from typing import Optional, Tuple

from models.broker_instrument import BrokerInstrument
from models.instrument import Instrument
from models.trading_state import TradingState


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
