\# Trading Bot — Project Context



\## Project Overview



Trading Bot is a Python project for developing an automated trading application for the Iranian stock market.



The application is designed to work with:



\* TSETMC for market/instrument information.

\* Multiple Iranian brokers through broker-specific adapters.

\* A central, broker-independent order engine.

\* Multiple trading accounts.

\* Precise order scheduling and execution.

\* Safe testing and dry-run workflows.



The project is currently under active development and is \*\*not considered production-ready\*\*.



\---



\## Current Status



The project currently has:



\* TSETMC symbol search and instrument resolution.

\* Persian/Arabic symbol normalization.

\* Windows Persian keyboard-layout handling.

\* Initial broker abstraction.

\* Initial Agah broker implementation.

\* Account, instrument, broker-instrument and order models.

\* Order validation.

\* Initial order engine.

\* Agah API investigation and test scripts.

\* Dry-run/testing infrastructure.

\* Local Git repository with an initial baseline commit.

\* `AgaahInstrumentProvider` for safe `TSETMC insCode → Agah nscId` mapping (Decision 018).

\* `InstrumentLookupError` as the official `InstrumentProvider` contract exception in `brokers/base.py` (Decision 019).

\* `OrderEngine.execute_by_ins_code(...)` that resolves `ins_code` through an `InstrumentProvider` and delegates to the existing `execute(...)` (commit 91bd2b4).

\* Integration tests covering the `Provider → OrderEngine` flow end-to-end (`test_engine_provider_integration.py`, 4/4 PASS).

\* Interactive scripts (`test_order_engine.py`, `test_order_dry_run.py`, `test_tsetmc_to_agah.py`) migrated to the new `InstrumentProvider` path; legacy `get_instrument_by_instrument_id(...)` no longer used in these scripts (commit 1a0d2d4).

\* `BrokerManager.get_instrument_provider(name)` — lazy, per-broker cached provider wiring (M4-A). The `AgaahInstrumentProvider` instance reuses the existing `AgaahBroker` instance from `self.brokers[name]`. New unit tests `test_broker_manager.py` 6/6 PASS. IMPLEMENTED, PENDING REVIEW & COMMIT (no commit yet).

\* Total unit-test regression (M1–M4-A): 38/38 PASS (32 pre-existing + 6 new).

\* `main.py` unchanged in M4-A. M4-B (Order workflow / UI integration) NOT STARTED.



\---



\## Main Components



\### `market/`



Responsible for market and instrument information.



Important files:



```text

market/tsetmc.py

market/symbol\_resolver.py

```



\### `brokers/`



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

brokers/device\_info.py

```



\### `core/`



Contains broker-independent trading logic.



Current file:



```text

core/order\_engine.py

```



\### `models/`



Contains domain models:



```text

account.py

broker\_instrument.py

instrument.py

order.py

order\_validator.py

```



\### `input/`



Contains input and Windows keyboard-layout functionality.



\### Tests



Current test scripts include:



```text

test\_agah\_instrument.py

test\_agah\_login.py

test\_broker\_dry\_run.py

test\_order\_build.py

test\_order\_dry\_run.py

test\_order\_engine.py

test\_tsetmc\_to\_agah.py

```



\---



\## Architecture Rule



The core trading logic must remain independent from individual brokers.



Preferred structure:



```text

Order Engine

&#x20;    ↓

Broker Interface

&#x20;    ↓

Broker Adapter

&#x20;    ↓

Broker API

```



Adding a new broker should normally require implementing a new adapter rather than adding broker-specific conditions throughout the core code.



Avoid designs such as:



```python

if broker == "agah":

&#x20;   ...

elif broker == "broker\_b":

&#x20;   ...

```



unless there is a documented architectural reason.



\---



\## Current Broker: Agah



Agah API investigation has identified authentication, account/balance, instrument, market and order-related endpoints.



However, several important details remain under investigation, including:



\* TSETMC instrument ID to Agah instrument ID mapping.

\* `categoryId`.

\* `clientKey`.

\* `deviceInfo`.

\* Exact order-entry/tradability status.

\* Production-safe order-status handling.



Unknown API behavior must be investigated rather than guessed.



\---



\## TSETMC



TSETMC is currently used for symbol and instrument discovery.



The project supports normalization of Persian/Arabic character variants and wrong Windows keyboard-layout input.



Example previously tested:



```text

آکو

آكو

```



Both should be treated as the same logical symbol where appropriate.



\---



\## Trading Requirements



The long-term system is expected to support:



\* Multiple broker accounts.

\* Configurable order timing.

\* Precise scheduling around market opening.

\* Configurable sending intervals.

\* Multiple simultaneous/batched order submissions.

\* Countdown and time synchronization.

\* Handling halted/not-yet-tradable symbols.

\* Available broker balance.

\* Daily price limits.

\* User-defined quantity.

\* Dry-run operation.

\* Strong separation between simulation and real order submission.



\---



\## Safety



The project is a trading application.



Therefore:



\* Do not send real orders during ordinary development/testing.

\* Prefer dry-run tests.

\* Do not use real credentials in source code.

\* Never commit passwords, tokens, cookies or other secrets.

\* Never assume an API behavior that has not been verified.

\* Production-order functionality requires deliberate testing and review.



\---



\## Git



The repository has a local Git baseline.



Initial commit:



```text

f600a6c — Initial project baseline

```



The Git repository and project documentation are the source of truth, not any individual AI conversation.



\---



\## Working With This Project



Before changing code, an AI coding agent must:



1\. Inspect the repository.

2\. Read the project documentation.

3\. Understand the existing implementation.

4\. Check whether the requested capability already exists.

5\. Make the smallest appropriate change.

6\. Run relevant tests.

7\. Report what changed and why.

8\. Record important architectural decisions.



Required project documentation:



```text

AI\_PROJECT\_MEMORY.md

PROJECT\_CONTEXT.md

ARCHITECTURE.md

DECISIONS.md

AGENT\_RULES.md

AI\_HANDOFF.md

BUG\_HISTORY.md

```



\---



\## Current Development Philosophy



The project should evolve incrementally.



Do not perform large refactors without a clear reason.



Do not replace working components merely because another implementation appears cleaner.



The preferred cycle is:



```text

Inspect

&#x20; ↓

Understand

&#x20; ↓

Plan

&#x20; ↓

Implement

&#x20; ↓

Test

&#x20; ↓

Review

&#x20; ↓

Commit

```



\---



\## Important



This file is intended to allow a new AI assistant or coding agent to understand the project quickly without relying on previous chat history.



For deeper technical details, read:



```text

AI\_PROJECT\_MEMORY.md

ARCHITECTURE.md

DECISIONS.md

AGENT\_RULES.md

AI\_HANDOFF.md

BUG\_HISTORY.md

```



