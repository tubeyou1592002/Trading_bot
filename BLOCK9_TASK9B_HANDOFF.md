# Block 9 — Task 9B: Account-Aware Order Feedback

**Status:** Implementation committed on `master` in `9ad15d435c2dc12eb3d95ba3f3ead071f6884e80` — `fix: scope order feedback to account runtime` (2026-10-18).

## Scope delivered

- `ui/main_window.py`: account-scoped feedback runtime registry and start/stop lifecycle.
- `ui/order_feedback_service.py`: explicit account identity, account-scoped broker resolution, idempotent listener registration, and restart-safe stop/start.
- `ui/order_configuration_page.py`: account-scoped event binding and row feedback.
- `ui/accounts_page.py`: lifecycle notifications for logout, account deletion, and broker change.
- `test_block9_account_aware_order_feedback.py`: offline, deterministic acceptance coverage.
- Existing UI registration/table tests updated to protect adjacent behavior.

## Acceptance contracts covered

1. Two accounts on the same broker receive distinct cached feedback runtimes and distinct account-owned broker instances. Resolution uses `BrokerManager.get_for_account(account_id, broker_name)`, not the name-only lookup.
2. Missing/invalid account identity or unusable authorization/session state fails closed: no runtime is composed or started.
3. Logout, deletion, or broker change stops only the affected account's runtime. Switching the active account does not stop another account's runtime.
4. Repeated start/stop/restart reuses the same runtime and does not register duplicate broker listeners.
5. Matching decision IDs on different accounts remain isolated; `AcceptedByBourse` and queue-position events update only the matching account's row. Unknown or cross-account events are no-ops.
6. Main-window construction remains lazy/offline, and the existing order-authorization gate remains connected.
7. Starting feedback never sends an order; no order-send method is added to the feedback service.

## Invariants preserved

- Account ownership is keyed by `(account_id, broker_name)`.
- The existing `DispatchCore → OrderEngine → M6-A…M6-E` execution/preflight chain is unchanged.
- The fail-closed UI order-authorization gate remains in force.
- Test execution remains dry-run (`live=False`); live trading remains disabled.
- No real order, live login, or network call is part of the offline acceptance tests.

## Verification record and limitation

Architectural review accepted Task 9B within the approved scope. Fresh focused acceptance run: `python -m pytest -q test_block9_account_aware_order_feedback.py test_ui5_task4_stage3_task3_core_registration.py test_ui5_task4_stage3_task4_ui_table.py` → **56 passed in 6.09s, exit 0**. This validates the scoped Task 9B contract and adjacent registration/table regressions; it does not establish that the entire repository suite is green.

The focused acceptance result above is recorded. The next phase is **broader regression and final acceptance of the local User Application**, not another implementation pass for Task 9B. The prior agent-reported broader run had 57 passed and 9 failed (attributed to missing `nats`); `py_compile` was reported successful, and one UI-7 failure was reported as baseline. These broader-run details are reported evidence, not a result reproduced by the fresh 56-test focused run. Classify actual failures during local-app acceptance and distinguish baseline/environment issues from new regressions.

## Next gate

**Task 9B scoped acceptance: COMPLETE.** Next gate: broader regression and final acceptance of the local User Application. Do not reopen Task 9B without a reproducible, in-scope regression. Keep Central Server and later phases out of scope until local-app acceptance is complete.
