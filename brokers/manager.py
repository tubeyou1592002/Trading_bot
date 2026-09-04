from typing import TYPE_CHECKING

from .agaah import AgaahBroker, AgaahInstrumentProvider

if TYPE_CHECKING:
    from brokers.base import InstrumentProvider


class BrokerManager:

    def __init__(self):
        self.brokers = {
            "آگاه": AgaahBroker(),
        }

        self.providers: dict = {}

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

        provider = AgaahInstrumentProvider(broker)

        self.providers[name] = provider

        return provider