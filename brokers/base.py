from abc import ABC, abstractmethod

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
