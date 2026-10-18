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
- Test execution remains dry-run (`live=False)); live trading remains disabled.
- No real order, live login, or network call is part of the offline acceptance tests.

## Verification record and limitation

The Task 9B implementation was reported as implemented and verified. The source-of-truth commit history does not expose a durable transcript with an exact focused pytest pass count, so this handoff intentionally does not invent one. The last documented full-repository run **predates Task 9B** and reported **1595 passed, 233 failed, 20 skipped, 4 errors**; it was not green and is not a post-Task-9B result.

After pulling, record the actual result for:

```powershell
python -m pytest -q test_block9_account_aware_order_feedback.py test_ui5_task4_stage3_task3_core_registration.py test_ui5_task4_stage3_task4_ui_table.py
```

Then run the relevant broader UI/regression set and distinguish baseline failures from new regressions. Do not claim full-suite acceptance without a fresh full-suite run.

## Next gate

**Independent regression/acceptance closure**, not another implementation of Task 9B. Review any newly exposed regressions, keep fixes separately scoped, and update this record with exact commands/results after they have actually been run.
