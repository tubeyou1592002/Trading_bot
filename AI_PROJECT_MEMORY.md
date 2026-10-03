\# Trading Bot — AI Project Memory



\## 1. Project Identity



\*\*Project name:\*\* Trading Bot



\*\*Language:\*\* Python



\*\*Platform:\*\* Windows



\*\*IDE:\*\* VS Code



\*\*Python version:\*\* 3.13.x



\*\*Project path:\*\*

`C:\\Users\\hp\\Documents\\Trading\_bot`



**Previous verified Git baseline:**

`d09cc1f — docs: synchronize Block 7 roadmap status`




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



\### Order Discovery — Real Network Observation (Agah Panel)

Source: observed from the real Agah panel Network traffic via Chrome DevTools / Network. No sensitive account or user information is recorded here.

Items without sufficient evidence remain UNKNOWN.

This Discovery is the basis for the design of Block 5.

Block 5 scope note: Block 5 is currently focused on detecting successful order registration in the trading core. Fill, Execution ID and full order lifecycle are currently out of scope.

1. `POST /api/v1/order` — order submission. Observed response includes `decisionId`.

2. `GET /api/v1/order/{decisionId}` — order result / history tracking. Observed fields:

\* `requestId`

\* `action`

\* `actionTitle`

\* `requestStatus`

\* `requestStatusTitle`

\* `decisionQuantity`

\* `remainingQuantity`

\* `requestTime`

\* `responseTime`

\* `delta`

Observed signal (only as an observed signal, not a general claim about the API): `requestStatusTitle = "تائید شده توسط بورس"`.

3. `GET /api/v1/order/getorderposition` — observed parameters:

\* `nscId`

\* `hostOrderNumber`

\* `orderDate`

Observed response fields:

\* `eventDateTime`

\* `ordersAheadQuantity`

\* `ordersAheadValue`

\* `position`

4. `POST /api/v1/order/{decisionId}/cancel` — observed response:

\* `isSuccess = true`

\* `errors = []`



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

---
## 5b. Agah OMS (Order Management System) — Verified Contracts (Agah-Specific Only)

**Source:** Real Agah panel network traffic (Chrome DevTools) and live order observation.  
**Scope:** The following applies **only to Agah**. Other brokers must not use these endpoints, state values, events, or mappings without independent evidence.  
**Real trading:** Still disabled. No real order was submitted for these discoveries.

### 5b.1 Initial Order Placement

| Item | Detail |
|------|--------|
| Endpoint | `POST /api/v1/order` |
| Success response | Contains `data.decisionId` |
| `data.isSuccess=true` | **Only** indicates initial registration success. It does **not** mean the order is registered in the trading core. |
| Core registration signal | Observed via OMS state `AcceptedByBourse (5)` → message «... در هسته معاملات ثبت گردید» |

> **Conclusion:** `POST /api/v1/order` success ≠ final registration in trading core. Full lifecycle must be tracked via `decisionId` and OMS states.

### 5b.2 OMS State Contract — `OmsStateChanged` (code 100)

Frontend consumes `OmsStateChanged` (message code `100`) for order state transitions.  
**Contract: numeric value + enum name + Persian/functional meaning**

| Value | Enum Name | Persian / Meaning |
|-------|-----------|-------------------|
| 1 | `SavingInAsa` | در حال ثبت در آسا |
| 2 | `SavedInAsa` | در آسا ثبت شد |
| 3 | `SendingToBourse` | در حال ارسال به بورس |
| 4 | `SentToBourse` | به بورس ارسال شد |
| 5 | `AcceptedByBourse` | در هسته معاملات ثبت/پذیرفته شد |
| 6 | `RejectedByError` | رد سفارش با خطا |
| 7 | `Traded` | معامله شد |
| 8 | `Completed` | تکمیل شد |
| 9 | `EliminatedByBourse` | حذف/لغو توسط بورس |

### 5b.3 Real-World Observation (Single Live Order)

```
SavedInAsa (2)
  → پیام «... در آسا ثبت گردید»

AcceptedByBourse (5)
  → پیام «... در هسته معاملات ثبت گردید»
```

This confirms the gap between initial POST success and core registration.

### 5b.4 OMS Error Path — `RejectedByError = 6`

When an order is rejected, the Pusher push includes:
- `decisionId`
- `message` → splits into `errorText | errorCode`

Example `errorCode`: `oms_042`  
Frontend mapping for `oms_042`: **«وضعیت گروه نماد برای ثبت سفارش مجاز نمی باشد»**

**Timing note:** The rejection push can arrive **before** the successful POST callback. Frontend temporarily holds it by `decisionId` and processes after the callback resolves.

> **Unverified / Not Confirmed:**
> - Root cause/backend logic that produces `oms_042` is **not confirmed**.
> - `instrumentGroupStateCode` is **not confirmed** as the definitive backend condition for `oms_042`.
> - **Do not** implement a speculative pre-check based on `groupStateCode` for `oms_042`.

### 5b.5 Pusher Transport (Observed in Production)

Frontend uses NATS-backed Pusher:

```
/api/v1/pusher/nats
/api/v1/Pusher/message-types
```

Message flow:

```
NATS
→ decode message
→ message$
→ OmsStateChanged (100)
→ order state
```

### 5b.5a Stage 1 Timing Implementation

Stage 1 timing instrumentation was implemented on top of the existing Block 8 `LatencyCollector`.

Per-order timing fields:
- `sent_at_ns`
  - Monotonic application timestamp captured at the actual broker submission point.
- `broker_registered_at_ns`
  - Monotonic application receipt timestamp captured only when the live Agah order response confirms successful initial registration with:
    - `isSuccess = true`
    - `data.decisionId` present
- `matching_engine_registered_at_ns`
  - Reserved for receipt of `OmsStateChanged (100)` with `AcceptedByBourse (5)`.
  - Currently remains `None` because no Pusher/OMS consumer exists in the repository.

Important:
- `data.decisionId` confirms initial broker/Agah registration only.
- It is not equivalent to `AcceptedByBourse (5)`.
- `AcceptedByBourse (5)` remains the documented matching-engine registration signal.
- Dry-run does not generate a broker-registration timestamp.
- No new latency framework was introduced; Block 8 infrastructure is reused.
- No real order was sent during implementation or testing.

Implementation commit:
`822c46d — feat: capture order feedback timing`

### 5b.6 Validity Constraints (Must Read)

- All of §5b is **Agah-specific**.
- Other brokers **must not** reuse these states, events, endpoints, or mappings without independent evidence.
- `oms_042` backend cause: **unconfirmed**.
- `instrumentGroupStateCode` as `oms_042` condition: **unconfirmed**.
- No speculative pre-check for `oms_042` based on `groupStateCode`.

---

## 6. TSETMC



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



### Current: Block 7 — Multi-Broker Execution

**Status: COMPLETED**

```text
Block 7 — Multi-Broker Execution
Status: COMPLETED

7.1  Broker Infrastructure Audit — COMPLETED (70ccda3)
7.2  Generic Multi-Broker Manager — COMPLETED (7974894)
7.3  Broker-specific Instrument Provider Isolation — COMPLETED (39f7594)
7.4  Second Broker Offline Stub — COMPLETED (8c2a047)
7.5  Multi-Broker Dispatch — COMPLETED (cf84494)
7.6-L1 N Account / N Broker Foundation — COMPLETED (a9e3b9a)
7.6-L2 Account + Broker + Order + Instrument Integration — COMPLETED (a6a3a12)
7.7  End-to-End Integration / Regression / Documentation — COMPLETED (3b9502d)
```

**Production changes during Block 7:** `brokers/manager.py` only (Task 7.2)

**Real trading: disabled**

### Current Test State

Block 7 Task tests:
23 passed — Task 7.6-L2
5 passed — Task 7.7

Full regression at Block 7 completion:
456 passed

Production changes during 7.6-L1: none
Production changes during 7.6-L2: none
Production changes during 7.7: none

Real trading: disabled


Implementation summary:



\* `BrokerManager.get_instrument_provider(name: str) -> InstrumentProvider` was added in `brokers/manager.py`.



\* The provider is constructed lazily on the first call and cached per broker in `self.providers[name]`.



\* The provider wraps the **same** `AgaahBroker` instance stored in `self.brokers[name]`. The manager does not construct a fresh broker for the provider.



\* BrokerManager → generic broker registration; broker-specific InstrumentProvider; per-broker provider cache. Current real broker: Agah. Architecture: Multi-Broker (not Agah-specific).



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

### Next Step

Block 8 — Latency Measurement & Optimization
Status: NOT STARTED

Per Roadmap, Block 8 is the next phase after Block 7 completion.

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

### User Application (UI) Status
- UI-1 Application Foundation: **COMPLETED** (`d73f3e0`)
- UI-2 / UI-2.1 Account & Broker Management: **COMPLETED** (`283f58`)
- UI-3 Order Configuration: **COMPLETED** — UI-3.1 (`97283c5`), UI-3.2A Symbol Search (`d14a8d2`), UI-3.2B Trading State Display (`a614597`)
- UI-3.2B follow-up (`4fc49e3`): **test-contract only** — updated the UI-1 / UI-3.1 import allowlists for the existing lazy UI-3.2B seams (`brokers.manager`, `core.trading_state_query`, `models.trading_state`); **no production code changed**. Final targeted tests: **84 passed**.
- Trading State display path (unchanged, read-only): `UI → TradingStateWorker → core.trading_state_query.TradingStateQuery → BrokerManager / InstrumentProvider → Agah Broker → TSETMC`. TSETMC stays the authoritative source (Decision 020); the UI never calls TSETMC directly and never interprets raw `cEtaval` / `cEtavalTitle`. Unverified / unavailable / error states are fail-closed «نامشخص»; the path creates, submits, or dispatches no Order.
- UI-4 — Order Queue: **COMPLETED** (Tasks 1–8 implemented, tested, and committed).
- UI-5 Task 4 Stage 1 (Core — order feedback & timing capture): **COMPLETED** (`822c46d`)
- UI-5 Task 4 Stage 2 (Core — queue position via Agah NATS/OMS): **COMPLETED**
- UI-5 Task 4 Stage 3 PREREQUISITE — OMS/NATS feedback activation bridge: **COMPLETED**
- UI-5 Task 4 Stage 3 (UI — user-facing order log table): **COMPLETED** (`ecfa5cf`)
  * Seven columns are rendered: `زمان ارسال`, `حساب`, `نماد`, `توضیح`, `زمان دریافت توسط کارگزاری`, `زمان ثبت در هسته معاملاتی در صورت وجود`, `وضعیت صف`.
  * Column 5 consumes the existing Stage 1 broker-receipt timestamp; column 6 is stamped only by matching-engine registration feedback (`AcceptedByBourse`, action=5).
  * `SavedInAsa` (action=2) does not mark a row registered in the trading core.
  * Column 7 consumes only the existing Stage 2 queue-position signal, correlated by `decisionId`; no new queue polling/calculation was added.
  * Rows preserve send order; duplicate/unknown/invalid queue feedback is handled fail-closed; `decisionId` is never rendered.
  * Verification: focused Stage 3 Task 4 tests 10 PASS; related Stage 3 suite 126 PASS; combined Stage 3 verification 136 PASS.
  * Real trading remains disabled and verification is offline/deterministic.
- Deferred to UI-6: latency/diagnostics/trace-style presentation and detailed execution timing.
### UI-6 Roadmap — Finalized

**Current status:** UI-5 is COMPLETED. UI-6 is COMPLETED with exactly four tasks: (1) Diagnostic Mode Foundation — COMPLETED; (2) Trace ID — COMPLETED; (3) Latency & Execution Diagnostics — COMPLETED; and (4) Integration, Regression & Documentation — COMPLETED. UI-6 itself is COMPLETE.

1. **Diagnostic Mode Foundation** — establish the NORMAL/DIAGNOSTIC presentation boundary; technical information remains hidden in Normal Mode; no trading/execution behavior changes.
2. **Trace ID — COMPLETED** — the existing dispatch-level `DispatchResult.trace_id` is shown only in Diagnostic Mode. Invalid/missing IDs are unavailable; no second ID is generated or substituted. A failed new runner attempt immediately clears the previous displayed ID. Reported verification: 20 focused tests and 190 related UI regression tests passed.
3. **Latency & Execution Diagnostics — COMPLETED** — reuses existing Block 8 timing data. Dispatch duration, stage timings, Broker/API calls, and application-side fields remain separate. Stage and call values are labeled per order; each API call is individually identified by operation and call number. Missing/cross-clock values remain unavailable. Verification: 28 focused tests and 289 selected UI regression tests passed.
4. **Integration, Regression & Documentation — COMPLETED** — Diagnostic Mode, Trace ID, latency/diagnostic presentation, and UI-5 regression safety were verified against the actual repository state before documentation was marked complete. No code, test, or configuration was changed.

UI-6 Task 1 uses the existing `ApplicationMode`; the diagnostic section is hidden in NORMAL and shown in DIAGNOSTIC. Invalid mode values hide it fail-closed. The mode does not change trading/execution behavior. Reported verification: 12 focused tests and 182 related UI regression tests passed.

**Task 4 session results (2026-10-02, run against the actual repository, not copied from earlier reports):**
- Focused UI-6 suite `python -m pytest test_ui6_task1_diagnostic_mode.py -q` → **28 passed**.
- Regression `python -m pytest test_ui1_application_foundation.py test_ui3_2a_symbol_search.py test_ui3_2b_trading_state_display.py test_ui4_queue_ui_integration.py test_ui5_task3_feedback_service.py -q` → **70 passed**.
- Unverified in this environment, and therefore NOT to be reported as passing: `test_ui3_1_order_configuration.py` (deliberately skipped — modal-dialog test hangs offscreen, also on baseline); `test_ui5_task4_stage2_queue_position.py` (collection error, `nats-py` missing); the UI-5 Stage 3 tests that import `brokers.agaah.nats_transport` (same `nats` import failure). UI-5 Stage 2 / Stage 3 coverage was therefore only partially re-verified here.
- **Follow-up verification (2026-10-02):** In the user's Python 3.13 environment with `nats-py` 2.16.0, `python -m pytest test_ui5_task4_stage2_queue_position.py test_ui5_task4_stage3_task3_core_registration.py test_ui5_task4_stage3_task4_ui_table.py -q` → **79 passed**, resolving the NATS-related limitation above. The test-only QMessageBox mocks and the UI-3.1 AST allowlist update resolved the Qt test issue without changing production code: `python -m pytest test_ui2_1_account_management.py test_ui3_1_order_configuration.py -q` → **46 passed**. No listed UI-6 verification limitation remains.
- `git diff --check` is clean for `AI_HANDOFF.md`, `AI_PROJECT_MEMORY.md`, and `DECISIONS.md`. At verification, `git status --short` showed these three documentation files as modified for this task, plus pre-existing untracked files; no other tracked files were modified.

The roadmap order is `UI-1 → UI-2 → UI-3 → UI-4 → UI-5 → UI-6 → UI-7 → UI-8 → Central Server`.

UI-6 does not include UI-7 scheduling/countdown, UI-8 end-to-end acceptance, Central Server/Admin Panel, new latency instrumentation, new trading logic, historical persistence/export/filtering, or M6-F order splitting. UI-7 owns scheduling; UI-8 owns final integration/acceptance. Missing or cross-clock Block 8 values remain unavailable; separate timing layers are not merged.

### UI-7 Roadmap — Schedule & Countdown

**Current status:** COMPLETE. UI-7 has exactly four tasks: (1) Schedule Configuration & Validation; (2) Countdown & Schedule State; (3) Timed Dispatch Integration; and (4) Integration, Regression & Documentation. All four are complete (Task 1: 2026-10-02; Tasks 2–4: 2026-10-03). UI-6 is complete. The next phase is UI-8 (End-to-End Integration & Acceptance).

1. **Schedule Configuration & Validation** — collect Start Time, End Time, and Interval; reuse `DispatchTiming` validation and `TimedDispatchScheduler`; use Tehran time (`Asia/Tehran`, confirmed by the user); show the accepted schedule summary. Establish the clock foundation: NTP disciplines the system clock for high-resolution continuity, while TSETMC provides the market-time comparison/calibration. Account for request elapsed time when estimating offset; apply bounded gradual correction only to an application-level logical clock, never abruptly change the OS clock. Keep countdown/elapsed-time measurement monotonic. The TSETMC response has seconds-only precision, so its uncertainty must be explicit and zero-millisecond alignment must not be promised or fabricated. User-provided Chrome DevTools capture identifies unauthenticated `GET https://cdn.tsetmc.com/api/StaticData/GetTime`; it returns `200 text/plain` as `MM/DD/YYYY HH:MM:SS` (Gregorian, seconds only). This is an unofficial/undocumented endpoint without a stability/SLA guarantee and may be IP-restricted. Before implementation validate status, content type, exact format, timestamp, timeout, and freshness; inspect `Age`, `Cache-Control`, `Date`, and optional `Expires` / `Last-Modified`. The HTTP `Date` header is GMT/UTC and must not be mistaken for the Tehran-time body. If Start Time is past but End Time is ahead, notify and begin once immediately without replaying missed intervals; if End Time is past, expire without dispatch.
2. **Countdown & Schedule State** — sync once after the main window appears and offer manual sync; show source, offset, uncertainty, and monotonic freshness (30-second Apply limit). Apply consumes the last completed sync or waits for one in flight, without making its own request; missing/stale/failed market time falls back to the system clock with a soft notice. Freeze the effective time and monotonic anchor on Apply so later syncs or wall-clock steps cannot move the countdown. Lock order/queue/schedule controls immediately, including while waiting for sync; change Apply to Stop. Stop cancels pending/active countdown without dispatch and unlocks controls; expiry unlocks. Task 2 does not dispatch orders. Manual Stop is approved; pause/retry remain out of scope.
3. **Timed Dispatch Integration** — invoke the existing UI/Core execution path only at due timestamps and within the schedule window; preserve order/account/broker identity and Core/SafetyGate/M6-A…M6-E checks; prevent early/late/duplicate dispatches and never compress missed slots after a clock-source change. Test Mode remains separate.
4. **Integration, Regression & Documentation** — use deterministic clock/timer tests; verify boundaries, past-start/expired behavior, site-clock timeout/invalid/stale fallback and recovery notices, no duplicate/catch-up dispatch, and unchanged UI-5/UI-6 behavior; record results before marking UI-7 complete.

**Existing infrastructure and boundary:** `core/timing_contracts.py`, `core/timed_dispatch_trigger.py`, and `core/timed_dispatch_scheduler.py` already provide validated timing contracts and deterministic timestamp generation. They deliberately do not run a real timer or scheduler loop. UI-7 adds the UI-side countdown and due-time coordination while reusing those contracts; it does not duplicate schedule math or redesign Core. UI-8 retains end-to-end Broker-boundary acceptance.

**Clock-source decision:** Prefer the stock-market site's server time in Tehran timezone (`Asia/Tehran`, confirmed by the user). NTP disciplines the system clock for high-resolution continuity; compare it periodically with TSETMC, whose seconds-only payload limits how precisely market-time offset can be known. If site time is unavailable, invalid, or stale, fall back to the NTP-disciplined system clock with a soft notice; disclose reduced confidence if NTP synchronization is also unavailable. Apply bounded gradual correction only to application-level logical time, never abruptly alter the OS clock; use a monotonic clock for elapsed time and countdowns. Switch back and notify when valid, fresh site time recovers. User-provided DevTools capture identifies `GET https://cdn.tsetmc.com/api/StaticData/GetTime` (public, no authentication), returning plain-text `MM/DD/YYYY HH:MM:SS` (Gregorian, seconds only). It is unofficial/undocumented, has no stability/SLA guarantee, and may be restricted to Iranian IP ranges. Freshness must account for CDN `Age` and `Cache-Control` plus available `Date`, `Expires`, or `Last-Modified`; the HTTP `Date` value is GMT/UTC, while the payload is Tehran time. Define the freshness policy before implementation. Clock switching must not duplicate an already dispatched slot or replay missed intervals. For a past Start Time with End Time still ahead, notify and begin once immediately; an already-past End Time expires without dispatch.

**UI-7 Task 1 completion (2026-10-02):** Implemented the TSETMC clock service and freshness/format validation, uncertainty-aware offset, bounded non-rewinding application clock, system-clock fallback, fail-closed schedule input parsing via Block 3, and the Schedule group with asynchronous Apply-time refresh. Added 102 offline tests. Reported verification: UI-7 **102 passed**; UI-1/UI-2.1/UI-3.2/UI-6 selection **97 passed**; UI-4/UI-5 runnable subset **155 passed**; offline import guard clean; baseline selections matched. Limitations: UI-3.1 `test_5` hangs in this environment as on baseline; `test_ui5_task4_stage3_task4_ui_table.py` needs unavailable `nats`; same-day windows only; live endpoint/CDN behavior was not verified. Full UI-3.1 and UI-5 Stage 3 coverage is not claimed. UI-7 remains IN PROGRESS; Task 2 is next.
**UI-7 Task 2 completion (2026-10-03):** Implemented one-shot startup sync, manual sync and visible freshness status, Apply using the last completed sync (or waiting for an in-flight sync), and soft system-clock fallback when no fresh market reading is available. Apply freezes the effective current time on a monotonic anchor; later clock changes do not shift the countdown. Controls lock immediately after valid Apply, including during pending sync; Apply becomes Stop, which cancels pending/active countdown without dispatch and unlocks controls. Expiry unlocks controls. A display-only one-second timer ages the freshness line. Verification: the user ran `python -m pytest -q test_ui7_task2_countdown_state.py` → **17 passed** after installing `tzdata`; the targeted non-rewind test also passed. The focused Task 2 suite includes the selected UI-5/UI-6 regression check. Previously reported selected UI-1/UI-2.1/UI-3.2/UI-6 regression: **97 passed**; UI-4/UI-5 runnable subset: **155 passed**; those broad selections were not rerun after the final Task 2 fixes. No live TSETMC request or order dispatch was performed. UI-7 remains IN PROGRESS; Task 3 is next.
**UI-7 Task 3 completion (2026-10-03):** Implemented fixed-millisecond periodic sends through the existing UI/Core runner path in `ui/schedule_dispatcher.py` and `ui/order_configuration_page.py`. Sends fan out concurrently by broker group; each tick starts independently of earlier broker responses, with no response-based cap or skipped cadence. A past start anchors the first due turn at the first execution opportunity without replaying historical slots; future starts and the configured end boundary remain fixed. Apply rejects the whole schedule for an empty queue, missing account, or account/broker mismatch; it never sends a partial destination set. Per-group monotonic start is captured immediately before `runner.run(...)`, separate from response time and Block 8 measurements. Stop prevents new turns; in-flight requests are not force-cancelled. Two Task 1/2 test fixtures now include a valid queued order to preserve their schedule/countdown coverage under Task 3's empty-queue refusal rule. Reported runs before the final guard correction: Task 3 **63 passed**; Tasks 1–3 **182 passed**; selected UI-5/UI-6/Block 8 regressions **220 passed**. After the final guard correction, the user ran the targeted race regression → **1 passed**; broad suites were not rerun after that small correction. No Core, Block 3, Block 8, Broker, or live-permission code was changed; no live order was enabled or sent. UI-7 remains IN PROGRESS; Task 4 is next.

**UI-7 Task 4 completion (2026-10-03) — UI-7 COMPLETE:** Task 4 ran the required UI-7 plus UI-1→UI-6 verification and closed the single UI-7 regression it found. No UI-7 production bug was found and no UI-7 implementation file was changed. The only code change was to `test_ui3_1_order_configuration.py`: its architectural seam contract now registers the two EXISTING Block 3 seams UI-7 reuses, `core.timing_contracts` and `core.timed_dispatch_scheduler`, and its laziness rule was generalized rather than relaxed — a new `must_stay_lazy` set covers both alongside `market.symbol_resolver`, so importing either at module level still raises. Proven by mutation: hoisting the import in `ui/schedule_settings.py` to module level makes `test_14` fail ("imports core.timing_contracts at module level"); the file was then restored byte-identically. Final offline runs: UI-7 Tasks 1+2+3 **183 passed** (exit 0); UI-1/UI-2.1/UI-3.1/UI-3.2A/UI-3.2B plus all eight UI-4 files **188 passed, 2 deselected** (exit 0); all eight UI-5 files plus UI-6 **173 passed** (exit 0); Block 3 timing contracts/scheduler/trigger **32 passed** (exit 0); Block 8 tasks 8.2/8.3/8.4/8.5 plus `dispatch_core` **124 passed, 2 failed** (exit 1). An offline import guard confirms that importing `ui.main_window`, `ui.order_configuration_page`, `ui.schedule_settings`, `ui.schedule_dispatcher` and `ui.market_clock` with `socket.socket`/`socket.create_connection` disabled creates no socket. Acceptance criteria re-checked and holding: clock/site sync/freshness/fallback/messages; Apply fixes time and the monotonic base; Stop halts future sends and expiry frees locks; past start yields one immediate start with no catch-up replay, future starts stay unshifted, nothing starts after the window end; the millisecond cadence with a turn never waiting on the previous turn's response and brokers of one turn reaching the send path together; fixed and correct order/account/broker bindings, with empty queue, invalid account and broker mismatch each rejecting the whole schedule and never sending a partial set; the recorded start being the real `runner.run(...)` entry boundary with Block 8 untouched and unmerged; unchanged UI-5/UI-6 behavior; no live or real broker access enabled. Known remaining items, all confirmed pre-existing and unrelated to UI-7 by reproducing each identically at pre-UI-7 commit `6901a82`: the two Block 8 `broker_received_at` contract failures (`test_block8_task8_2.py::test_latency_does_not_add_fields_to_existing_contracts`, `test_block8_task8_3.py::test_measurement_keeps_existing_engine_and_result_contracts`), which concern a Broker-received timestamp field and sit outside Task 4 scope; and the two UI-3.1 hangs (`test_5_quantity_enter_and_store`, `test_extra_page_preserves_state_on_fractional_input`), deselected so the remainder could be verified. Earlier limitation RESOLVED: `nats` is installed, so `test_ui5_task4_stage3_task4_ui_table.py` ran → **10 passed**. Environment: this machine has no IANA tz database, so all runs used the out-of-repo shim `PYTHONPATH=/tmp/tzshim` plus `QT_QPA_PLATFORM=offscreen`; no repository file was modified for it. UI-7 has exactly four tasks and all four are complete; the next phase is UI-8.

### UI-8 Roadmap — End-to-End Integration & Acceptance

**Status:** COMPLETE; UI-7 is complete and all four UI-8 tasks, including Task 4 (regression, acceptance, and documentation), are complete. UI-8 has exactly four tasks and was the final User Application acceptance phase before Central Server work. Limitations recorded, not capabilities: one Test pass over a mixed-account/mixed-broker queue is still rejected, the cross-clock/unavailable application-side timing branch stays covered only by UI-6 fixtures, and the pre-existing Block 8 `broker_received_at` failures plus the two known UI-3.1 hangs remain open for a separately scoped repair.

1. **Single-Account / Single-Broker End-to-End Path** — verify the existing UI → TestRunner → Core → Broker-boundary flow with offline doubles, including order input, plan/dispatch result, and user-visible feedback.
2. **Multi-Account / Multi-Broker Routing and Identity** — verify each order remains bound to its intended account and broker through planning, dispatch, result collection, and UI feedback, including mixed destinations and failure cases.
3. **Safety Gates, Modes, and Diagnostics** — verify fail-closed and M6-A…M6-E behavior at the existing Core/SafetyGate boundary; verify Test Mode stays distinct from Live; verify Diagnostic Mode, UI-5 feedback, and UI-6 Trace ID/latency presentation using existing Block 8 data without combining timing layers.
4. **Regression, Acceptance, and Documentation** — run and record relevant UI-1…UI-7, M6, and Block 8 regressions; confirm no UI-5…UI-7 regression or safety bypass; document exact results and limitations. Mark UI-8 complete only after required acceptance checks pass.

**Scope and safety:** Acceptance runs use offline doubles and stop at the existing Broker boundary. No real order, broker credential, or Live permission is authorized. UI-8 does not redesign Core, M6, Block 8, or UI-7. Central Server, Admin Panel, License/Activation, and multi-user rollout remain later phases. If an acceptance gap requires code or test changes, request a separately scoped repair before making them.

**UI-8 Task 1 completion record (2026-10-03):** Added `test_ui8_task1_single_broker_e2e.py` as one focused offline E2E test. It exercises the real page queue/Test action through TestRunner, DispatchIntegration, DispatchCore, OrderEngine, and SimulationBroker for one order/account/broker; asserts preserved identities, exactly one `live=False` broker call, no live-send result, and the result rendered in the UI. Network and real-broker entry points are blocked by the test. The test does not assume a SafetyGate is attached and passed in a temporary committed-HEAD tree without the pre-existing local `ui/test_runner.py` modification. Reported verification: focused test **1 passed**; together with directly related UI-5 Task 2/3 tests **42 passed**. No production/configuration/documentation other than this status record was changed by the implementation; no real order or network call was made. Task 1 is complete; Task 2 is next. No UI-8 completion claim is made.

**UI-8 Task 2 completion record (2026-10-03):** Added `test_ui8_task2_multi_account_multi_broker_e2e.py` with two offline tests. The first drives real page queue/Test flows through TestRunner/Core/OrderEngine and two independent simulation pairs, proving order/account/broker identity and per-broker delivery for three orders across two accounts and brokers in separate supported single-account passes; it also verifies dry-run results and UI attribution. The second proves the current mixed-destination queue is rejected fail-closed without dispatch, broker calls, queue splitting, or entry loss. **The product does not currently execute mixed-account/mixed-broker entries in one Test pass.** The limitation is recorded, not worked around; any support for mixed queues needs a separately scoped product decision and implementation. Reported verification: Task 2 tests **2 passed**; Task 1 + Task 2 tests **3 passed**. No production/configuration code or other test changed; no live order or network access occurred. Task 2 verification is complete; Task 3 is next. UI-8 remains in progress.

**UI-8 Task 3 completion record (2026-10-03):** Added `test_ui8_task3_safety_modes_diagnostics.py` with three focused offline tests over the real UI/TestRunner/Core path and SimulationHarness. They verify dry-run behavior, same-run real Trace ID and Block 8 timing display in Diagnostic Mode, hidden technical data in Normal Mode, stale data clearing after a failed run, an actual M6-C rejection before broker placement, and unchanged queue/order-log/result rows when modes change. Network and real-broker entry points are guarded; no live order was used. Reported result: **3 passed**. The missing/cross-clock application-side timing path did not occur in the real report and remains covered by the existing UI-6 fixture tests; it is not claimed as real-run evidence. No production or other test file changed. Task 3 is complete; Task 4 is next. UI-8 remains in progress.

**UI-8 Task 4 completion record (2026-10-03) — Task 4 COMPLETE, UI-8 COMPLETE:** Task 4 verified the Task 1–3 tests against their recorded results and ran the required regressions, all offline (`QT_QPA_PLATFORM=offscreen`, Python 3.13.15, pytest 9.1.1) at the three UI-8 test commits with the pre-existing uncommitted `ui/test_runner.py` change untouched. Actual results: UI-8 Tasks 1+2+3 → **6 passed** (exit 0); UI-1 + UI-2.1 → **27 passed** (exit 0); UI-3.1 whole file **timed out at 300 s** on its two known hangs (`test_5_quantity_enter_and_store`, `test_extra_page_preserves_state_on_fractional_input`), and with exactly those two deselected → **30 passed, 2 deselected** (exit 0); UI-3.2A + UI-3.2B → **42 passed** (exit 0); UI-4 (nine files) → **89 passed** (exit 0); UI-5 (seven files) → **145 passed** (exit 0); UI-6 → **28 passed** (exit 0); UI-7 (three files) → **183 passed** (exit 0); M6-A…M6-D plus Block 8 tasks 8.2–8.5 → **135 passed, 2 failed** (exit 1). The two failures are the pre-existing Block 8 `broker_received_at` contract tests already recorded by UI-7 Task 4, traceable to the 2026-09-30 commits `2459ece`/`3557c04`, involving no UI-8 file, and outside UI-8 scope; they are reported as an open, separately scoped repair. No UI-8 defect was found: identity preservation, fail-closed mixed-destination rejection and M6-C rejection with zero broker placements, dry-run Test mode, Diagnostic-only technical data with the same-run Trace ID and separate Block 8 timing categories, and unchanged UI-5/UI-7 behavior all hold over the real UI → TestRunner → Core → OrderEngine → simulation broker path. No gate was bypassed, every broker call was `live=False`, no live send was reported, and no network, credential, or real broker was used. Task 4 modified no code and no test — only these current status sections — and committed or pushed nothing. The next phase is Central Server.

- Full per-task detail lives in `AI_HANDOFF.md` §9 (User Application / UI Architecture & Roadmap). Full per-task detail lives in `AI_HANDOFF.md` §9 (User Application / UI Architecture & Roadmap).



\---



## 20. Critical Rule for Future Agents

\*\*Do not modify the architecture, broker API implementation, authentication mechanism, or real-order behavior based on assumptions.\*\*



Inspect the existing implementation first.



If an API behavior is unknown, mark it as unknown and investigate it.



Never invent an endpoint, request field, authentication mechanism, broker identifier, or trading rule.
