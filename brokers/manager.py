from typing import TYPE_CHECKING

from .agaah import AgaahBroker, AgaahInstrumentProvider

if TYPE_CHECKING:
    from brokers.base import InstrumentProvider


class BrokerManager:

    def __init__(self):
        self.brokers = {}
        self.providers = {}
        self._provider_classes = {}

        self.register("آگاه", AgaahBroker(), AgaahInstrumentProvider)

    def register(self, name, broker, provider_class):
        """
        ثبت یک Broker مستقل همراه با Provider سازگار با همان Broker.

        name: نام Broker برای resolve کردن
        broker: همان Broker instance که قرار است مدیریت شود
        provider_class: کلاس Provider سازگار با همین Broker
        """
        if name in self.brokers:
            raise ValueError(
                f"Broker already registered: {name}"
            )

        self.brokers[name] = broker
        self._provider_classes[name] = provider_class

    def names(self):
        return list(self.brokers.keys())

    def get(self, name):
        if name not in self.brokers:
            raise ValueError(
                f"Unknown broker: {name}"
            )

        return self.brokers[name]

    def get_instrument_provider(self, name: str) -> "InstrumentProvider":
        """
        دریافت InstrumentProvider برای یک broker مشخص.

        provider به‌صورت lazy ساخته می‌شود و در
        `self.providers` cache می‌شود. provider متناظر
        با broker دقیقاً همان instance موجود در
        `self.brokers[name]` را استفاده می‌کند تا
        session، auth state، و کش provider با lifecycle
        broker سازگار باشد.
        """

        if name not in self.brokers:
            raise ValueError(
                f"Unknown broker: {name}"
            )

        if name in self.providers:
            return self.providers[name]

        broker = self.brokers[name]
        provider_class = self._provider_classes[name]

        provider = provider_class(broker)

        self.providers[name] = provider

        return provider
