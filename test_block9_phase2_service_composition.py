"""Offline tests for lazy Block 9 service composition at MainWindow."""

import pytest
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_main_window_construction_does_not_compose_auth_services(qapp, monkeypatch):
    import ui.authentication_service as auth_module
    import ui.credential_store as credential_module
    import ui.session_manager as session_module

    constructions = []

    class Forbidden:
        def __init__(self, *args, **kwargs):
            constructions.append(type(self).__name__)
            raise AssertionError("auth composition must remain lazy")

    monkeypatch.setattr(auth_module, "AuthenticationService", Forbidden)
    monkeypatch.setattr(credential_module, "CredentialStore", Forbidden)
    monkeypatch.setattr(session_module, "SessionManager", Forbidden)

    window = MainWindow()
    assert window._broker_manager_cache is None
    assert window._authentication_service is None
    assert window._credential_store is None
    assert window._session_manager is None
    assert window.accounts_page._authentication_service_factory is not None
    assert window.accounts_page._credential_store_factory is not None
    assert window.accounts_page._session_manager_factory is not None
    assert constructions == []
    window.close()


def test_authentication_service_composition_is_cached_and_manager_bound(qapp, monkeypatch):
    import brokers.agaah.auth_adapter as adapter_module
    import brokers.manager as manager_module
    import ui.authentication_service as auth_module
    import ui.credential_store as credential_module
    import ui.session_manager as session_module

    calls = []

    class Manager:
        def __init__(self):
            self.account_calls = []
            self.name_calls = []
            self.brokers = {}

        def get_for_account(self, account_id, broker_name):
            self.account_calls.append((account_id, broker_name))
            broker = object()
            self.brokers[(account_id, broker_name)] = broker
            return broker

        def get(self, name):
            self.name_calls.append(name)
            raise AssertionError("name-only broker resolution is forbidden")

    class FakeCredentialStore:
        def __init__(self):
            calls.append(("credentials", self))

    class FakeSessionManager:
        def __init__(self):
            calls.append(("sessions", self))

    class FakeAuthenticationService:
        def __init__(self, account_store, credentials, sessions,
                     adapter_factories):
            calls.append(("service", account_store, credentials, sessions,
                          adapter_factories))
            self.account_store = account_store
            self.credentials = credentials
            self.sessions = sessions
            self.adapter_factories = adapter_factories

    manager = Manager()
    monkeypatch.setattr(manager_module, "BrokerManager", lambda: manager,
                        raising=False)
    monkeypatch.setattr(credential_module, "CredentialStore", FakeCredentialStore)
    monkeypatch.setattr(session_module, "SessionManager", FakeSessionManager)
    monkeypatch.setattr(auth_module, "AuthenticationService", FakeAuthenticationService)

    original_factory = adapter_module.make_agah_adapter_factory
    factory_managers = []

    def tracking_factory(bound_manager):
        factory_managers.append(bound_manager)
        return original_factory(bound_manager)

    monkeypatch.setattr(adapter_module, "make_agah_adapter_factory", tracking_factory)

    window = MainWindow()
    account_store = window.account_store
    assert window._broker_manager_cache is None
    assert window._authentication_service is None

    service = window.authentication_service
    assert service is window.authentication_service
    assert service.account_store is account_store
    assert isinstance(service.credentials, FakeCredentialStore)
    assert isinstance(service.sessions, FakeSessionManager)
    assert window.credential_store is service.credentials
    assert window.session_manager is service.sessions
    assert window.accounts_page._credential_store_factory() is service.credentials
    assert window.accounts_page._session_manager_factory() is service.sessions
    assert window.accounts_page._authentication_service_factory() is service
    assert window.credential_store is window.credential_store
    assert window.session_manager is window.session_manager
    assert len([call for call in calls if call[0] == "credentials"]) == 1
    assert len([call for call in calls if call[0] == "sessions"]) == 1
    assert factory_managers == [manager]
    assert window._shared_broker_manager() is manager
    assert [call[0] for call in calls] == ["credentials", "sessions", "service"]

    adapter_factory = service.adapter_factories["آگاه"]
    broker_a = adapter_factory("account-A").broker
    broker_b = adapter_factory("account-B").broker
    assert broker_a is manager.brokers[("account-A", "آگاه")]
    assert broker_b is manager.brokers[("account-B", "آگاه")]
    assert broker_a is not broker_b
    assert manager.account_calls == [
        ("account-A", "آگاه"), ("account-B", "آگاه")
    ]
    assert manager.name_calls == []
    window.close()


def test_failed_authentication_service_construction_can_retry(qapp, monkeypatch):
    import ui.authentication_service as auth_module
    import ui.credential_store as credential_module
    import ui.session_manager as session_module

    class Manager:
        pass

    manager = Manager()
    window = MainWindow()
    monkeypatch.setattr(window, "_shared_broker_manager", lambda: manager)

    class Dependency:
        def __init__(self):
            pass

    credentials = Dependency()
    sessions = Dependency()
    monkeypatch.setattr(credential_module, "CredentialStore", lambda: credentials)
    monkeypatch.setattr(session_module, "SessionManager", lambda: sessions)
    attempts = []

    class FlakyService:
        def __init__(self, *args, **kwargs):
            attempts.append(None)
            if len(attempts) == 1:
                raise RuntimeError("temporary construction failure")
            self.args = args
            self.kwargs = kwargs

    monkeypatch.setattr(auth_module, "AuthenticationService", FlakyService)
    with pytest.raises(RuntimeError):
        _ = window.authentication_service
    assert window._authentication_service is None

    service = window.authentication_service
    assert isinstance(service, FlakyService)
    assert window.authentication_service is service
    assert len(attempts) == 2
    assert service.args[0] is window.account_store
    assert service.args[1] is credentials
    assert service.args[2] is sessions
    window.close()


def test_accounts_page_injected_factories_are_not_called_on_construction(qapp):
    from ui.account_store import AccountStore
    from ui.accounts_page import AccountsPage

    calls = []
    page = AccountsPage(
        AccountStore(),
        authentication_service_factory=lambda: calls.append("auth"),
        credential_store_factory=lambda: calls.append("credentials"),
        session_manager_factory=lambda: calls.append("sessions"),
    )

    assert calls == []
    page.close()
