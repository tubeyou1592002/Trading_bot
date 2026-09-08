\# Trading Bot — AI Project Memory



\## 1. Project Identity



\*\*Project name:\*\* Trading Bot



\*\*Language:\*\* Python



\*\*Platform:\*\* Windows



\*\*IDE:\*\* VS Code



\*\*Python version:\*\* 3.13.x



\*\*Project path:\*\*

`C:\\Users\\hp\\Documents\\Trading\_bot`



\*\*Current Git baseline:\*\*

`8cfc4d4 — M6-E Documentation Checkpoint (docs: update project state after M6-E, Architect approved, pushed)`



\---



\## 2. Project Goal



The project is a modular Python trading bot for the Iranian stock market.



The main objective is to:



\* Connect to multiple brokers/accounts.

\* Resolve and monitor Iranian stock symbols.

\* Retrieve market/instrument information from TSETMC.

\* Prepare and send orders through broker APIs.

\* Support precise order sending around market opening time.

\* Support multiple broker adapters.

\* Provide safe dry-run/testing mechanisms before real order submission.

\* Eventually support precise timing, server time synchronization, countdown, batching, and multiple accounts.

\* Keep broker-specific API implementation isolated from the core trading logic.



The project must be designed so that different brokers can be added without rewriting the core trading engine.

---

## 2b. Project Goal — Low-Latency, Configurable Order Dispatch

The long-term objective of the project is to build a **Low-Latency, Configurable Order Dispatch** system. The goal is to minimize the time and variance between a dispatchable event and the moment an order enters the broker infrastructure, while keeping the system fully configurable and safe.

### Core Dispatch Engine

The system is a **dispatch engine**, not merely an order sender. It must:

* Accept **pre-ready (pre-submitted / pre-validated) orders** so that no preparation work happens on the dispatch hot path.
* Allow the user to configure the **start time** and **end time** of order sending.
* Allow the user to configure the **interval / gap between orders**.
* Support sending to:
  * One account / one broker
  * Multiple accounts / one broker
  * Multiple accounts / multiple brokers
* Support **Event-Driven Dispatch**: orders may be triggered immediately when an event is observed.
  * Example: start sending immediately after a **Permitted** or **Permitted-Reserved** signal.
  * In Event-Driven mode, the system may continue tracking until it receives a confirmation / token indicating the order has been registered in the trading core.
* Minimize **latency** and **variance** between a dispatchable event and order entry into the broker infrastructure.

### Configuration, Not Hard-Coded Constants

All timing-related values are **user-configurable** and must not be treated as fixed architectural constants:

* Example values such as `50ms` or `10 seconds` are **illustrative only**; the actual values must be configurable by the user.
* The architecture must be ready, in the future, to measure latency across individual stages (network, VPS, broker API) so that bottlenecks can be identified and optimized.

### Explicit Non-Guarantee

The system is **NOT a guaranteed order-positioning system** for the trading core queue. The goal is to minimize latency and provide the best practical conditions for early order entry; it does not guarantee that an order will obtain a position in the trading core queue.

### Validation / Preflight Architecture

M6-A through M6-E (identity check, trading-state gate, price/quantity constraints, account cash + BUY capacity, portfolio quantity + SELL gate, unified capacity preflight) **must be preserved** and must not be bypassed in future architecture. However, the future architecture should perform as much preparation and validation as possible **before the dispatch moment**, so that the final dispatch path remains as low-latency as possible.



\---



\## 3. Current Architecture



Current high-level architecture:



```text

User

&#x20; ↓

UI / Application

&#x20; ↓

Core Trading / Order Engine

&#x20; ↓

Broker Interface

&#x20; ↓

Broker Adapter

&#x20; ↓

Broker API

```



Market data path:



```text

User symbol input

&#x20;     ↓

Symbol Resolver

&#x20;     ↓

TSETMC

&#x20;     ↓

Instrument information

&#x20;     ↓

Broker-specific instrument mapping

```



Current project structure:



```text

Trading\_bot/

├── main.py

├── brokers/

│   ├── \_\_init\_\_.py

│   ├── agaah.py

│   ├── base.py

│   ├── device\_info.py

│   └── manager.py

│

├── core/

│   └── order\_engine.py

│

├── input/

│   ├── \_\_init\_\_.py

│   └── keyboard\_layout.py

│

├── market/

│   ├── \_\_init\_\_.py

│   ├── symbol\_resolver.py

│   └── tsetmc.py

│

├── models/

│   ├── \_\_init\_\_.py

│   ├── account.py

│   ├── broker\_instrument.py

│   ├── instrument.py

│   ├── order.py

│   └── order\_validator.py

│

└── tests / test scripts

```



\---



\## 4. Current Broker



Primary broker under development:



\*\*Agah\*\*



The broker implementation is currently located under:



```text

brokers/agaah.py

```



The project is intended to support additional brokers later.



Broker-specific implementation must remain isolated.



\---



\## 5. Agah API Knowledge



Base API:



```text

https://tseonlineapi.agah.com/api/v1

```



Online trading website:



```text

https://online.agah.com

```



Protocol:



```text

HTTPS

JSON

```



Authentication uses:



```text

Authorization: Bearer <token>

UserIdentifier: <identifier>

```



\### Captcha



Endpoint:



```text

GET /captcha/getcaptcha

```



The response contains:



\* captcha image as Base64

\* captchaId



\### Authentication



Endpoint:



```text

POST /users/authenticate

```



Known request information includes:



\* userName

\* password

\* captcha

\* captchaId

\* clientKey

\* deviceInfo



Response includes:



\* accessToken

\* refreshToken

\* userIdentifier



The exact generation of `clientKey` and `deviceInfo` may require further investigation of the browser implementation.



\### Financial Account / Balance



Endpoint:



```text

GET /financialaccounts/balances

```



Known fields include:



\* lastBalance

\* tradableBalanceT1

\* tradableBalanceT2

\* block

\* credit

\* settlementDateT0

\* settlementDateT1

\* settlementDateT2



\### Order



Endpoint:



```text

POST /order

```



Known request fields include:



\* nscId

\* orderSide

\* price

\* quantity

\* validityType

\* categoryId

\* bankAccountId

\* creationDate



Known order side:



```text

1 = Buy

2 = Sell

```



Price is sent in Rial, therefore Toman price generally needs conversion:



```text

Rial = Toman × 10

```



Response includes:



```text

decisionId

```



\### Live Decisions



Endpoint:



```text

GET /order/liveDecisions

```



During testing while market was closed, the response was empty.



\### Instrument Live Segmentation



Endpoint:



```text

GET /instruments/live-segmentation/{nscId}

```



\### Market Indexes



Endpoint:



```text

GET /v2/markets/marketindexes?nscIds=...

```



\---



\## 6. TSETMC



TSETMC is currently used for market/instrument discovery.



Instrument search endpoint used:



```text

https://cdn.tsetmc.com/api/Instrument/GetInstrumentSearch/{query}

```



Example previously tested:



Symbol:



```text

آكو

```



Name:



```text

آكو باتري ايرانيان

```



TSETMC `insCode`:



```text

60235881999727383

```



ISIN:



```text

IRO1ACCO0001

```



Market:



```text

بازار بورس

```



The project contains:



```text

market/tsetmc.py

market/symbol\_resolver.py

```



\---



\## 7. Persian Input / Keyboard Handling



The project supports Persian symbol input normalization.



Important requirements:



\* Normalize Persian and Arabic character variations.

\* Handle symbols such as `آکو` and `آكو`.

\* Support cases where the user types using the wrong Windows keyboard layout.

\* The keyboard-layout functionality is implemented under:



```text

input/keyboard\_layout.py

```



\---



\## 8. Current Models



The project currently contains models for:



```text

models/account.py

models/broker\_instrument.py

models/instrument.py

models/order.py

models/order\_validator.py

```



These models are intended to separate domain data from broker-specific API implementation.



\---



\## 9. Order Engine



Core order logic is currently located at:



```text

core/order\_engine.py

```



The core engine should remain broker-independent.



The preferred design is:



```text

Order Engine

&#x20;     ↓

Broker Interface

&#x20;     ↓

Agah Adapter

```



and later:



```text

Order Engine

&#x20;     ↓

Broker Interface

&#x20;     ├── Agah

&#x20;     ├── Broker B

&#x20;     └── Broker C

```



The order engine exposes two execution entry points:



\* `OrderEngine.execute(broker, order, instrument, account, live=False)` — accepts a fully resolved `BrokerInstrument` and an `Order`; performs validation, trading-state check, and dry-run/live dispatch.

\* `OrderEngine.execute_by_ins_code(broker, provider, ins_code, order, account, live=False)` — accepts a TSETMC `ins_code` together with an `InstrumentProvider`; calls `provider.get_instrument(ins_code)` to resolve the `BrokerInstrument`, checks `nsc_id` consistency without overwriting, and then delegates to the existing `execute(...)`. This is the broker-independent way to enter the engine from a TSETMC `ins_code`.



Business logic must not become filled with:



```python

if broker == "agah":

```



Broker-specific behavior belongs inside broker adapters.



\---



\## 10. Planned Features



The following features are part of the intended project roadmap.



\### Multiple accounts



Allow the user to configure multiple trading accounts and brokers.



\### Precise order timing



Support:



\* configurable start time

\* configurable end time

\* configurable interval

\* precise timestamp scheduling

\* batch sending

\* countdown timer

\* server time synchronization



Example target:



```text

08:44:56.000

```



followed by order submission around market opening.



\### Halted symbols



For a halted/not-tradable instrument, the UI should eventually allow the user to choose behavior such as:



```text

Wait until symbol becomes tradable

```



or:



```text

Send when order can be registered by the trading core

```



The exact implementation must be based on verified market/broker behavior.



\### Buying power



Display available tradable balance from the broker.



\### Daily price limits



Display relevant daily maximum/minimum price information.



\### Quantity



Allow the user to specify order quantity.



\### Multi-broker execution



Eventually allow the same trading instruction to be distributed across several broker accounts.



Example concept:



```text

Broker A → 20M

Broker B → 25M

Broker C → 5M

```



\---



\## 11. Important Technical Unknowns



These items require further investigation and must not be guessed.



\### TSETMC insCode → Agah nscId — Resolved

The mapping from a TSETMC `insCode` to an Agah `nscId` is no longer an open unknown. It is implemented by `AgaahInstrumentProvider` (in `brokers/agaah/instrument_provider.py`) using the verified path: `TSETMC.get_info(ins_code) → Instrument.symbol → Agah /instruments/all?query=<symbol>&count=50 → for each candidate nscId: broker.get_instrument(nscId) → match tse_id == ins_code`.

The official contract exception for lookup failure is `InstrumentLookupError`, defined in `brokers/base.py` (Decision 019). `AgaahInstrumentProvider` raises this exception; `OrderEngine.execute_by_ins_code` catches it and safely blocks order submission.

Resolved as of Milestone 1 (commit 2020f92). The unit tests `test_instrument_provider.py` and `test_engine_provider_integration.py` exercise this path end-to-end without network access.

Note: resolving the mapping does NOT resolve the other Agah-specific unknowns below. Tradability and order-API behavior remain unverified.



### Agah categoryId



The correct source/value must be verified.



Do not assume that a sample value is universally valid.



\### Agah clientKey



The exact generation/source needs verification.



\### Agah deviceInfo



The exact generation/encryption mechanism needs verification.



\### Order status / instrument tradability



The Agah API endpoint for exact order-entry status has not yet been fully identified.



TSETMC instrument state may be useful, but this must be verified before becoming production logic.



\---



\## 12. Security Rules



Never store the following in Git:



\* passwords

\* access tokens

\* refresh tokens

\* cookies

\* real authentication headers

\* captcha data

\* private API keys

\* personal secrets



The project `.gitignore` already excludes:



```text

captcha.png

client\_id.txt

.env

.env.\*

```



Secrets must be supplied through secure configuration/environment mechanisms.



\---



\## 13. Testing Philosophy



The project contains several test scripts, including:



```text

test\_agah\_instrument.py

test\_agah\_login.py

test\_broker\_dry\_run.py

test\_order\_build.py

test\_order\_dry\_run.py

test\_order\_engine.py

test\_tsetmc\_to\_agah.py

```



Before real trading behavior is enabled:



1\. Test data models.

2\. Test order construction.

3\. Test validation.

4\. Test broker mapping.

5\. Test API authentication.

6\. Test dry-run order flow.

7\. Test order engine.

8\. Only then consider controlled real-order testing.



No agent should send a real trading order merely to test whether the API works.



\---



\## 14. AI Development Model



The project is intended to support multiple AI coding agents.



Possible agents may include:



\* ChatGPT

\* Genspark

\* Claude

\* Codex

\* Cline

\* Roo Code

\* other coding agents



No individual AI agent is the source of truth.



The source of truth is:



```text

Git repository

\+

Project documentation

\+

Tests

\+

Git history

```



AI agents are replaceable.



\---



\## 15. Roles



\### User



The user is:



\* Product Owner

\* final decision-maker

\* real-world tester

\* responsible for approving risky/production actions



\### ChatGPT / Architect



The architecture/reasoning assistant is responsible for:



\* architecture

\* technical analysis

\* design decisions

\* reviewing implementation strategy

\* maintaining project continuity

\* helping document important decisions



\### Coding Agent



The coding agent is responsible for:



\* inspecting the repository

\* editing files

\* implementing approved changes

\* running tests

\* debugging

\* reporting changes

\* avoiding unnecessary architectural changes



\---



\## 16. Agent Independence



A new AI agent must not assume previous conversation context exists.



Before making changes it should read:



```text

AI\_PROJECT\_MEMORY.md

PROJECT\_CONTEXT.md

ARCHITECTURE.md

DECISIONS.md

AGENT\_RULES.md

AI\_HANDOFF.md

BUG\_HISTORY.md

```



If any of these files are missing, the agent should inspect the repository before making architectural assumptions.



\---



\## 17. Current Git State



Git has been initialized locally.



Current branch:



```text

master

```



Initial baseline commit:



```text

f600a6c

Initial project baseline

```



At the time this document is created, the baseline is considered the known starting point of the project.



\---



\## 18. Development Principle



Do not rewrite working code simply because another implementation looks cleaner.



Preferred process:



```text

Inspect

&#x20; ↓

Understand

&#x20; ↓

Plan

&#x20; ↓

Implement minimally

&#x20; ↓

Test

&#x20; ↓

Review

&#x20; ↓

Commit

```



Changes should be incremental and reversible.



\---



\## 19. Current Immediate Goal



The immediate goal is to establish durable project documentation and a reliable handoff system before introducing additional AI coding agents or making major architectural changes.



Next documentation files:



```text

PROJECT\_CONTEXT.md

ARCHITECTURE.md

DECISIONS.md

AGENT\_RULES.md

AI\_HANDOFF.md

BUG\_HISTORY.md

```



After documentation is established:



```text

Local Git

&#x20;   ↓

GitHub Private Repository

&#x20;   ↓

AI Coding Agent

&#x20;   ↓

Controlled development

```



\---



## 19b. Milestone 4-A — BrokerManager → InstrumentProvider (Implemented, Committed as bdd5a1d)



### Completed (M1–M3, M4-A, documentation checkpoint)



```text

M1 — Completed

M2 — Completed

M3 — Completed
M4-A — Committed as bdd5a1d

M4-A — Implemented, Committed as bdd5a1d
Documentation checkpoint — bdd5a1d

```



### Current (M4-B)



```text

M4-B — main.py / Order Workflow

Status: COMMITTED as 9713360

Tests: 7/7 (test_main_order_workflow.py)

Regression: 45/45 PASS (38 pre-existing + 7 new)

```



Implementation summary:



\* `BrokerManager.get_instrument_provider(name: str) -> InstrumentProvider` was added in `brokers/manager.py`.



\* The provider is constructed lazily on the first call and cached per broker in `self.providers[name]`.



\* The provider wraps the **same** `AgaahBroker` instance stored in `self.brokers[name]`. The manager does not construct a fresh broker for the provider.



\* `BrokerManager` remains structurally Agah-specific. No factory map, no plugin architecture, no registry, no DI framework was introduced.



\* `main.py` is **not** a consumer of the provider in M4-A.



### Contract of `BrokerManager.get_instrument_provider(name)`



```text

get_instrument_provider(name)

    ↓

validate broker exists                  (else ValueError)

    ↓

return cached provider if available

    ↓

otherwise use existing broker instance  (from self.brokers[name])

    ↓

create provider lazily                  (AgaahInstrumentProvider(broker))

    ↓

cache provider                          (self.providers[name] = provider)

    ↓

return provider

```



### Important boundaries (M4-A)



\* `main.py` unchanged.



\* `OrderEngine` unchanged.



\* `OrderEngine.execute_by_ins_code` unchanged.



\* `AgaahInstrumentProvider` unchanged.



\* Mapping logic unchanged.



\* `InstrumentLookupError` unchanged.



\* `live_trading_enabled` lock unchanged.



\* No real order was submitted.



\* No network-based test was added.



\* No login / captcha was performed.



\* No generic factory / plugin architecture was added.



\* No legacy lookup was removed.

### Important boundaries (M4-B)

M4-B changes ONLY `main.py` (and adds `test_main_order_workflow.py`). The following remain unchanged:

\* `OrderEngine`, `OrderEngine.execute_by_ins_code`, `AgaahInstrumentProvider`, mapping logic, `InstrumentLookupError`, `live_trading_enabled` lock — all unchanged.

\* No new business logic in `main.py`; `send_order()` is pure orchestration (guard checks, UI→domain conversion, delegation to `OrderEngine.execute_by_ins_code`).

\* `Account` is obtained from `broker.get_account()` (real Broker API) — no placeholder or mock.

\* `live=False` is hard-coded; no live order path is reachable.

\* No scheduling/timer, no login automation, no multi-account management added.

\* `core/`, `brokers/base.py`, `brokers/agaah/`, `models/`, `market/`, `input/` — all unchanged.

### Next decision point

M4-B is committed (9713360), all 45/45 tests pass. The next milestones will be defined by a separate user instruction:

\* implement real `get_trading_state` for Agah (Decision 017) after identifying a verified source;

\* add scheduling/timer for time-based order submission;

\* add multi-account / session lifecycle management.

### M5 — TSETMC Trading State Integration (IMPLEMENTED)

پیاده‌سازی شده و تست شده است:

\* `market/tsetmc.py`: متد `get_trading_state(ins_code)` از endpoint `https://cdn.tsetmc.com/api/MarketData/GetInstrumentStateAll/{ins_code}`
\* `brokers/agaah/broker.py`: `get_trading_state(nsc_id)` از TSETMC دریافت می‌کند؛ ابتدا `nsc_id` از طریق `broker.get_instrument(nsc_id)` به `tse_id` (که برابر TSETMC `insCode` است) تبدیل می‌شود؛ سپس identity بررسی می‌شود؛ و آخرین وضعیت (بیشترین `dEven`/`hEven`) انتخاب می‌شود؛ `cEtaval` را مطابق Decision 020 می‌نگاشت و `TradingState` مناسب برمی‌گرداند.
\* `test_trading_state.py`: 16 تست جدید؛ 16/16 PASS
\* سایر وضعیت‌ها (I, AG, AS, IG, IS, IR) و unknown/error/timeout/network → BLOCKED / UNVERIFIED
\* `A ` و `AR` → Order submission ALLOWED
\* identity mismatch (insCode در پاسخ با درخواست یکسان نیست) → UNVERIFIED / BLOCK
\* Regression: 60/60 PASS (45 پیشین + 16 جدید + 1 به‌روزرسانی شده در test_engine_interface.py)
\* هیچ real order ارسال نشده است
\* Committed as `ca3e2cbf` — pushed to origin/master

### M6-A — Instrument Identity + Trading-State Gate (COMPLETED / Architect Approved)

#### Implementation Summary
- **File modified:** `core/order_engine.py`
  - Added explicit identity check in `prepare()`: if `order.nsc_id != instrument.nsc_id` → `BLOCKED` (no overwrite).
  - Enforced fail-closed policy: `UNVERIFIED` (Unknown / Missing / Error / Unverified) → `BLOCKED` in `OrderEngine.prepare()`.
- **Tests added:** `test_m6a_preflight.py` — 8 tests covering:
  - valid identity + allowed state → READY
  - identity mismatch → BLOCKED
  - `A ` / `AR` → ALLOWED (via VERIFIED_TRADABLE)
  - unsupported state → BLOCKED
  - missing/unknown/error state → BLOCKED
- **Tests updated:** `test_engine_interface.py` (2 tests), `test_main_order_workflow.py` (1 test) — expectations updated for new `BLOCKED` behavior.
- **M5 contract:** Unchanged. `brokers/agaah/broker.py`, `market/tsetmc.py`, `models/trading_state.py` were not modified.

#### Test Results (M6-A)
- `test_m6a_preflight.py`: 8/8 PASS
- `test_engine_interface.py`: 17/17 PASS
- `test_main_order_workflow.py`: 7/7 PASS
- `test_trading_state.py` (M5 regression): 16/16 PASS
- `test_engine_provider_integration.py`: 4/4 PASS
- `test_broker_manager.py`: 6/6 PASS
- `test_instrument_provider.py`: 11/11 PASS
- **Total related regression: 69/69 PASS**

#### Behavioral Contract (M6-A)
```
Broker returns UNVERIFIED
    └─> OrderEngine.prepare()
            └─> RETURN BLOCKED (mode="BLOCKED")

Broker returns valid TradingState (verified + order_entry_allowed)
    └─> OrderEngine.prepare()
            └─> RETURN READY (after OrderValidator)
```

#### Out-of-Scope for M6-A
The following are explicitly **not** part of M6-A and remain for M6-B or later:
- Account Cash Availability (`tradableBalanceT1`)
- Buy Capacity via Agah (`calculatedquantity`)
- Portfolio Quantity for Sell (`numberOfShares`)
- Instrument Constraints (price thresholds, tick, min/max qty)
- Order Splitting
- Scheduler / Retry / Recovery

---

### M6-B — Instrument Price / Quantity Preflight Constraints (COMPLETED / Architect Approved)

#### Implementation Summary
- **Files modified:**
  - `models/order_validator.py` — Added fail-closed checks for required price/quantity constraints:
    - `lower_price_threshold`, `upper_price_threshold`, `fixed_price_tick`, `minimum_order_quantity`, `lot_size`, `maximum_order_quantity_for_buy`, `maximum_order_quantity_for_sell` — all now BLOCK if `None`/missing.
    - Added `lotSize` validation: `order.quantity % lot_size == 0`.
  - `core/order_engine.py` — `OrderValidationError` now maps to `mode="BLOCKED"` (fail-closed).
- **Tests added:** `test_m6b_preflight.py` — 21 tests covering:
  - price below/above thresholds → BLOCKED
  - valid price → READY
  - invalid tick → BLOCKED
  - zero/negative quantity → BLOCKED
  - below minimum quantity → BLOCKED
  - invalid lot size → BLOCKED
  - BUY above max buy → BLOCKED
  - SELL above max sell → BLOCKED
  - valid BUY/SELL quantity → READY
  - missing/None constraints → BLOCKED (7 tests)
- **Tests updated:** `test_engine_interface.py` (1 test) — expectation updated for `BLOCKED` behavior.
- **M5/M6-A contract:** Unchanged.

#### Test Results (M6-B)
- `test_m6b_preflight.py`: 21/21 PASS
- `test_engine_interface.py`: 17/17 PASS
- `test_m6a_preflight.py`: 8/8 PASS
- `test_trading_state.py` (M5 regression): 16/16 PASS
- `test_engine_provider_integration.py`: 4/4 PASS
- `test_broker_manager.py`: 6/6 PASS
- `test_instrument_provider.py`: 11/11 PASS
- `test_main_order_workflow.py`: 7/7 PASS
- **Total related regression: 91/91 PASS**

#### Behavioral Contract (M6-B)
```
Missing/Unknown required constraint (lower/upper threshold, tick, min qty, lot size, max buy/sell)
    └─> OrderValidator raises OrderValidationError
            └─> OrderEngine.prepare()
                    └─> RETURN BLOCKED (mode="BLOCKED")

Invalid value (price out of range, bad tick, qty below min, above max, not multiple of lot)
    └─> OrderValidator raises OrderValidationError
            └─> OrderEngine.prepare()
                    └─> RETURN BLOCKED (mode="BLOCKED")

Valid + Known constraints
    └─> OrderValidator passes
            └─> OrderEngine.prepare()
                    └─> RETURN READY (after trading-state gate)
```

#### Out-of-Scope for M6-B
The following are explicitly **not** part of M6-B and remain for M6-C or later:
- Account Cash Availability (`tradableBalanceT1`)
- Buy Capacity via Agah (`calculatedquantity`)
- Portfolio Quantity for Sell (`numberOfShares`)
- Order Splitting
- Scheduler / Retry / Recovery

#### Note on `baseQuantity`
- `baseQuantity` does not exist in the repository (`BrokerInstrument`, API mappings, or documentation).
- Only `lot_size` exists and was validated in M6-B.
- No new field or API was added for `baseQuantity`.

---

### M6-C — Account Cash + BUY Capacity Validation (COMPLETED / Architect Approved)

#### Implementation Summary
- **Files modified:**
  - `models/order_validator.py` — Added fail-closed checks for Account Cash in BUY path:
    - `tradable_balance_t1` must be numeric (`int`/`float`), not `bool`, not `None`, not negative.
    - `required_cash = order.price * order.quantity` must be `<= tradable_balance_t1`.
  - `brokers/base.py` — Added concrete `get_buy_capacity()` method to `Broker` ABC (default: `NotImplementedError` → fail-closed for brokers that don't override).
  - `brokers/agaah/broker.py` — Implemented `get_buy_capacity()` calling `GET /api/v1/trades/calculatedquantity` with params `nscId`, `sideCode`, `fund`, `price`; validates `isSuccess`, `data` presence/numeric/non-negative; raises on any API/HTTP/network failure.
  - `core/order_engine.py` — Added `BUY` import and BUY capacity gate in `prepare()`:
    - `fund = account.tradable_balance_t1`.
    - Missing/invalid/negative `fund` → `BLOCKED`.
    - API call failure → `BLOCKED` (fail-closed).
    - `order.quantity > capacity` → `BLOCKED`.
- **Tests added:** `test_m6c_preflight.py` — 16 tests covering:
  - Account Cash (6 tests):
    - valid sufficient cash → READY
    - insufficient cash → BLOCKED
    - missing `tradableBalanceT1` → BLOCKED
    - malformed/string balance → BLOCKED
    - negative balance → BLOCKED
    - `bool` balance → BLOCKED
  - BUY Capacity (10 tests):
    - valid sufficient capacity → READY
    - insufficient capacity → BLOCKED
    - `data` == None → BLOCKED
    - missing `data` → BLOCKED
    - `isSuccess == false` → BLOCKED
    - non-numeric `data` → BLOCKED
    - API/HTTP failure → BLOCKED
    - timeout/network failure → BLOCKED
    - connection error → BLOCKED
    - SELL order skips capacity gate → READY
- **Tests updated:** `test_m6a_preflight.py`, `test_m6b_preflight.py`, `test_engine_interface.py`, `test_engine_provider_integration.py`, `test_main_order_workflow.py` — added `get_buy_capacity` to FakeBroker implementations.
- **BUY Capacity via Agah (`calculatedquantity`):** IMPLEMENTED
  - endpoint: `GET /api/v1/trades/calculatedquantity`
  - params: `nscId`, `sideCode`, `fund` (= `tradable_balance_t1`), `price`
  - response field: `data` = Agah-calculated BUY capacity
  - Architect-approved response contract (verified via Chrome DevTools)
  - No new fields added to `Account`/`Order`/`BrokerInstrument`

#### Test Results (M6-C Account Cash + BUY Capacity)
- `test_m6c_preflight.py`: 16/16 PASS
- `test_m6b_preflight.py`: 21/21 PASS
- `test_m6a_preflight.py`: 8/8 PASS
- `test_trading_state.py` (M5 regression): 16/16 PASS
- `test_engine_interface.py`: 17/17 PASS
- `test_engine_provider_integration.py`: 4/4 PASS
- `test_broker_manager.py`: 6/6 PASS
- `test_instrument_provider.py`: 11/11 PASS
- `test_main_order_workflow.py`: 7/7 PASS
- **Total related regression: 106/106 PASS**

#### Behavioral Contract (M6-C Account Cash + BUY Capacity)
```
BUY path:
    tradable_balance_t1 is None/missing
        └─> OrderValidator raises OrderValidationError
                └─> OrderEngine.prepare()
                        └─> RETURN BLOCKED (mode="BLOCKED")

    tradable_balance_t1 is bool or non-numeric
        └─> OrderValidator raises OrderValidationError
                └─> OrderEngine.prepare()
                        └─> RETURN BLOCKED (mode="BLOCKED")

    tradable_balance_t1 is negative
        └─> OrderValidator raises OrderValidationError
                └─> OrderEngine.prepare()
                        └─> RETURN BLOCKED (mode="BLOCKED")

    required_cash > tradable_balance_t1
        └─> OrderValidator raises OrderValidationError
                └─> OrderEngine.prepare()
                        └─> RETURN BLOCKED (mode="BLOCKED")

    tradable_balance_t1 valid + cash sufficient
        └─> OrderValidator passes
                └─> OrderEngine.prepare()
                        └─> BUY Capacity gate:
                            fund = tradable_balance_t1
                            broker.get_buy_capacity(nscId, sideCode, fund, price)
                                ├─ any API/HTTP/network error → BLOCKED
                                ├─ isSuccess != true → BLOCKED
                                ├─ data missing/None → BLOCKED
                                ├─ data non-numeric → BLOCKED
                                ├─ data < 0 → BLOCKED
                                └─ capacity >= 0 → compare quantity:
                                    order.quantity > capacity → BLOCKED
                                    order.quantity <= capacity → continue
                                        └─> RETURN READY
```

#### Out-of-Scope for M6-C
The following are explicitly **not** part of M6-C and remain blocked/pending:
- Portfolio Quantity for Sell (`numberOfShares`)
- Unified BUY/SELL Preflight
- Order Splitting
- Scheduler / Retry / Recovery

---

### M6-D — Portfolio Quantity / SELL Gate (COMPLETED / Architect Approved)

#### Implementation Summary
- **Files modified:**
  - `brokers/base.py` — Added `get_sell_capacity()` to `Broker` ABC (default: `NotImplementedError` → fail-closed).
  - `brokers/agaah/broker.py` — Implemented `get_sell_capacity()` calling `GET /api/v1/portfolio`, parsing `portfolio.numberOfShares`, with full validation (isSuccess, portfolio presence, numeric, non-negative) and fail-closed behavior on any API/HTTP/network failure.
  - `core/order_engine.py` — Added `SELL` import and SELL capacity gate in `prepare()` after the BUY gate: calls `broker.get_sell_capacity()`, `BLOCKED` on any exception or insufficient capacity (`order.quantity > capacity`).
- **Tests added:** `test_m6d_preflight.py` — 15 tests covering:
  - sufficient capacity → READY
  - exact quantity → READY
  - insufficient capacity → BLOCKED
  - zero quantity → BLOCKED (by existing OrderValidator)
  - API failure → BLOCKED
  - missing numberOfShares → BLOCKED
  - missing portfolio → BLOCKED
  - non-numeric → BLOCKED
  - timeout → BLOCKED
  - connection error → BLOCKED
  - negative → BLOCKED
  - BUY order skips SELL capacity gate → READY
  - SELL gate does not break BUY path → READY
  - correct arguments verification
  - M6-B max_sell check fires before SELL capacity gate → BLOCKED
- **Tests updated:** `test_engine_interface.py`, `test_m6a_preflight.py`, `test_m6b_preflight.py`, `test_m6c_preflight.py`, `test_engine_provider_integration.py`, `test_main_order_workflow.py` — added `get_sell_capacity` to FakeBroker implementations.

#### Test Results (M6-D)
- `test_m6d_preflight.py`: 15/15 PASS
- `test_m6c_preflight.py`: 16/16 PASS
- `test_m6b_preflight.py`: 21/21 PASS
- `test_m6a_preflight.py`: 8/8 PASS
- `test_trading_state.py` (M5 regression): 16/16 PASS
- `test_engine_interface.py`: 17/17 PASS
- `test_engine_provider_integration.py`: 4/4 PASS
- `test_broker_manager.py`: 6/6 PASS
- `test_instrument_provider.py`: 11/11 PASS
- `test_main_order_workflow.py`: 7/7 PASS
- **Total related regression: 123/123 PASS** (106 previous + 15 new M6-D + 2 updated interface tests)

#### Behavioral Contract (M6-D)
```
SELL path (after M6-A identity/trading-state gate, after M6-B price/quantity constraints):
    order.quantity > 0 and side == SELL
        └─> OrderEngine.prepare()
                └─> SELL Capacity gate:
                    broker.get_sell_capacity(nsc_id, side_code, fund=None, price)
                        ├─ any API/HTTP/network error → BLOCKED
                        ├─ isSuccess != true → BLOCKED
                        ├─ portfolio missing → BLOCKED
                        ├─ portfolio.numberOfShares missing/None → BLOCKED
                        ├─ portfolio.numberOfShares non-numeric → BLOCKED
                        ├─ portfolio.numberOfShares < 0 → BLOCKED
                        └─ capacity >= 0 → compare quantity:
                            order.quantity > capacity → BLOCKED
                            order.quantity <= capacity → continue
                                └─> RETURN READY

BUY path:
    get_sell_capacity is NEVER called (BUY gate uses get_buy_capacity only)
```

#### M6-D Contract Details
- **Endpoint:** `GET /api/v1/portfolio` (Architect-verified)
- **Quantity field:** `portfolio.numberOfShares`
- **Rule:** SELL allowed when `quantity <= numberOfShares`
- **Missing/invalid/API failure → BLOCKED** (fail-closed)
- `numberOfShares` is used only as the SELL gate bound; it is NOT an independent sellable quantity claim.

#### Out-of-Scope for M6-D
The following are explicitly **not** part of M6-D and remain blocked/pending:
- Unified BUY/SELL Preflight
- Order Splitting
- Scheduler / Retry / Recovery

---

### M6-E — Unified BUY/SELL Capacity Preflight (COMPLETED / Architect Approved)

#### Implementation Summary
- **Files modified:**
  - `core/order_engine.py` — Refactored the two separate `if order.side == BUY` / `if order.side == SELL` capacity blocks in `prepare()` into a single unified capacity gate:
    - Both BUY and SELL capacity calls now route through a shared `_check_capacity()` static method.
    - `_check_capacity()` encapsulates the common exception handling (`Exception → BLOCKED`, fail-closed) and quantity comparison (`order.quantity > capacity → BLOCKED`).
    - BUY path: pre-validates `fund = account.tradable_balance_t1` (None/bool/non-numeric/negative checks), then calls `broker.get_buy_capacity(nsc_id, side_code, fund, price)`.
    - SELL path: calls `broker.get_sell_capacity(nsc_id, side_code, fund=None, price)` directly.
    - Side selection uses `capacity_label` ("خرید" / "فروش") to preserve exact error messages.
- **Tests added:** None (refactor only — no new behavior).
- **Tests updated:** None (all 123 existing tests continue to pass without modification).
- **No architectural decisions added.**

#### Unified Structure
```
OrderEngine.prepare() capacity gate:
    if order.side == BUY:
        fund = account.tradable_balance_t1
        validate fund (None / bool / negative / non-numeric → BLOCKED)
        capacity_fn = lambda: broker.get_buy_capacity(nsc_id, side, fund, price)
        capacity_label = "خرید"
    else:  # SELL (guaranteed by OrderValidator: side ∈ {BUY, SELL})
        capacity_fn = lambda: broker.get_sell_capacity(nsc_id, side, fund=None, price)
        capacity_label = "فروش"

    → _check_capacity(order, broker_name, capacity_fn, capacity_label)
        ├─ capacity_fn() raises Exception → BLOCKED (fail-closed)
        ├─ order.quantity > capacity → BLOCKED
        └─ order.quantity <= capacity → fall through to Ready
```

#### Behavior Preserved
- **Gate ordering:** Identity (M6-A) → Trading State (M5/M6-A) → OrderValidator (M6-B) → Capacity (M6-C/M6-D unified) → Ready.
- **Fail-closed policy:** Any exception from `get_buy_capacity` or `get_sell_capacity` → `BLOCKED`.
- **Fund parameter:** BUY passes `fund = account.tradable_balance_t1`; SELL passes `fund = None`.
- **Error messages:** Identical to pre-refactor (verified string-for-string).
- **BUY/SELL separation:** BUY orders never call `get_sell_capacity`; SELL orders never call `get_buy_capacity`.
- **Validation-before-capacity:** All `OrderValidator` checks (including `maximum_order_quantity_for_buy`/`maximum_order_quantity_for_sell`) fire BEFORE the capacity API call.

#### Test Results (M6-E)
- `test_m6a_preflight.py`: 8/8 PASS
- `test_m6b_preflight.py`: 21/21 PASS
- `test_m6c_preflight.py`: 16/16 PASS
- `test_m6d_preflight.py`: 15/15 PASS
- `test_engine_interface.py`: 17/17 PASS
- `test_trading_state.py` (M5 regression): 16/16 PASS
- `test_engine_provider_integration.py`: 4/4 PASS
- `test_broker_manager.py`: 6/6 PASS
- `test_instrument_provider.py`: 11/11 PASS
- `test_main_order_workflow.py`: 7/7 PASS
- `test_order_build.py`: PASS
- `test_broker_dry_run.py`: PASS
- `test_smoke_import`: PASS
- **Total regression: 123/123 PASS** (all tests, no new tests added, no existing tests modified)

#### Out-of-Scope for M6-E
The following are explicitly **not** part of M6-E:
- `Broker.get_capacity()` unified method on `Broker` ABC — not implemented (Phase 2 optional, not part of this commit)
- Changes to `brokers/base.py` — unchanged
- Changes to `brokers/agaah/broker.py` — unchanged
- Changes to `OrderValidator` (`models/order_validator.py`) — unchanged
- M6-F / Order Splitting — Deferred / Future Development (out of scope per Architect decision)
- Any new endpoint or contract changes — none introduced

### M6 Overall Status
- M6 Discovery: **COMPLETE**
- M6 Architectural Scope: **DEFINED**
- M6-A Implementation: **COMPLETED** (Architect approved, pushed as `7ce09e3`)
- M6-B Implementation: **COMPLETED** (Architect approved, pushed as `84f9130`)
- M6-C Account Cash + BUY Capacity Validation: **COMPLETED** (Architect approved, pushed as `03ede4e`)
- M6-D Portfolio Quantity / SELL Gate: **COMPLETED** (Architect approved, pushed as `f3bdf1d`)
- M6-E Unified BUY/SELL Capacity Preflight: **COMPLETED** (Architect approved, pushed as `be0d0b7`)
- **M6 preflight core complete: M6-A through M6-E all implemented.**
- **M6-F / Order Splitting: Deferred / Future Development** — out of scope per Architect decision; no implementation planned at this stage.



\---



## 20. Critical Rule for Future Agents

\*\*Do not modify the architecture, broker API implementation, authentication mechanism, or real-order behavior based on assumptions.\*\*



Inspect the existing implementation first.



If an API behavior is unknown, mark it as unknown and investigate it.



Never invent an endpoint, request field, authentication mechanism, broker identifier, or trading rule.



