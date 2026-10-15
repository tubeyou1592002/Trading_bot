# Block 9 — Phase 2 — Task 2B: Lazy Service Composition at MainWindow — COMPLETE (2026-10-15)

## Goal
Compose the already-reviewed Block 9 services at the existing application boundary without changing UI behavior or order dispatch.

## Current verified baseline
- Phase 1 foundation is complete: commits `9efb88e` and `39bd0d6`.
- Task 2A is complete and pushed: `ccdd563`. `make_agah_adapter_factory(broker_manager)` receives `account_id` and resolves the exact account-owned broker via `get_for_account(account_id, "آگاه")`. `AuthenticationService` factory callbacks accept `account_id`.
- The owner ran the focused acceptance set on Windows: **287 passed in 3.12s**.
- `ui/main_window.py` still does not construct or expose `AuthenticationService`. The existing Test/dispatch route is outside this task and must not be changed.

## Exact allowed files
1. `ui/main_window.py`
2. `test_block9_phase2_service_composition.py` (new, focused offline tests)

Do not edit any other file. In particular, do not modify `ui/accounts_page.py`, `ui/account_store.py`, `ui/credential_store.py`, `ui/session_manager.py`, `ui/authentication_service.py`, `brokers/agaah/auth_adapter.py`, `brokers/manager.py`, `ui/test_runner.py`, Core, order engine, provider, feedback, or any UI design file.

## Required implementation
1. Reuse the existing `self.account_store`; do not create a second AccountStore.
2. Add one lazily-created, cached accessor for the `AuthenticationService` using the project's existing MainWindow lazy-service pattern. Construct it only when first requested, never during `MainWindow` construction.
3. Construct exactly one `CredentialStore` and one `SessionManager` for the composed service graph. Inject the existing AccountStore and these dependencies into `AuthenticationService`.
4. Reuse `self._shared_broker_manager()`; do not construct another BrokerManager. Configure the existing account-aware Agah adapter factory with `make_agah_adapter_factory(the_same_manager)`. Keep the generic `AuthenticationService` broker-independent.
5. Cache the completed service only after successful construction; do not expose a partially constructed service after an exception. Repeated access after success returns the same AuthenticationService instance.
6. Keep composition local and offline: do not invoke login, CAPTCHA, credential reads/writes, network requests, broker calls, or order submission while constructing the service. Construction of the service graph must not access the OS credential vault; actual vault operations remain within CredentialStore methods.
7. Do not connect the Accounts page, alter account forms, change broker routing, or claim that production authentication and dispatch now use the same account-owned broker. Those are separate follow-up work.

## Acceptance tests
The new tests must use offline fakes/patches and prove:
- Constructing MainWindow does not instantiate BrokerManager, CredentialStore, SessionManager or AuthenticationService and performs no network/vault/login operation.
- First accessor call composes AuthenticationService from the exact existing `self.account_store`, a CredentialStore, a SessionManager and a factory built with the same cached BrokerManager used by the current MainWindow seam.
- Repeated accessor calls return the same service and do not rebuild its dependencies.
- A construction failure does not leave a partial AuthenticationService cached; a later call can retry safely.
- The composition factory uses `account_id` and resolves account-owned brokers; it must not fall back to name-only `get("آگاه")`.
- Existing UI construction/laziness contracts remain intact.

## Test commands
Run the new focused test first:
```powershell
py -3 -m pytest -q test_block9_phase2_service_composition.py
```
Then run the focused auth/manager regressions:
```powershell
py -3 -m pytest -q test_block9_task4_authentication_service.py test_block9_task4_agah_auth_adapter.py test_block9_task4_integration.py test_broker_manager.py
```
Also run existing UI construction/account regressions if these files are present in the repository:
```powershell
py -3 -m pytest -q test_ui1_application_foundation.py test_ui2_1_account_management.py
```
Report each command and exact output. Do not claim tests that were not run. Never use real credentials, a live broker, network calls, or real orders.

## Git/worktree rules
- No commit, push, stage, cherry-pick, reset, checkout, or broad clean command.
- Preserve every unrelated local file/change; never use `git add -A`.
- Do not update project memory in this implementation task; architect will update it after reviewing the report.
- Final report must list exact changed files, tests/outputs, and any pre-existing failures.

## Completion Record — Owner Report (2026-10-15)

- Commit pushed: `23802a7` — `feat: compose account authentication service lazily`.
- Changed files: `ui/main_window.py` and `test_block9_phase2_service_composition.py`.
- Verification: composition tests **3 passed**; focused auth/adapter/integration/BrokerManager suite **169 passed**; UI foundation/account selection **33 passed, 2 failed** (both failures are in the out-of-scope AccountsPage call missing required `display_name`); `py_compile` and staged `git diff --check` passed.
- Safety: no real login, credential-vault operation, network request or order; no change to Accounts-page UI or order dispatch. Same-instance account-aware authentication/dispatch remains incomplete.
- Follow-up audit after Task 2C: MainWindow passes its cached `BrokerManager` to both AuthenticationService's adapter factory and the TestRunner/DispatchCore path. `AccountsPage` does not yet call AuthenticationService, so user-facing login/logout remains unwired. The trading-state and feedback factories still use name-only broker/provider APIs, and order identity resolution constructs a separate manager.
- Next bounded implementation is Phase 3 Task 3A: add and display the user-chosen display name and call `AccountStore.add(account_id, broker_name, display_name)` correctly; see the authoritative task in `AI_HANDOFF.md`.
