# Trading Bot — Project Context



## Project Overview



Trading Bot is a Python project for developing an automated trading application for the Iranian stock market.



The application is designed to work with:



* TSETMC for market/instrument information.

* Multiple Iranian brokers through broker-specific adapters.

* A central, broker-independent order engine.

* Multiple trading accounts.

* Precise order scheduling and execution.

* Safe testing and dry-run workflows.



The project is currently under active development and is **not considered production-ready**.



---



## Current Status



**Current Block 9 checkpoint (updated 2026-10-18):** Task 9A and Task 9B are implemented. Task 9B — account-aware order feedback/runtime lifecycle — is accepted at the scoped level following architectural review and a fresh focused acceptance run: `python -m pytest -q test_block9_account_aware_order_feedback.py test_ui5_task4_stage3_task3_core_registration.py test_ui5_task4_stage3_task4_ui_table.py` → **56 passed in 6.09s, exit 0**. Its account-keyed runtimes, account-scoped broker resolution, fail-closed startup, listener idempotency/restart behavior, account-isolated feedback routing, and account-specific lifecycle handling are covered by this test set. No further Task 9B code change is requested at this point.

The full project/test suite is not being declared green. An earlier agent-reported broader run had **57 passed and 9 failed**, attributing the nine failures to missing `nats`; `py_compile` was reported successful, and a UI-7 failure was described as baseline. Those reports have not been independently reproduced in the current focused run. The next phase is broader regression and final acceptance of the **local User Application**, with baseline/environment failures classified separately from newly introduced regressions. Preserve the fail-closed order-authorization gate, `DispatchCore → OrderEngine → M6-A…M6-E`, dry-run `live=False`, and disabled live trading.

**Roadmap position (updated 2026-10-18):** UI-1 through UI-10 are recorded complete. Block 9 Tasks 9A and 9B are implemented; Task 9B's scoped architectural review and focused acceptance are complete. The current gate is local-application regression/final acceptance, not another Task 9B implementation. Central Server, Admin Panel, centralized License/Activation, multi-user testing, and release preparation remain later high-level phases, not yet decomposed into a definitive numbered task count.

The project currently has:



* TSETMC symbol search and instrument resolution.

* Persian/Arabic symbol normalization.

* Windows Persian keyboard-layout handling.

* Initial broker abstraction.

* Initial Agah broker implementation.

* Account, instrument, broker-instrument and order models.

* Order validation.

* Initial order engine.

* Agah API investigation and test scripts.

* Dry-run/testing infrastructure.

* Local Git repository with an initial baseline commit.

* `AgaahInstrumentProvider` for safe `TSETMC insCode → Agah nscId` mapping (Decision 018).

* `InstrumentLookupError` as the official `InstrumentProvider` contract exception in `brokers/base.py` (Decision 019).

* `OrderEngine.execute_by_ins_code(...)` that resolves `ins_code` through an `InstrumentProvider` and delegates to the existing `execute(...)` (commit 91bd2b4).

* Integration tests covering the `Provider → OrderEngine` flow end-to-end (`test_engine_provider_integration.py`, 4/4 PASS).

* Interactive scripts (`test_order_engine.py`, `test_order_dry_run.py`, `test_tsetmc_to_agah.py`) migrated to the new `InstrumentProvider` path; legacy `get_instrument_by_instrument_id(...)` no longer used in these scripts (commit 1a0d2d4).

* `BrokerManager.get_instrument_provider(name)` \u2014 lazy, per-broker cached provider wiring (M4-A). The `AgaahInstrumentProvider` instance reuses the existing `AgaahBroker` instance from `self.brokers[name]`. New unit tests `test_broker_manager.py` 6/6 PASS. COMMITTED as `bdd5a1d`.

* Total unit-test regression (M1\u2013M4-B): 45/45 PASS (38 pre-existing + 7 new).

* `main.py` order workflow (M4-B) \u2014 `current_provider` wired parallel to `current_broker` in `on_broker_changed`; `OrderEngine` instance added; `selected_instrument` stored in `select_symbol`; `send_order()` method added using `OrderEngine.execute_by_ins_code(live=False)`. New unit tests `test_main_order_workflow.py` 7/7 PASS. COMMITTED as `9713360`.



---



## Main Components



### `market/`



Responsible for market and instrument information.



Important files:



```text

market/tsetmc.py

market/symbol_resolver.py

```



### `brokers/`



Contains broker abstractions and broker-specific implementations.



Current broker:



```text

Agah

```



Important files:



```text

brokers/base.py

brokers/agaah.py

brokers/manager.py

brokers/device_info.py

```



### `core/`



Contains broker-independent trading logic.



Current file:



```text

core/order_engine.py

```



### `models/`



Contains domain models:



```text

account.py

broker_instrument.py

instrument.py

order.py

order_validator.py

```



### `input/`



Contains input and Windows keyboard-layout functionality.



### Tests



Current test scripts include:



```text

test_agah_instrument.py

test_agah_login.py

test_broker_dry_run.py

test_order_build.py

test_order_dry_run.py

test_order_engine.py

test_tsetmc_to_agah.py

```



---



## Architecture Rule



The core trading logic must remain independent from individual brokers.



Preferred structure:



```text

Order Engine

     ↓

Broker Interface

     ↓

Broker Adapter

     ↓

Broker API

```



Adding a new broker should normally require implementing a new adapter rather than adding broker-specific conditions throughout the core code.



Avoid designs such as:



```python

if broker == "agah":

    ...

elif broker == "broker_b":

    ...

```



unless there is a documented architectural reason.



---



## Current Broker: Agah



Agah API investigation has identified authentication, account/balance, instrument, market and order-related endpoints.



However, several important details remain under investigation, including:



* TSETMC instrument ID to Agah instrument ID mapping.

* `categoryId`.

* `clientKey`.

* `deviceInfo`.

* Exact order-entry/tradability status.

* Production-safe order-status handling.



Unknown API behavior must be investigated rather than guessed.



---



## TSETMC



TSETMC is currently used for symbol and instrument discovery.



The project supports normalization of Persian/Arabic character variants and wrong Windows keyboard-layout input.



Example previously tested:



```text

آکو

آكو

```



Both should be treated as the same logical symbol where appropriate.



---



## Trading Requirements



The long-term system is expected to support:



* Multiple broker accounts.

* Configurable order timing.

* Precise scheduling around market opening.

* Configurable sending intervals.

* Multiple simultaneous/batched order submissions.

* Countdown and time synchronization.

* Handling halted/not-yet-tradable symbols.

* Available broker balance.

* Daily price limits.

* User-defined quantity.

* Dry-run operation.

* Strong separation between simulation and real order submission.



---



## Safety



The project is a trading application.



Therefore:



* Do not send real orders during ordinary development/testing.

* Prefer dry-run tests.

* Do not use real credentials in source code.

* Never commit passwords, tokens, cookies or other secrets.

* Never assume an API behavior that has not been verified.

* Production-order functionality requires deliberate testing and review.



---



## Git



The repository has a local Git baseline.



Initial commit:



```text

f600a6c — Initial project baseline

```



The Git repository and project documentation are the source of truth, not any individual AI conversation.



---



## Working With This Project



Before changing code, an AI coding agent must:



1. Inspect the repository.

2. Read the project documentation.

3. Understand the existing implementation.

4. Check whether the requested capability already exists.

5. Make the smallest appropriate change.

6. Run relevant tests.

7. Report what changed and why.

8. Record important architectural decisions.



Required project documentation:



```text

AI_PROJECT_MEMORY.md

PROJECT_CONTEXT.md

ARCHITECTURE.md

DECISIONS.md

AGENT_RULES.md

AI_HANDOFF.md

BUG_HISTORY.md

```



---



## Current Development Philosophy



The project should evolve incrementally.



Do not perform large refactors without a clear reason.



Do not replace working components merely because another implementation appears cleaner.



The preferred cycle is:



```text

Inspect

  ↓

Understand

  ↓

Plan

  ↓

Implement

  ↓

Test

  ↓

Review

  ↓

Commit

```



---



## Important



This file is intended to allow a new AI assistant or coding agent to understand the project quickly without relying on previous chat history.



For deeper technical details, read:



```text

AI_PROJECT_MEMORY.md

ARCHITECTURE.md

DECISIONS.md

AGENT_RULES.md

AI_HANDOFF.md

BUG_HISTORY.md

```



