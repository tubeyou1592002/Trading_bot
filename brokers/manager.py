from typing import TYPE_CHECKING
from threading import RLock

from .agaah import AgaahBroker, AgaahInstrumentProvider

if TYPE_CHECKING:
    from brokers.base import InstrumentProvider


class BrokerManager:

    def __init__(self):
        self.brokers = {}
        self.providers = {}
        self._provider_classes = {}
        self._broker_factories = {}
        self.account_brokers = {}
        self.account_providers = {}
        self._account_lock = RLock()
        self._account_provider_instances = []

        self.register(
            "آگاه", AgaahBroker(), AgaahInstrumentProvider,
            broker_factory=AgaahBroker,
        )

    def register(self, name, broker, provider_class, broker_factory=None):
        """
        ثبت یک Broker مستقل همراه با Provider سازگار با همان Broker.

        name: نام Broker برای resolve کردن
        broker: همان Broker instance که قرار است مدیریت شود
        provider_class: کلاس Provider سازگار با همین Broker
        """
        if broker_factory is not None and not callable(broker_factory):
            raise ValueError("broker_factory must be callable")
        if not callable(provider_class):
            raise ValueError("provider_class must be callable")
        with self._account_lock:
            if name in self.brokers:
                raise ValueError(f"Broker already registered: {name}")

            self.brokers[name] = broker
            self._provider_classes[name] = provider_class
            self._broker_factories[name] = broker_factory

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

    def get_for_account(self, account_id, broker_name):
        """Resolve a broker instance scoped to the exact account/name pair."""
        if not isinstance(account_id, str) or not account_id.strip():
            raise ValueError("Invalid account id")
        if broker_name not in self.brokers:
            raise ValueError(f"Unknown broker: {broker_name}")

        key = (account_id, broker_name)
        with self._account_lock:
            if key in self.account_brokers:
                return self.account_brokers[key]

            factory = self._broker_factories.get(broker_name)
            if factory is None:
                raise ValueError(f"No account broker factory registered: {broker_name}")

            broker = factory()
            required_methods = (
                "login", "get_instrument", "get_account", "place_order", "cancel_order",
                "get_trading_state", "get_buy_capacity", "get_sell_capacity",
            )
            if (broker is None or any(not callable(getattr(broker, method, None))
                                      for method in required_methods)
                    or not isinstance(getattr(broker, "name", None), str)
                    or not broker.name.strip()
                    or any(broker is existing for existing in self.brokers.values())
                    or any(broker is existing for existing in self.account_brokers.values())):
                raise ValueError("Broker factory returned an invalid or reused instance")

            # Optional additive account-binding contract used by brokers
            # that provide account-owned prepared senders.
            bind_identity = getattr(broker, "bind_account_identity", None)
            if callable(bind_identity):
                bind_identity(account_id)

            self.account_brokers[key] = broker
            return broker

    def get_instrument_provider_for_account(self, account_id, broker_name):
        """Lazily resolve an isolated provider for an account-scoped broker."""
        if not isinstance(account_id, str) or not account_id.strip():
            raise ValueError("Invalid account id")
        if broker_name not in self.brokers:
            raise ValueError(f"Unknown broker: {broker_name}")

        key = (account_id, broker_name)
        with self._account_lock:
            if key in self.account_providers:
                return self.account_providers[key]

            broker = self.get_for_account(account_id, broker_name)
            provider = self._provider_classes[broker_name](broker)
            if (provider is None
                    or not callable(getattr(provider, "get_instrument", None))
                    or not callable(getattr(provider, "get_nsc_id", None))
                    or not callable(getattr(provider, "refresh_cache", None))
                    or getattr(provider, "_broker", None) is not broker
                    or any(provider is existing for existing in self.providers.values())
                    or any(provider is existing for existing in self._account_provider_instances)):
                raise ValueError("Provider factory returned an invalid or reused instance")

            self.account_providers[key] = provider
            self._account_provider_instances.append(provider)
            return provider
