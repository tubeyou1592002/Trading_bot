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

`4c185ab — feat: add bounded Agah 401 token recovery`




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

1. **Schedule Configuration & Validation** — collect Start Time, End Time, and Interval; reuse `DispatchTiming` validation and `TimedDispatchScheduler`; interpret inputs in Tehran time (`Asia/Tehran`); show the accepted schedule summary. Use only the Windows system clock, synchronized externally with NetTime/NTP. Do not run NTP, modify the OS clock, or query TSETMC time. Sample system wall and monotonic time together at Apply; project deadlines onto monotonic time. If Start Time is past but End Time remains ahead, begin once immediately without replaying missed intervals; if End Time has passed, expire without dispatch.
2. **Countdown & Schedule State** — show the live system clock labelled «ساعت سیستم» and preserve Apply/Stop, state, countdown, and summary. Apply anchors system wall time to monotonic time so later wall-clock adjustments cannot jump countdowns or dispatch deadlines. Stop cancels an active countdown and unlocks controls; expiry unlocks. Task 2 does not dispatch orders; pause/retry remain out of scope.
3. **Timed Dispatch Integration** — invoke the existing UI/Core execution path only at due timestamps and within the schedule window; preserve order/account/broker identity and Core/SafetyGate/M6-A…M6-E checks; prevent early/late/duplicate dispatches and never compress missed slots after a clock-source change. Test Mode remains separate.
4. **Integration, Regression & Documentation** — use deterministic clock/timer tests; verify boundaries, past-start/expired behavior, site-clock timeout/invalid/stale fallback and recovery notices, no duplicate/catch-up dispatch, and unchanged UI-5/UI-6 behavior; record results before marking UI-7 complete.

**Existing infrastructure and boundary:** `core/timing_contracts.py`, `core/timed_dispatch_trigger.py`, and `core/timed_dispatch_scheduler.py` already provide validated timing contracts and deterministic timestamp generation. They deliberately do not run a real timer or scheduler loop. UI-7 adds the UI-side countdown and due-time coordination while reusing those contracts; it does not duplicate schedule math or redesign Core. UI-8 retains end-to-end Broker-boundary acceptance.

**Clock-source decision (updated):** Schedule display and timing use only the Windows system clock, synchronized externally with NetTime/NTP. The application does not run NTP, modify the OS clock, or query TSETMC time. Schedule inputs remain Tehran wall-clock times. Apply samples wall and monotonic clocks together and maps deadlines to monotonic time, preventing later system-clock changes from jumping or repeating scheduled runs. TSETMC symbol, trading-state, and price-limit data use remains unchanged.

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



### Block 9 — Account & Session Management (بلوک مدیریت حساب و نشست‌ها)

**Status:** IN PROGRESS — Block 9 Tasks 1–4 and Task 5 Stages 2A–2C are complete within their documented scopes. Account-integration Phase 1 (Tasks 1A `9efb88e`, 1B `39bd0d6`) and Phase 2 (Tasks 2A `ccdd563`, 2B `23802a7`, 2C `56a317b`) are complete and pushed within scope. The shared `BrokerManager` is used by authentication composition and TestRunner/DispatchCore, resolving account-owned resources by `(account_id, broker_name)` when called. Phase 3 Task 3A (`fbdc112`) and Tasks 3B-1 (`e4a0796`), 3B-2 (`f8764c0`), 3B-3 (`c8ec626`), 3B-4 (`9cb1f95`) and 3B-5 (`19d9558`) are complete and pushed. AccountsPage supports display names, credential save/delete, begin/cancel/complete login, local logout and per-account status, with integrated offline UI acceptance complete. Task 5 Stage 3 offline integration/regression audit was accepted on 2026-10-16. Name-only or separate-manager trading-state, instrument identity and feedback paths remain later work.

This block is responsible for converting the current "Accounts" page from simple/temporary account registration into a real broker account management system.

#### Current Execution Roadmap — Per-Account Runtime and Accounts-Page Integration

**Owner-approved direction:** 2026-10-15. Phase 1 Tasks 1A (`9efb88e`) and 1B (`39bd0d6`) and Phase 2 Tasks 2A (`ccdd563`), 2B (`23802a7`) and 2C (`56a317b`) are complete within their scopes. Phase 3 Task 3A (`fbdc112`) displays the required account display name; Task 3B-1 (`e4a0796`) injects lazy account services; Task 3B-2 (`f8764c0`) adds explicit credential save/delete UI; Task 3B-3 (`c8ec626`) adds begin/cancel login and validated generic challenge display. Task 3B-4 now completes login, local logout and per-account status. Task 3B-5 is the next bounded task; its exact test-only allowlist and acceptance criteria are in `AI_HANDOFF.md`. The accepted dark RTL direction remains; no broader redesign is authorized without owner approval.

**Phase 3 Task 3A completion (2026-10-15):** Commit `fbdc112` — `feat: add account display names to accounts page` — was pushed to `origin/master`. Changed files: `ui/accounts_page.py`, `ui/strings.py`, and `test_ui2_1_account_management.py`. The owner verified `py -3 -m pytest -q test_ui2_1_account_management.py` (**24 passed**) and `py -3 -m pytest -q test_ui1_application_foundation.py test_ui2_1_account_management.py` (**37 passed**). Display names are collected, validated, shown independently, and passed to `AccountStore.add(account_id, broker_name, display_name)`; login/credential integration was not part of this task.

## Completion Record — Block 9 Phase 3 Task 3B-1: Lazy service composition/injection — COMPLETE (2026-10-15)

- **Commit pushed:** `e4a0796` — `feat: inject lazy account services`.
- **Changed and committed files:** `ui/main_window.py`, `ui/accounts_page.py`, `test_block9_phase2_service_composition.py`.
- **Design:** MainWindow lazily caches one CredentialStore and one SessionManager; AuthenticationService uses those exact shared instances. AccountsPage accepts optional keyword-only service callbacks; MainWindow injects lazy lambdas without executing them during page/window construction. Construction failure does not cache an incomplete AuthenticationService.
- **Owner/agent-reported offline verification:** `python3 -m pytest -q test_block9_phase2_service_composition.py` → **4 passed**; account-management tests → **24 passed**; UI foundation + account-management tests → **37 passed**; focused AuthenticationService/Agah adapter/integration suite → **145 passed**. `py_compile` and targeted `git diff --check` succeeded. The agent environment did not have the Windows `py` launcher, so equivalent `python3` commands were used.
- **Final owner review:** only the three allowed Task 3B-1 files were staged and committed; cached diff check passed. The unrelated local `test_ui2_1_account_management.py` worktree marker had no content diff; `ui/test_runner.py` and other unrelated artifacts remained unstaged.
- **Scope boundary:** no credential/login UI action, real vault access, network request, broker login, or order was added/performed.


## Completion Record — Block 9 Phase 3 Task 3B-3: Begin/cancel login and generic challenge display — COMPLETE (2026-10-16)

- **Commit pushed:** `c8ec626` — `feat: add account login challenge UI`.
- **Changed files:** `ui/accounts_page.py`, `ui/strings.py`, `test_ui2_1_account_management.py`.
- **Reviewed behavior:** Login uses the selected row's real account ID and lazy injected AuthenticationService factory. Public `LoginChallenge` images are Base64-decoded and validated before display; invalid/missing/unsupported challenges fail closed and attempt cleanup. Cancel and cleanup calls carry the original pending account ID, not the currently selected row.
- **Owner-reported verification (after final test completion):** `python3 -m pytest -q test_ui2_1_account_management.py` → **37 passed in 2.02s**; UI foundation + account management → **50 passed in 4.34s**; service composition/authentication/Agah adapter/integration → **149 passed in 3.02s**; `py_compile` passed. Agent environment lacked `py -3`; equivalent `python3` commands were used.
- **Final owner staging/review:** only the three allowlisted files were staged; `git diff --cached --check` passed; the staged path list matched the allowlist.
- **Git:** commit `c8ec626` was pushed successfully, advancing remote `master` from `8bb7f54` to `c8ec626`.
- **Safety:** no real credentials/vault, network/broker login, CAPTCHA endpoint request or order was used.
- **Next:** Task 3B-4 — complete login, local logout and per-account status; exact bounded handoff is in `AI_HANDOFF.md`.

## Completion Record — Block 9 Phase 3 Task 3B-2: Credential save/delete UI — COMPLETE (2026-10-15)

- **Commit pushed:** `f8764c0` — `feat: add account credential management UI`.
- **Changed files:** `ui/accounts_page.py`, `ui/strings.py`, `test_ui2_1_account_management.py`.
- **Architecture:** credentials are written/deleted only by explicit user actions through the injected `CredentialStore`; target account identity comes from the selected row's real account ID and record broker; no credential read-back/prefill was added; password is masked; credential input fields are cleared after save/delete attempts; user-facing errors do not contain backend exception details.
- **Owner's staged-diff review:** exactly the three allowed files were staged; `git diff --cached --check` passed; the staged file list matched the allowlist.
- **Implementation-agent verification (agent used `python3` because `py -3` was unavailable in that environment):** account-management tests **33 passed**; UI foundation + account-management tests **46 passed**; service-composition + CredentialStore tests **68 passed, 7 skipped**; compilation and scoped diff checks passed. These are agent-reported results; owner rerun of these suites is not claimed.
- **Git:** after the remote advanced, `git pull --rebase --autostash origin master` succeeded and reapplied the autostash; push then succeeded, advancing remote `master` from `1f3b838` to `f8764c0`.
- **Safety boundary:** no real secure-vault operation, broker login, CAPTCHA request, network request or order submission was performed.
- **Next:** Task 3B-3 — begin/cancel login and generic challenge display. Its exact bounded contract is recorded in `AI_HANDOFF.md`. Review it before Task 3B-4.

**Owner-approved Task 3B implementation order (2026-10-15):** The Product Owner accepted the following sequence. Acceptance applies to the order of work; each implementation task still requires an Architect-defined allowlist, exact acceptance criteria, and review before the next task starts.

1. **Task 3B-1 — Lazy service composition/injection and offline construction tests.** Provide AccountsPage with controlled/lazy access to the already-composed shared services without triggering service, vault, network, or login work during MainWindow/AccountsPage construction. No credential/login UI actions in this task.
2. **Task 3B-2 — Credential save/delete UI.** Wire explicit user-triggered save/delete via CredentialStore; cover success, missing credential, validation/backend failures, and secret non-disclosure with fake in-memory backends.
3. **Task 3B-3 — Begin/cancel login and generic challenge display.** Use AuthenticationService and its public LoginChallenge contract; display the challenge only when returned, keep broker-specific CAPTCHA details inside the adapter, and test with fakes.
4. **Task 3B-4 — Complete login, local logout, and per-account status.** Confirm status from public service APIs; prove state and UI for one account cannot change another account using at least two fake accounts on the same broker.
5. **Task 3B-5 — Integrated offline UX acceptance.** Verify the entire credential → challenge → response → status flow, offline construction, and regressions. No real vault/network/login/order is allowed.

**Rules for all five tasks:** implement in sequence; Architect reviews each report/diff before the next task starts; each task gets its own exact allowed-file list and focused test commands; never stage broadly or touch unrelated local work; keep account-bound trading-state, instrument identity, order routing, NATS/queue-position, and feedback fixes in the separate later phase. The current approval does not itself authorize implementation outside the individually issued task. Preserve the existing dark RTL direction and do not perform a broad redesign without separate approval.

Work through these phases in order. Each phase must be split into small tasks with exact allowed files and acceptance tests. Review evidence before beginning the next phase.

| Phase | Scope | Status |
|---|---|---|
| **1. Lock contracts and logout lifecycle** | Finalize the account-aware broker/provider manager contract and per-account runtime identity; add a public, fail-closed per-account logout operation to `AuthenticationService`; cover normal logout, cleanup failures and account isolation. | **COMPLETE — Tasks 1A and 1B reviewed/pushed** |
| **2. Compose and inject services** | Lazily compose account/session/authentication services and route dispatch through the account-scoped broker/provider registry using MainWindow's shared manager. User-facing login, active-session gating and other account-bound consumers remain later phases. | **COMPLETE within defined scope — Tasks 2A–2C reviewed/pushed** |
| **3. Connect the Accounts page** | Implement account add/edit/delete/sort/select and display name; connect credential save/removal, independent row-level login/logout/status and CAPTCHA only when the adapter requires it. The page calls services; it does not implement broker authentication or manage tokens. | **IN PROGRESS — Task 3A and Tasks 3B-1–3B-3 complete; Task 3B-4 next** |
| **4. Route all account-bound activity** | Gate order-page/order preparation on one active account with a usable logged-in session; resolve instrument provider, trading-state query, order routing, NATS/queue-position tracking and feedback through that account's runtime; preserve `DispatchCore → OrderEngine → M6-A…M6-E` and fail closed on missing/mismatched runtime. | Pending |
| **5. Regression and acceptance** | Test at least two accounts on the same broker, proving independent broker/session/provider/token/recovery state and account-correct feedback; run focused and broad regression; preserve M6 gates and keep live trading disabled. Never automatically replay `POST /order` after 401. | Pending |

#### Phase 1 — Task 1A: Public Per-Account Logout — COMPLETE (2026-10-15)

- **Implementation commit:** `9efb88e` — `feat: add safe per-account logout`, pushed to `origin/master`.
- **Only changed files:** `ui/authentication_service.py` and `test_block9_task4_authentication_service.py`.
- **Public behavior:** `AuthenticationService.logout(account_id)` performs local, account-scoped logout. It removes service references before cleanup, tries to cancel a pending login where applicable, detaches that account's recovery handler, clears the account-owned broker authentication view, calls the SessionManager logout/invalidation path, and verifies the final state before reporting cleanup success.
- **Fail-closed checks:** cleanup/cancel failures, an unverified authenticated-session clear, or an inconsistent state (logged in without an adapter / login pending without a pending adapter) must not be reported as successful logout. Error reporting is sanitized. The operation does not claim to revoke broker-side tokens.
- **Verification reported:** `python3 -m pytest -q test_block9_task4_authentication_service.py` → **75 passed in 1.00s**. Tests cover logout cleanup, failure paths, per-account isolation, and retention of another account's session.
- **Review boundary (at the Task 1A checkpoint):** Task 1A was complete, while Phase 1 remained open pending the account-aware `BrokerManager`/provider contract. That gap was closed by Task 1B, commit `39bd0d6`; Phase 1 is now complete. Phase 2 service composition and same-instance authentication/dispatch wiring remain pending.

#### Phase 1 — Task 1B: Account-Scoped BrokerManager Registry — COMPLETE (2026-10-15)

- **Implementation commit:** `39bd0d6` — `feat: add account-scoped broker registry`, pushed to `origin/master`.
- **Only changed files:** `brokers/manager.py` and `test_broker_manager.py`.
- **Account-scoped API:** added `get_for_account(account_id, broker_name)` and `get_instrument_provider_for_account(account_id, broker_name)`, keyed by the exact pair `(account_id, broker_name)`. Each account gets its own broker and provider/cache; provider resolution validates that `provider._broker` is the exact same object as that account's broker.
- **Safety and concurrency:** invalid account IDs, unknown brokers, missing/non-callable factories, invalid or reused broker/provider instances fail closed. Failed factory/provider construction is not cached, allowing retry. A shared `RLock` makes account-scoped creation thread-safe for repeated/concurrent access to the same key.
- **Backward compatibility:** existing name-based `get(name)`, `get_instrument_provider(name)` and `register(...)` remain available. No fallback from an account-bound lookup to a name-only broker/provider is allowed.
- **Verification reported by the owner:** `python3 -m pytest -q test_broker_manager.py` → **24 passed, 0 failed**. The full repository suite was not run as part of this bounded task.
- **Safety / integration boundary:** tests were offline; no real broker login or order was performed. This task changes only the registry and its tests. It does **not** yet wire `AuthenticationService`, `MainWindow`, `DispatchCore`, or order feedback to these account-scoped objects, so production account-aware routing and production 401 recovery must not yet be claimed as active.

#### Phase 2 — Task 2A: Account-Owned Broker Identity for Authentication Adapters — COMPLETE (2026-10-15)

- **Commit:** `ccdd563` — `feat: wire account-owned brokers into auth adapters`, pushed to `origin/master`.
- **Scope:** `brokers/agaah/auth_adapter.py`, `ui/authentication_service.py`, and the seven listed Task 4 / Task 5 regression files in the commit. No `MainWindow`, Accounts-page UI, or order-routing implementation was included.
- **Verified design:** `make_agah_adapter_factory(broker_manager)` returns a factory accepting `account_id`; it resolves the broker only through `broker_manager.get_for_account(account_id, "آگاه")` and injects that exact instance into `AgahAuthenticationAdapter`. The generic authentication factory contract accepts the account ID and remains broker-independent.
- **Failure cleanup:** if session registration fails after adapter login succeeds, the service removes retained/pending adapter references, attempts account-scoped authentication cleanup, and verifies the locally logged-out/token-cleared state before treating cleanup as confirmed.
- **Owner's Windows verification:** nine focused authentication, integration, 401-recovery and broker-manager test files → **287 passed in 3.12s**. No live broker login, network request, or real order was performed.
- **Not complete:** `MainWindow` still does not compose or expose `AuthenticationService`. Existing production dispatch still uses its current name-based broker path; therefore same-account auth-to-order broker identity and production account-aware order routing are **not** established by this task.

#### Phase 2 — Task 2B: Lazy Service Composition at MainWindow — COMPLETE (2026-10-15)

- **Commit:** `23802a7` — `feat: compose account authentication service lazily`, pushed to `origin/master`.
- **Changed files:** `ui/main_window.py` and `test_block9_phase2_service_composition.py` only.
- **Implementation:** `MainWindow.authentication_service` lazily composes and caches `AuthenticationService` from the existing `self.account_store`, one `CredentialStore`, one `SessionManager`, and the Agah adapter factory bound to the same cached `_shared_broker_manager()`. The service is cached only after successful construction; a failed construction can be retried. No login, CAPTCHA, vault operation, network access, or order submission is done by composition.
- **Owner-reported Windows verification:**
  - `python3 -m pytest -q test_block9_phase2_service_composition.py` → **3 passed**.
  - Focused authentication/adapter/integration/BrokerManager regression → **169 passed**.
  - `test_ui1_application_foundation.py` + `test_ui2_1_account_management.py` → **33 passed, 2 failed**. Both failures are in `AccountsPage` calling `AccountStore.add(account_id, broker_name)` without the required `display_name`; these files are outside Task 2B and remain unresolved. Do not label them pre-existing without baseline reproduction.
  - `py_compile` succeeded. The owner confirmed the staged `git diff --check` was clean.
- **Boundary:** no Accounts-page UI, dispatch, provider, feedback or order-routing code was changed. Task 2B does not make production authentication and dispatch use the same account-owned broker yet.

#### Phase 2 — Task 2C: Account-Scoped Dispatch Resolution — COMPLETE (2026-10-15)

- **Implementation commit:** `56a317b` — `feat: resolve dispatch brokers by account` (full SHA: `56a317b59a577590dd46af21f9745df25f671bea`), pushed to `origin/master`.
- **Changed files:** `core/dispatch_core.py`, `test_dispatch_core.py`, and `test_block9_phase2_dispatch_account_identity.py`.
- **Behavior:** `DispatchCore` pre-resolves the required broker and instrument provider by the explicit `(account_id, broker_name)` pair before the first order can enter `OrderEngine`. Resources are reused only for the same pair. Account-scoped resolution failures fail closed as `BLOCKED`; name-only broker/provider fallbacks are not used. The existing `DispatchCore → OrderEngine → M6-A…M6-E` chain remains.
- **Reported verification (offline):** `python3 -m pytest -q test_block9_phase2_dispatch_account_identity.py` → **4 passed**; `python3 -m pytest -q test_dispatch_core.py test_execution_planner.py test_broker_manager.py` → **67 passed**; staged `git diff --cached --check` → passed. The agent environment did not provide the Windows `py` launcher, so the equivalent `python3` commands were used.
- **Safety:** tests use mocks/offline seams; no credentials, live broker request, or real order was used. Live trading remains disabled.
- **Architecture-audit outcome:** `MainWindow.authentication_service` and the real `TestRunner` receive the same cached `BrokerManager`; the adapter factory and `DispatchCore` both resolve account-owned resources by `(account_id, broker_name)`. However, `AccountsPage` does not call `AuthenticationService`, so user-driven login/logout is not yet wired. `MainWindow._real_trading_state_query()` and `_real_feedback_broker_factory()` still use name-only broker/provider APIs, and `ui/order_configuration_page.py::_default_order_identity_resolver()` constructs a separate `BrokerManager` and resolves by broker name. These account-bound consumers remain later work; do not claim the whole account runtime/feedback flow is integrated.
**Execution rule:** Keep tasks small and review evidence before implementation. Phase 3 Task 3A (display-name contract) is complete and pushed as `fbdc112`. Next is Phase 3 Task 3B: a read-only source review and Accounts-page authentication UX/integration proposal for Product Owner approval; no code or documentation changes and no authentication implementation are authorized in Task 3B. Keep account-bound trading-state, instrument identity and feedback routing separately scoped for Phase 4. Preserve the accepted UI direction, offline construction guarantees, `DispatchCore → OrderEngine → M6-A…M6-E`, and the no-automatic-`POST /order`-retry rule.

#### Overview

The user must be able to introduce an account once, choose a display name, later select it from a table and Login/Logout, enter Captcha if needed, view each account's status independently, and for entering the order page, must have exactly one Active Account that is also Logged In with a Valid Session.

The system must be scalable for multiple accounts and in the future multiple Brokers, but only actually-existing Brokers in the repository are implemented. No unknown API or behavior should be guessed.

#### Flow

```
Add Account → Select Broker → Account name + account_id → Secure Credential Storage → Display in Table
Select Account → Login → Captcha if needed → Successful Login → Independent Session → Logged-in Status
Select Active Account → Verify Login/Session → Enter Order Page → Use that Account
```

#### Sub-tasks

1. **Account Management Foundation**
   - Add, edit, delete, select, and sort accounts
   - Independent display name
   - Active Account
   - Compatibility preservation with `Account`

2. **Secure Credential Store**
   - Secure storage and retrieval of Username/Password
   - Delete Credential when account is deleted
   - No Credential storage in Account Model/AccountStore

3. **Account Session Manager**
   - Independent session per account
   - Login state
   - Logout
   - Token lifecycle
   - Prevent session mixing

4. **Agah Login & Captcha Flow**
   - Connect real Agah login to account session
   - Use existing `get_captcha()` and `login()`
   - Show Captcha only when needed
   - Successful Login only after real success

5. **Token / Session Lifecycle**
   - Real Access Token / Refresh Token verification
   - Refresh or re-Login based on real API behavior
   - Session persistence and expiration/error management
   - No guessing of API behavior

6. **Accounts Page Visual & UX Redesign**
   - Complete redesign of Accounts page based on new model
   - Central table for account management
   - Clear status
   - Login / Logout / Edit / Delete / Select
   - Captcha only during Login when needed
   - **Before implementation, visual design must be presented and approved by Product Owner/Architect**

7. **Login / Logout UI Integration**
   - Independent Login and Logout per row
   - Independent status display per account
   - No impact of one account on another's session

8. **Order Page Access Gate**
   - Access to order page only if:
     `Active Account exists + Logged In + Valid Session`
   - Otherwise prevent entry/order preparation
   - Gate at appropriate Application/UI layer

9. **Account-Aware Order Routing**
   - Active Account → Session of that account → Broker Instance/Adapter of that account → existing `DispatchCore → OrderEngine → M6` path
   - No Account/Session mixing
   - No parallel order path creation

10. **Full Regression & Acceptance**
    - Test Add/Edit/Delete/Sort/Select/Login/Logout/Captcha
    - Test multiple accounts and multiple sessions
    - Test Order Page Gate
    - Test Account-aware routing
    - Regression on UI/Core/M6/Block 8
    - Live Trading must not be accidentally enabled

#### Task 1 — Account Management Foundation — COMPLETED

`ui/account_store.py` implements the final Block 9 Task 1 contract:

- `AccountRecord` has exactly three fields: `account` (the existing `models.account.Account`), `broker_name: str`, and `display_name: str`.
- `AccountStore.add(account_id, broker_name, display_name)` is the final signature; `display_name` is required.
- `display_name` must be a `str`, non-empty and non-whitespace (surrounding whitespace is trimmed), and is independent of `account_id` (never derived from it by the store).
- `display_name` lives on `AccountRecord` only — it is NOT added to `models.account.Account`.
- No credential / password / token / session is stored in `Account` or `AccountRecord` in this task.
- `add()` validation order: `broker_name` → `account_id` (None check) → `Account` construction → duplicate check → `display_name` → `AccountRecord`. An invalid `account_id` is rejected for its own reason, not `display_name`'s.
- `set_active` / `active_account_id` / `is_active` / `all_accounts` ordering behavior is unchanged.
- `ui/accounts_page.py` was NOT modified (out of scope for this task).

Tests:

- `test_ui2_1_account_management.py` gained `display_name` contract tests plus `test_display_name_is_required` (missing `display_name` → `TypeError`).
- All 16 UI test files were migrated to the three-argument `store.add(account_id, broker_name, display_name)` call.
- Task-specific run: `20 passed, 2 failed`. The two failures (`test_11_accounts_page_creates_no_real_broker`, `test_extra_page_add_and_active_flow`) are caused by the still-unmigrated `ui/accounts_page.py` calling `store.add(account_id, broker_name)` with two arguments; they are intentionally out of scope here and must be resolved in the later UI redesign task (sub-task 6).
- Full suite: `1386 passed, 4 failed` — two pre-existing Block 8 `broker_received_at` contract failures (unchanged) plus the two UI failures above. No new failure was introduced.

Task 2 — Secure Credential Store: **COMPLETED and independently verified.** Commit `4dc4231 — feat: add secure credential store foundation` exists in git history. Independent verification evidence: `test_block9_task2a_credential_store.py` — **71 passed**, exit code successful. `ui/credential_store.py` is broker-independent (imports nothing from `brokers/`, `core/`, `market/`, `models/` or `main.py`), stores credentials only in the OS secure vault addressed by `(service_id, account_id)`, and never writes credentials to any model, file or environment variable. No real credential, broker or network was used.

Task 3 — Account Session Manager: **COMPLETED and independently verified.** Commit `4ce8aab — feat: add account session manager` exists in git history. Independent verification evidence: `test_block9_task3_session_manager.py` — **56 passed**, exit code successful. `ui/session_manager.py` is broker-independent (imports nothing from `brokers/`, `core/`, `market/`, `models/` or `main.py`), tracks per-account login state independently, and rejects overlapping login flows and invalid state transitions fail-closed. Tokens are held in memory only and never written to a `Session` snapshot, a model, a file or an error message. No real credential, broker or network was used.

Completed: **Task 5 Stage 3 — Final Offline Integration and Regression Audit** was accepted on 2026-10-16. Next: account-management Task 9 — Account-Aware Order Routing. Decision 031 requires each `(account_id, broker_name)` to own its broker/HTTP session/token state, authentication adapter/recovery callback and provider/cache. Phase 1 Tasks 1A–1B and Phase 2 Tasks 2A–2C are complete; MainWindow shares its cached BrokerManager between AuthenticationService’s adapter factory and TestRunner/DispatchCore. DispatchCore resolves each request via `get_for_account(account_id, broker_name)` and `get_instrument_provider_for_account(account_id, broker_name)`, and the auth adapter factory resolves the same account-owned pair through that manager. Task 5 Stages 1, 2A, 2B, 2C.1, 2C.2, 2C.3a and 2C.3b are complete; Stage 2C is closed. Commit `2df4eed` adds a fake-session guard against replaying `POST /order` after 401. The earlier owner-run Block 9 regression reported **524 passed**; no real broker request or order was made. Remaining Task 9 routing gaps are the name-only trading-state query, separate-manager default order identity resolver, missing active-account + usable-session order gate, and name-only account feedback path. Account-management Task 9 is distinct from the simulation/stress test roadmap `test_block9_task9_1.py`–`test_block9_task9_7.py`.

#### Task 4 — Agah Login & Captcha Flow — Execution Plan

**Status:** IN PROGRESS — Stage 1 (Architecture Review & Contract) COMPLETED; **Stage 2 (Agah Login Implementation) COMPLETED**; **Stage 3 (Integration & Regression) COMPLETED**. Task 4 connects real Agah login (including CAPTCHA) to the per-account session state introduced in Task 3, without redesigning the existing account / session / broker / order architecture. The three stages below MUST be executed in order.

**Stage 1 — Architecture Review & Contract**
- Review the current account, session, broker, and order-placement architecture.
- Define a common authentication contract that is broker-independent.
- Determine how each account is assigned its own broker instance and independent session.
- Review `BrokerManager` dependencies and the current order-placement path.
- This stage is review and design only; NO code may be changed.
- Until this review is complete, NO implementation task may be issued.

**Stage 2 — Agah Login Implementation** — COMPLETED
- Implement the common contract and the Agah-specific adapter based on the Stage 1 results.
- Connect the stored credentials to the login flow and connect the login result to `SessionManager`.
- Use only the real, existing Agah API behavior for login and CAPTCHA; unknown behavior MUST NOT be guessed.
- Record login state only after a real, confirmed successful login.
- Test successful login, failed login, and the independence of two accounts' sessions.

##### Stage 2 — Completion Report

- **Broker-independent authentication contract** implemented in `brokers/authentication.py`.
- **Authentication service** implemented in `ui/authentication_service.py`, with the **Agaah-specific adapter** in `brokers/agaah/auth_adapter.py`. Agah-specific logic lives only in the adapter; the contract and the service remain broker-independent.
- **Tests** added for all three layers: the contract (`test_block9_task4_authentication_contract.py`), the service (`test_block9_task4_authentication_service.py`), and the Agaah adapter (`test_block9_task4_agah_auth_adapter.py`).
- **Commit:** `51ee992` — `feat: add broker authentication and Agaah login adapter`.
- **Actual test result for Task 4:** **107 passed**; pytest exit code successful.
- **Test method / honesty boundary:** the tests run against test doubles and an injected fake HTTP session. They do NOT perform a real login against a real user account and do NOT open a live connection to the broker. No real, live authentication is claimed or exercised.
- **Architectural constraints preserved:** the existing `DispatchCore → OrderEngine → M6` path is unchanged; token lifecycle, expiry, renewal and persistence remain OUT OF SCOPE for Task 4 (deferred to Task 5); the confirmed Agah CAPTCHA requirement is respected and CAPTCHA-less login is not assumed.
- **Real trading:** disabled. No real order was sent and no real broker login was performed.

**Stage 3 — Integration & Regression** — COMPLETED
- Integrate with the current application structure and keep the existing order-placement path intact; this does NOT include full account-aware order routing (out of scope — sub-task 9).
- Verify that sessions and authentication data of different accounts do not interfere.
- Ensure no parallel order-placement path is created.
- Run the relevant tests and regression.
- Report the exact tests run, their results, and any pre-existing errors.

##### Stage 3 — Completion Report

- **Changed files:** `test_block9_task4_integration.py` (new; the only code change) and this documentation record. No production program file was changed; the `DispatchCore → OrderEngine → M6` order path, `BrokerManager`, `MainWindow`, `ui/accounts_page.py` and `ui/order_configuration_page.py` are untouched.
- **Integration scenario (fully offline):** the real `AccountStore`, `CredentialStore` (with an in-memory stub backend), `SessionManager`, `AuthenticationService`, real `AgahAuthenticationAdapter`, and the real `AgaahBroker.get_captcha()`/`login()` logic are wired together; the only replaced seams are the OS credential vault (→ in-memory stub) and the HTTP transport (→ per-account in-memory fake session serving the same response shapes the real broker code parses). No real network request, real account, credential, token or order is used.
- **Test result:** `test_block9_task4_integration.py` — **19 passed** (exit 0).
- **Independence proven (explicit tests):** two Agah accounts get two independent adapters/brokers/HTTP sessions; each account's credentials reach only its own adapter; a successful login of one does not log the other in; each account's token is recorded only in its own session and never swapped; a failure or cancel of one account leaves the other untouched; incomplete/failed broker responses never mark a login successful; no password/access token/refresh token leaks through an error message, exception chain or public output; no real network request is sent (socket patched).
- **Regression (12 files, run at repo root with `python3 -m pytest -q`):** integration **19 passed**; authentication_contract **21 passed**; agah_auth_adapter **46 passed**; authentication_service **40 passed**; task2a_credential_store **64 passed, 7 skipped**; task3_session_manager **56 passed**; broker_manager **18 passed**; dispatch_core **17 passed**; ui1_application_foundation **13 passed**; ui3_1_order_configuration **32 passed**; ui2_1_account_management **20 passed / 2 failed** (exit 1); order_engine **0 items collected** (exit 5, it is an interactive script, not a pytest suite). Combined Task 2/3/4 auth suites plus integration: **246 passed, 7 skipped, 2 failed**.
- **Pre-existing failures (NOT caused by Stage 3, reported separately):** `test_ui2_1_account_management.py::test_11_accounts_page_creates_no_real_broker` and `test_ui2_1_account_management.py::test_extra_page_add_and_active_flow` fail because `ui/accounts_page.py` (line 152) calls `self.store.add(account_id, broker_name)` with two arguments while `AccountStore.add(account_id, broker_name, display_name)` requires three. Both files are byte-identical to HEAD (verified with `git status`/`git diff`) and the failure reproduces when the file is run in isolation. Proposed fix (not applied here, separate scope): pass a display-name argument at the accounts-page call site.
- **Real trading / real login:** disabled. No real broker login, no real CAPTCHA and no real order were performed anywhere in this stage.
- **Commit:** none; nothing was committed or pushed.

##### Post-Review Correction — Final Verification

This addendum records one architectural-review correction and its real, offline verification. It does not change any production logic beyond the reorder described below, and it does not alter the accepted Task 2 / Task 3 results or the historical Stage 3 report above.

- **Correction (login-state check order):** in `ui/authentication_service.py`, `begin_login()` now checks the account's current session state (`LOGGED_IN`, then `LOGIN_PENDING`) immediately after resolving the account and session, *before* building an adapter, reading credentials, or issuing the broker captcha request. Only after passing that check does it reserve the session (`LOGGED_OUT → LOGIN_PENDING`), build the adapter, load credentials, and fetch the challenge. A failure after reservation clears the temporary attempt and returns the session to `LOGGED_OUT`. This avoids the previous order, in which a rejected duplicate attempt could construct an adapter / read credentials / contact the broker before the rejection was detected. No order-placement path, broker API, session contract, or other production file was changed.
- **No-extra-request tests (integration, fully offline):** the two existing rejection tests in `test_block9_task4_integration.py` were completed rather than duplicated; no new duplicate test was created. The fake per-account HTTP session is the `FakeAgahSession` installed on the real `AgaahBroker.session`; its request list is snapshotted before the rejected attempt and compared afterwards.
  - `test_relogin_while_logged_in_rejected_no_factory_call` — account already `LOGGED_IN`: the second `begin_login` raises `AuthenticationServiceError`; the HTTP request count is unchanged; the adapter instance, session state (`LOGGED_IN`) and token (`ACCESS_A`) are untouched.
  - `test_second_login_attempt_while_pending_rejected_no_extra_work` — a first login attempt is still `LOGIN_PENDING`: the second `begin_login` raises `AuthenticationServiceError`; the HTTP request count is unchanged; the pending adapter, the `LOGIN_PENDING` state and the absent token are untouched; the first attempt still completes to `LOGGED_IN` using the same adapter.
- **Commands executed and exact results** (repo root; Python 3.14.4, pytest 9.1.1; UI files run with `QT_QPA_PLATFORM=offscreen`):
  - `python3 -m pytest -q test_block9_task4_authentication_service.py` → **47 passed** (exit 0)
  - `python3 -m pytest -q test_block9_task4_integration.py` → **23 passed** (exit 0)
  - `python3 -m pytest -q test_block9_task4_authentication_contract.py` → **21 passed** (exit 0)
  - `python3 -m pytest -q test_block9_task4_agah_auth_adapter.py` → **46 passed** (exit 0)
  - `python3 -m pytest -q test_block9_task2a_credential_store.py` → **64 passed, 7 skipped** (exit 0)
  - `python3 -m pytest -q test_block9_task3_session_manager.py` → **56 passed** (exit 0)
  - `python3 -m pytest -q test_broker_manager.py` → **18 passed** (exit 0)
  - `python3 -m pytest -q test_dispatch_core.py` → **17 passed** (exit 0)
  - `QT_QPA_PLATFORM=offscreen python3 -m pytest -q test_ui1_application_foundation.py` → **13 passed** (exit 0)
  - `QT_QPA_PLATFORM=offscreen python3 -m pytest -q test_ui2_1_account_management.py` → **20 passed, 2 failed** (exit 1)
  - `QT_QPA_PLATFORM=offscreen python3 -m pytest -q test_ui3_1_order_configuration.py` → **32 passed** (exit 0)
  - `test_order_engine.py` was **not** run as pytest: it is an interactive script, not a test suite.
- **Known pre-existing errors (reported separately; NOT caused by and NOT attributed to this correction):** `test_ui2_1_account_management.py::test_11_accounts_page_creates_no_real_broker` and `test_ui2_1_account_management.py::test_extra_page_add_and_active_flow` fail with `TypeError: AccountStore.add() missing 1 required positional argument: 'display_name'` at `ui/accounts_page.py:152`, where `self.store.add(account_id, broker_name)` is called while `AccountStore.add(account_id, broker_name, display_name)` requires three arguments. `ui/accounts_page.py` is byte-identical to HEAD (verified with `git status`/`git diff`); the failure reproduces in isolation and is unchanged from the Stage 3 report above.
- **Scope / honesty boundary:** only `test_block9_task4_integration.py` and this memory file were changed by this addendum. The already-present working-tree changes in `ui/authentication_service.py` and `test_block9_task4_authentication_service.py` were preserved, not rewritten. No real network request, real account, real credential, real CAPTCHA, or real order was used, and no live connection was opened. Nothing was committed or pushed.

#### Task 4 — Architectural Constraints (Broker-Independent Auth Boundary)

1. The common authentication architecture MUST be broker-independent; Agah-specific logic MUST live only in the Agah adapter.
2. Every account MUST have independent authentication state and an independent session.
3. A single broker instance with mutable authentication state MUST NOT be shared across multiple accounts.
4. The existing `DispatchCore → OrderEngine → M6` path MUST be preserved; any necessary change to its dependencies MUST first be documented and justified in Stage 1.
5. Token lifecycle, expiry, renewal, and persistence are OUT OF SCOPE for this task and are handled in **Task 5**.
6. Redesigning the Accounts page, the general login/logout UI integration, restricting access to the order page, and full account-aware routing are OUT OF SCOPE for Task 4 and are performed in later tasks per the roadmap (sub-tasks 6, 7, 8, 9).
7. CAPTCHA display MUST follow the confirmed API behavior; because the current Agah method requires CAPTCHA, CAPTCHA-less login MUST NOT be assumed.

#### Task 5 — Token / Session Lifecycle — Execution Plan

**Status:** Stage 1, Stage 2A (Agah Refresh Primitive), and Stage 2B (Per-Account Session and Token Replacement) are **COMPLETED and reviewed**. Stage 2C.1 (bounded recovery for four broker read-only GETs) and Stage 2C.2 (instrument search) are also **COMPLETED and reviewed**. Stage 2C, including NATS and queue-position request paths, and Task 5 Stage 3 are **COMPLETE within scope**. Account-aware order routing remains separate under Task 9.

##### Stage 1 — Discovery Findings (Verified vs. Unverified)

**Evidence source:** The project owner inspected the official Agah Online application's browser Sources/Network code. This records observed client behavior only; it does not establish every server-side guarantee. No real token values or user-specific data are recorded here.

**Verified from the inspected browser client code**
- Refresh endpoint: `POST https://tseonlineapi.agah.com/api/v1/users/refresh-token`.
- Request JSON fields: `accessToken` and `refreshToken` (the currently stored token values).
- On a response where `isSuccess` is true, the client reads `data.accessToken` and `data.refreshToken` and stores both.
- The client's HTTP error handling attempts refresh for certain `401` responses when both tokens are available, then retries the original request after a successful refresh. If refresh fails, or if a refresh-token/NATS-pusher request returns `401`/`403`, the client logs out and redirects. A specific OIDC invalid-token error also triggers logout.
- The website's `silentRenew: false` / `useRefreshToken: false` settings belong to its separate OIDC configuration; they do not negate the custom API refresh method observed above.
- The browser client stores the tokens in browser storage after client-side AES-CBC encryption. This implementation must NOT be copied into Trading_bot as a token-persistence design.

**Verified from the current Python repository**
- `AgaahBroker.login()` parses `accessToken`, `refreshToken`, and `userIdentifier` and holds them on that account's broker instance (`brokers/agaah/broker.py`).
- The retained Agah adapter also holds an immutable `AuthenticatedSession` containing both tokens. `AuthenticationService` retains one adapter per account.
- `SessionManager` stores only the access token in memory; it has no atomic token-replacement API for an already-`LOGGED_IN` account.
- Authenticated request paths use `_auth_headers()` and call `raise_for_status()`; the production Python code currently has no refresh endpoint method, no dedicated `401` handling, no token replacement after login, and no refresh/retry coordination.
- Tokens are not persisted to disk, configuration, environment variables, or the OS credential vault. Keep this boundary: the OS vault stores login credentials only; access and refresh tokens remain in memory.
- Existing offline test seams include the replaceable `AgaahBroker.session`, fake HTTP sessions/responses from Task 4 tests, injected adapter factories, and a directly testable `SessionManager`.

**Open questions — do not guess**
- Exact server behavior for HTTP failures versus an `isSuccess: false` response envelope.
- Whether refresh tokens are single-use/rotated on every success, and what happens if the refresh response is incomplete.
- Any headers beyond the observed JSON fields that the endpoint may require.
- Actual token lifetime and whether every `401` represents expiration.
- Whether the server guarantees a live order was not accepted whenever its response is `401`. Until independently established, treat live-order retry as a safety-sensitive operation and do not automatically replay a live `POST /order`.

##### Task 5 Roadmap

**Stage 1 — Read-Only Audit: COMPLETED**
- Trace tokens through the broker, adapter, authentication service, and SessionManager.
- Inventory authenticated HTTP paths and their current error handling.
- Record observed browser-client refresh behavior separately from unverified server semantics.
- No source files were modified and no tests or live requests were executed during this audit.

**Stage 2A — Agah Refresh Primitive and Independent Tests: COMPLETED and reviewed**
- Allowed and changed files only: `brokers/agaah/broker.py` and new `test_block9_task5_refresh_token.py`.
- Added `AgaahBroker.refresh_tokens()`, using the discovered endpoint `POST /api/v1/users/refresh-token` and the confirmed JSON fields `accessToken` / `refreshToken`.
- Both current tokens are required before sending a request. The method validates the HTTP response, JSON envelope, requires `isSuccess is True` (JSON boolean only), and validates both replacement tokens before changing either broker attribute.
- Failures leave both original token values unchanged and raise a sanitized error without exposing the old/new token values or sensitive exception context. No token persistence was added.
- Tests use fake HTTP responses/sessions and an offline socket guard; no live broker calls, real credentials, real tokens, CAPTCHA, or orders were used.
- No automatic `401` interception/retry, SessionManager/auth-adapter integration, UI change, order-path change, or commit/push was performed by the Stage 2A agent.

##### Stage 2A — Verification and Review Record
- Owner-run compile command: `py -3 -m py_compile brokers/agaah/broker.py test_block9_task5_refresh_token.py` → successful (exit 0).
- Owner-run refresh tests: `py -3 -m pytest -q test_block9_task5_refresh_token.py` → **57 passed** (exit 0; 1.27s).
- Owner-run related Agah / Task 4 regression: `py -3 -m pytest -q test_agah_instrument.py test_agah_login.py test_block9_task4_agah_auth_adapter.py test_block9_task4_authentication_contract.py test_block9_task4_authentication_service.py test_block9_task4_integration.py` → **137 passed** (exit 0; 1.00s).
- Architect review: inspected the added `refresh_tokens()` implementation and the full new test file in three sections. The implementation validates replacement tokens before assignment, fails closed on non-boolean success flags, preserves prior tokens on failure, avoids secret-bearing error context, and makes no automatic retry.
- Total across the two pytest commands above: **194 passed**, with no failures reported.
- Stage 2A provides the broker-level refresh primitive. Stage 2B synchronization across the broker, adapter, AuthenticationService and SessionManager is completed and recorded below. HTTP 401 handling, bounded retry, and concurrent-refresh coordination remain unimplemented and belong to Stage 2C.


**Stage 2B — Per-Account Session and Token Replacement: COMPLETED and reviewed**
- Added a broker-independent `SessionManager.replace_token(account_id, token)` API. It only replaces a non-empty access token for an already-`LOGGED_IN` account and preserves that account's state and public `Session` snapshot; unknown accounts or invalid states fail closed.
- Added `SessionManager.invalidate_session(account_id)` as an emergency, idempotent local invalidation path that is independent of `logout()`. It sets only that account to `LOGGED_OUT` and clears its in-memory token. It does not claim to revoke broker-side tokens.
- Integrated explicit `AuthenticationService.refresh_session(account_id)` through the broker-independent adapter contract. The service checks login/adaptor state, validates the refreshed access-token view, then synchronizes the SessionManager token. No automatic refresh trigger, 401 handling/retry, UI change, token persistence, or order-dispatch change was introduced.
- On token-sync failure, the service removes the account's adapter, attempts the existing logout path, and uses emergency invalidation if logout fails. If all cleanup paths fail, it emits a sanitized error explicitly stating that emergency invalidation did not succeed and a safe state is not confirmed. The test deliberately verifies the real unresolved local state in this final-failure case rather than falsely asserting safety.
- Per-account isolation is verified: invalidation of account A does not alter account B's login state, token, or adapter. Tests also check secret non-disclosure through messages, `repr`, and exception chains.

##### Stage 2B — Verification and Review Record
- **Changed files (commit `3258a351a420a3ea98c57b0f289c9a6145adb33e`):** `brokers/agaah/auth_adapter.py`, `brokers/authentication.py`, `ui/authentication_service.py`, `ui/session_manager.py`, and new `test_block9_task5_token_sync.py`.
- **Final Stage 2B test:** `python3 -m pytest -q test_block9_task5_token_sync.py` → **55 passed** (exit 0; run after the final explicit unsafe-state assertion was added).
- **Focused final-failure test:** `python3 -m pytest -q test_block9_task5_token_sync.py -k "sync_logout_and_invalidate_failure" -v` → **1 passed, 54 deselected** (exit 0).
- **Related authentication regression:** `python -m pytest -q test_block9_task3_session_manager.py test_block9_task4_agah_auth_adapter.py test_block9_task4_authentication_contract.py test_block9_task4_authentication_service.py test_block9_task4_integration.py test_block9_task5_refresh_token.py test_block9_task5_token_sync.py` → **304 passed** (exit 0; run before the final assertion-only strengthening; the final Task 5 suite was rerun afterward).
- The tests use fake/offline broker transports and do not perform real broker login, send orders, or enable live trading. No commit/push was performed by the test agent; implementation commit is `3258a351a420a3ea98c57b0f289c9a6145adb33e`.

##### Stage 2B — Final Cleanup and Secret-Leak Regression (follow-up verification, 2026-10-15)

- **Follow-up test commit:** `31d7063` — `test: cover token sync failure cleanup`, pushed to `master`. This commit changes only `test_block9_task5_token_sync.py` (92 insertions); it does not change production code.
- **Exact owner-run command and result:** `py -3 -m pytest -q test_block9_task5_token_sync.py` → **56 passed in 0.65s** (exit 0).
- **Adapter removal despite logout failure:** `test_service_sync_and_logout_failure_adapter_removal_independent_of_logout` injects failures into `replace_token()` and `logout()` with token-bearing fault messages. It verifies the account's adapter is removed before the logout attempt, `get_adapter()` no longer exposes it, emergency local invalidation clears that account's token and sets it to `LOGGED_OUT`, and a subsequent refresh is refused.
- **Secret-leak surfaces:** the regression checks old/new access and refresh token values across the public error message, `str`, `repr`, reachable `__context__` / `__cause__` chain and formatted traceback. The injected fault messages must not appear in the public error.
- **All-cleanup-paths-fail case:** `test_service_sync_logout_and_invalidate_failure_stays_unresolved_and_explicit` verifies that if emergency invalidation also fails, the service explicitly reports that a safe state was NOT confirmed; it does not falsely claim the session was cleared. The test checks the actual unresolved state and secret non-disclosure.
- **Review conclusion:** the token-sync failure cleanup and exception-leak regression is verified by this test run. No live broker call, real credential, real token or order was used. This follow-up does not implement HTTP 401 handling/retry or renewal coordination.

#### Stage 2C.1 — Bounded HTTP 401 Recovery for Four Agah Read-Only GET Paths — COMPLETED and reviewed

- **Implementation commit:** `4c185ab23f6717af79b69ac026c1a7b988b722a6` — `feat: add bounded Agah 401 token recovery`, pushed to `master` after rebasing onto the documentation update commit `ac8cb67`.
- **Changed files in the implementation commit:** `brokers/authentication.py`, `brokers/agaah/auth_adapter.py`, `brokers/agaah/broker.py`, `ui/authentication_service.py`, and new `test_block9_task5_401_handling.py`. The unrelated working-tree change to `ui/test_runner.py` was not included.
- **Scope:** bounded 401 recovery only for `AgaahBroker.get_buy_capacity()`, `get_sell_capacity()`, `get_account()`, and `get_instrument()`. A genuine HTTP status 401 is checked before `raise_for_status()`. Recovery is called through the installed account-scoped callback / adapter / `AuthenticationService`, not by calling the broker refresh primitive directly from the GET helper. The original GET is retried at most once; a second 401 does not cause another refresh or retry. Without a handler, the request fails closed.
- **Concurrency correction:** the exact access token used to build the original Authorization header is captured before sending the request. Under the per-broker token lock, recovery only runs if that same token is still current; otherwise the request reuses the token already installed by the overlapping refresh. A deterministic event-coordinated regression test proves a pre-fix behavior would trigger a second refresh.
- **Failure cleanup:** the service detaches recovery, clears the account-owned adapter/broker authentication view where supported, removes the adapter, attempts logout and then emergency local invalidation, and verifies `LOGGED_OUT` plus an empty `SessionManager` token before claiming successful cleanup. If that state cannot be confirmed, the public error explicitly says the safe state is unconfirmed. Per-account isolation and token non-disclosure are tested.
- **New test file:** `test_block9_task5_401_handling.py` — **26 tests** after the five review-correction tests were added.
- **Exact focused verification reported by the owner/agent** (the prescribed `py -3` executable was unavailable in the Linux test environment, so equivalent `python3` commands were run with Python 3.14.4):
  - `python3 -m pytest -q test_block9_task5_401_handling.py test_block9_task5_token_sync.py test_block9_task5_refresh_token.py` → **139 passed**.
  - `python3 -m pytest -q test_block9_task3_session_manager.py test_block9_task4_agah_auth_adapter.py test_block9_task4_authentication_contract.py test_block9_task4_authentication_service.py test_block9_task4_integration.py` → **193 passed**.
  - All Block 9 suites → **481 passed, 7 skipped**.
  - Broader run excluding `test_main_order_workflow.py` and `test_ui5_task4_stage2_queue_position.py` → **1714 passed, 20 skipped, 13 failed**. The report attributes the 13 failures to two existing `broker_received_at` contract failures and 11 environment failures caused by missing `nats`; those failures are recorded, not silently treated as passing.
- **Safety / honesty boundary:** tests use fake/offline HTTP sessions and report no real socket use. `POST /order` is never automatically replayed. No UI, order-dispatch, `BrokerManager`, `SessionManager`, instrument-provider, NATS/queue-position, or live-trading permission code was changed.
- **Remaining production integration gap, explicitly unresolved:** `AuthenticationService` installs the recovery handler on the account-owned broker created by that account's authentication adapter. The current `DispatchCore` order path still resolves a broker from `BrokerManager`, a different instance. Stage 2C.1 does NOT prove that the production order path uses the account-owned broker, does NOT implement account-aware routing, and does NOT authorize sharing a mutable authenticated broker across accounts. Account-aware routing remains a separate roadmap task.
- **Review conclusion:** Stage 2C.1 is completed and reviewed within its stated scope. This does NOT mark the whole Task 5 Stage 2C complete.

#### Stage 2C.2 — Bounded HTTP 401 Recovery for Agah Instrument Search — COMPLETED and reviewed

- **Implementation commit:** `55189733e3d0515cff427bca231b5ff9281a38c3` — `fix: recover Agah instrument search from expired token`; pushed to `origin/master`.
- **Exactly four changed files:** `brokers/agaah/instrument_provider.py`, `test_instrument_provider.py`, `test_engine_provider_integration.py`, and new `test_block9_task5_401_instrument_provider.py`.
- **Production behavior:** `AgaahInstrumentProvider._search_candidates()` delegates the search to the existing `AgaahBroker._authed_get_with_recovery()` helper. The helper owns the only retry (at most once); the provider adds no direct refresh and no `session.get()` fallback. The endpoint, query/count parameters, timeout-equivalent behavior, exact `tse_id == ins_code` mapping, provider cache behavior, and `InstrumentLookupError` failure contract remain covered.
- **Test fakes:** the two existing fake brokers received only minimal helper-interface shims; their existing test logic was not redesigned.
- **Security/offline tests:** the new suite contains 8 tests using a fake HTTP session and the real authentication service/adapter wiring. Tests cover real 401 recovery, refreshed-token/header and parameter preservation, second-401 stop, no-handler fail-closed, non-401 behavior, no secret leakage (including the saved password) across error text/repr/exception chain/traceback, cache behavior after failed recovery, exact mapping, and no real socket use.
- **Verification reported after the final password-leak assertion:** `python3 -m pytest -q test_block9_task5_401_instrument_provider.py` → **8 passed**; Stage 2C.1 regression → **139 passed**; Task 3/4 authentication regression → **193 passed**; all Block 9 suites → **489 passed, 7 skipped**.
- **Broader-suite caveat:** the prior broader run reported **1722 passed, 20 skipped, 13 failed** with the same known pre-existing failures: Block 8 `broker_received_at` contract failures, environment-related `nats` import failures, and existing `AccountStore.add(..., display_name)` contract failures in UI tests. The full broader suite was not rerun after the final test-only password assertion; all Block 9 tests were rerun successfully.
- **Production integration boundary remains unresolved:** the recovery handler is installed by `AuthenticationService` on an account-owned broker instance. A `BrokerManager`/`DispatchCore` consumer may still hold a different broker instance. Stage 2C.2 therefore does not prove that the production instrument-provider/order path always uses the account-owned broker with that handler. Do not share one mutable authenticated broker across accounts; full account-aware routing remains a separate Block 9 Task 9 item.
- **Review conclusion:** Stage 2C.2 is accepted within its narrow scope. It does not complete Task 5 or all of Stage 2C. Live trading remains disabled; no real credentials, broker calls, network calls, or orders were used.

#### Stage 2C.3a — NATS Bootstrap GET Recovery — COMPLETED and reviewed

- Commit 8f57b01 adds bounded recovery for NATS bootstrap GETs pusher/nats and Pusher/message-types through the existing helper via asyncio.to_thread.
- Owner-run offline regression: 53 passed; no real network, broker login or order.

#### Stage 2C.3b — Queue-Position GET Recovery — COMPLETED and reviewed

- Commit 0e4b321 routes order/getorderposition through the recovery helper while preserving parameters, response conversion and the None error contract; queue_position.py remained unchanged.
- Owner-run offline regression: 52 passed; no real network, broker login or order.

#### Stage 2C — Final Disposition: COMPLETE within scope

- Remaining authenticated Agah GET paths were reviewed and routed through bounded 401 recovery; the read-only audit found no other in-scope authenticated GET bypass.
- Eligible read-only GETs retry at most once after successful refresh. A live POST /order is never automatically replayed after 401.
- Stage 2C.1, 2C.2, 2C.3a and 2C.3b are complete and reviewed. Task 5 Stage 3 was subsequently executed and accepted on 2026-10-16; it is no longer pending.
- Task 9 account-aware production order routing remains separate; Task 5 closeout is not proof of order authorization or account-correct feedback.

**Stage 3 — Offline Integration and Regression — COMPLETE and ACCEPTED (2026-10-16)**

- **Suite 1 — Task 5 refresh/token synchronization/401 recovery, including NATS and queue-position paths:** executed with `/tmp/block9-stage3-venv-final/bin/python -m pytest -q test_block9_task5_refresh_token.py test_block9_task5_token_sync.py test_block9_task5_401_handling.py test_block9_task5_401_instrument_provider.py test_block9_task5_401_nats_transport.py test_block9_task5_401_queue_position.py` → **175 passed in 2.28s**. Both the NATS and queue-position test modules were collected and executed successfully.
- **Suite 2 — session/authentication/broker/dispatch regression:** `python3 -m pytest -q test_block9_task3_session_manager.py test_block9_task4_authentication_contract.py test_block9_task4_authentication_service.py test_block9_task4_agah_auth_adapter.py test_block9_task4_integration.py test_broker_manager.py test_dispatch_core.py test_block9_phase2_dispatch_account_identity.py` → **267 passed in 4.62s**.
- **Suite 3 — Accounts-page UI integration regression:** `python3 -m pytest -q test_block9_phase3_accounts_ui_integration.py test_ui1_application_foundation.py test_ui2_1_account_management.py` → **60 passed in 5.65s**.
- **Combined result:** 502 passing test executions across the three successful commands; no failures or skips were reported in these outputs.
- **Environment resolution:** system Python initially lacked `nats-py` and could not create a venv because `python3.14-venv` required administrator access. `uv` was installed under `/tmp/uv-bin`, a venv was created under `/tmp/block9-stage3-venv-final`, and `nats-py==2.16.0` was installed only into that temporary environment. No project code, test, or dependency file was changed to resolve this.
- **Coverage evidence:** atomic refresh and token-pair preservation (`test_block9_task5_refresh_token.py::test_valid_access_but_invalid_refresh_is_atomic`, `test_http_error_keeps_both_tokens`); per-account state (`test_block9_task5_token_sync.py::test_replace_token_is_per_account`, `test_service_refresh_a_does_not_affect_b`); concurrent bounded 401 recovery (`test_block9_task5_401_handling.py::test_concurrent_same_account_single_refresh`, `test_overlapping_401_causes_exactly_one_refresh_deterministic`); NATS and queue-position retry contracts (`test_block9_task5_401_nats_transport.py::test_connection_info_401_triggers_handler_and_retries_once`, `test_block9_task5_401_queue_position.py::test_401_triggers_handler_and_retries_once_with_new_token`); POST no-replay (`test_block9_task5_401_handling.py::test_post_order_401_is_not_retried_and_does_not_refresh`); secret-leak and fake/offline transport guards across the respective test files.
- **Safety:** the audit used fake broker transports and credentials; no real broker login or order was performed. A live `POST /order` must never be replayed automatically after 401.
- **Architect disposition:** Task 5 is **COMPLETE within its documented scope**. This does not certify Task 9 account-aware production routing, active-account/usable-session order authorization, account-specific feedback, or enable live trading. Those remain separate work.

**Execution control:** Stages 1, 2A, 2B, 2C.1, 2C.2, 2C.3a, 2C.3b and Stage 3 are complete/reviewed within scope. The next planned work is Block 9 Task 9 — account-aware production routing. Preserve `DispatchCore → OrderEngine → M6`, the live-trading safety lock, and the broker-independent authentication boundary.

#### Block Boundaries

This block must NOT without separate decision:
- Redesign Core Dispatch
- Change M6-A through M6-E
- Change SafetyGate
- Enable Live Trading
- Implement Central Server/Admin Panel/License

---

## 20. Critical Rule for Future Agents

\*\*Do not modify the architecture, broker API implementation, authentication mechanism, or real-order behavior based on assumptions.\*\*



Inspect the existing implementation first.



If an API behavior is unknown, mark it as unknown and investigate it.



Never invent an endpoint, request field, authentication mechanism, broker identifier, or trading rule.


## Latest checkpoint — Block 9 Phase 3 Task 3B-4 COMPLETE (2026-10-16)

Commit pushed: `9cb1f95` (`feat: complete per-account login and status UI`). Only `ui/accounts_page.py`, `ui/strings.py` and `test_ui2_1_account_management.py` were committed. After the last generic-message wording adjustment, account-management tests passed **45/45**. Earlier regression runs reported UI foundation + account management **58 passed**, composition/authentication/Agah adapter/integration **149 passed**, and compilation success; the combined suites were run before the final text-only adjustment. No real vault, broker network/login, CAPTCHA request or order was used.

**Next:** Block 9 Phase 3 Task 3B-5 — integrated offline UX acceptance. Test the full MainWindow/AccountsPage → fake credential backend → real AuthenticationService → real account-owned Agah adapter/broker flow with a fake HTTP transport, prove two same-broker accounts remain isolated, and test UI logout/status. The task is test-only and may add only `test_block9_phase3_accounts_ui_integration.py`; no production edits, staging, commits or pushes. See `AI_HANDOFF.md` for exact acceptance criteria.
## Latest checkpoint — Block 9 Phase 3 Task 3B-5 COMPLETE (2026-10-16)

Commit 19d9558 (test: verify integrated account UI offline) adds only test_block9_phase3_accounts_ui_integration.py. Owner-reported results: integrated UI/lazy construction 2 passed in 1.37s; UI foundation + account-management 58 passed in 4.36s; composition/authentication/Agah-adapter/integration 149 passed in 3.11s; py_compile passed. Both tests guard requests.sessions.Session.request against real HTTP; credentials and per-account HTTP transports are fake.

## Latest checkpoint — Block 9 Task 5 Stage 3 COMPLETE (2026-10-16)

**Architect disposition:** Task 5 is complete within its documented scope. Actual offline regression results: Task 5 refresh/token/401 suite **175 passed in 2.28s**; session/authentication/broker/dispatch suite **267 passed in 4.62s**; Accounts-page integration suite **60 passed in 5.65s**. The first suite includes and successfully runs both NATS and queue-position tests.

The NATS dependency `nats-py==2.16.0` was installed only in the temporary venv at `/tmp/block9-stage3-venv-final`; no project code, test, or dependency file was changed to resolve the environment issue. Tests used fake/offline transports and did not perform real broker login or order placement.

**Next:** Block 9 Task 9 — account-aware production routing. Task 5 closeout does not prove account-correct trading-state/instrument-identity/feedback paths or the active-account + logged-in + usable-session order gate; live trading remains disabled.

## Latest checkpoint — Block 9 Task 9A COMPLETE; account/session order gate NEXT (2026-10-16)

**Commits pushed to `master`:**
- `4aef682` — Task 9A offline acceptance tests in `test_block9_task9_account_bound_read_paths.py`.
- `1123cd9` — account-bound read-path implementation in `ui/main_window.py`, `ui/order_configuration_page.py`, and `ui/trading_state_worker.py`.

**Task 9A accepted scope:** the trading-state query and instrument `nscId` resolver use the shared `MainWindow` `BrokerManager` and the exact account runtime keyed by `(account_id, broker_name)`. Async read results are bound to `(account_id, broker_name, ins_code)`; results from an old account are rejected after a switch, and missing/invalid account context fails closed without a name-only fallback. `DispatchCore → OrderEngine → M6-A…M6-E` was not changed. Tests used offline fakes; no real network, broker login or order was performed.

**Verification:**
- `python3 -m pytest -q test_block9_task9_account_bound_read_paths.py` → **6 passed** (latest recorded run: 1.37s).
- `python3 -m py_compile ui/main_window.py ui/order_configuration_page.py ui/trading_state_worker.py test_block9_task9_account_bound_read_paths.py` → passed.
- Requested broader regression → **9 failed, 155 passed**. Eight failures are in `test_ui3_2b_trading_state_display.py`: fixtures have no active account but still expect a query/result, which conflicts with the new fail-closed contract. One failure, `test_ui3_1_order_configuration.py::test_14_ui_does_not_use_legacy_main`, rejects the `brokers.authentication` import in `ui/accounts_page.py`, outside Task 9A. Do not weaken fail-closed behavior to make no-account fixtures pass.
- The staged Task 9A code diff passed `git diff --cached --check` before commit. A prior whole-worktree check showed CRLF/trailing-whitespace output in a file with older local edits, so that broad output could not be attributed entirely to Task 9A.
- Unrelated local `ui/test_runner.py` edits and untracked artifacts were excluded from these commits and must be preserved.

**Architect disposition:** Task 9A is **COMPLETE within its approved scope**. This does not mean the broad regression is green or that order authorization is implemented.

**Next:** define a separate task for the active-account + logged-in + usable-session order-authorization gate. Account-aware `MainWindow._real_feedback_broker_factory()`/feedback lifecycle remains separate. Keep live trading disabled, preserve `DispatchCore → OrderEngine → M6-A…M6-E`, and never automatically replay `POST /order` after HTTP 401.

## Latest checkpoint — Block 9 SQLite Account Metadata Persistence COMPLETE (2026-10-17)

**Implementation commit pushed:** `fa3e6ad` — `feat(ui): persist account metadata in SQLite`.

**Changed code/test files:** `ui/account_repository.py` (new), `ui/account_store.py`, `ui/main_window.py`, `test_account_repository.py` (new), `test_ui2_1_account_persistence.py` (new), `test_ui1_application_foundation.py`, and `test_ui2_1_account_management.py`.

**Behavior:** production `MainWindow()` uses `AccountStore.persistent_default()`. On Windows the default SQLite path is `%LOCALAPPDATA%\Trading Bot\accounts.db`; non-Windows fallback is `XDG_DATA_HOME/Trading Bot/accounts.db`, then `~/.local/share/Trading Bot/accounts.db`. Only `account_id`, `broker_name`, `display_name`, and `position` are stored. Credentials remain in the OS-backed `CredentialStore`. Active selection, login state, sessions and access/refresh tokens are not persisted or restored. Tests can inject a temporary database path or `repository=False` for in-memory behavior.

**Verification (owner-run Windows environment):** `py -3 -m pytest -q test_account_repository.py test_ui2_1_account_persistence.py test_ui2_1_account_management.py test_ui1_application_foundation.py` → **67 passed in 4.06s** using a temporary `LOCALAPPDATA`/`XDG_DATA_HOME`. The real user database was not touched. This records the focused suites only; the broader Task 9A regression remains **9 failed, 155 passed** as stated above.

**Architectural boundary:** this work changes local account-metadata persistence only. It does not redesign `AccountsPage`, change authentication/session/token persistence, or modify order dispatch/live-trading policy. See Decision 032 in `DECISIONS.md`.

**Follow-up at this checkpoint (superseded):** the Accounts-page mockup and redesign were subsequently approved and completed in code commit `f8d564f` (see the latest checkpoint appended below). The active-account + logged-in + usable-session order gate and account-aware feedback remain distinct pending work. Live trading remains disabled.


## Latest checkpoint — Accounts-page redesign COMPLETE (2026-10-17)

**Code commit pushed:** `f8d564f54b32eece0b776d9696bf7b454adb0043` — `feat(ui): redesign accounts page and captcha dialog`.

**Changed files:** `ui/accounts_page.py`, `ui/strings.py`, `test_ui2_1_account_management.py`, and `test_block9_phase3_accounts_ui_integration.py`.

**Behavior recorded:** the page now uses the approved RTL account-management design, generates the internal account ID, brings display name/broker/credentials into the add form, separates active-account state from login state, and exposes account-row actions. CAPTCHA appears only for a valid image challenge in a modal RTL `QDialog`; invalid challenge payloads/images trigger a best-effort `cancel_login(account_id)` and sanitized error reporting. Existing SQLite metadata persistence and OS-vault credential boundaries are unchanged.

**Focused offline verification reported:**
- `QT_QPA_PLATFORM=offscreen pytest -q test_ui2_1_account_management.py` → **49 passed**.
- `QT_QPA_PLATFORM=offscreen pytest -q test_block9_phase3_accounts_ui_integration.py` → **2 passed**.
- `QT_QPA_PLATFORM=offscreen pytest -q test_block9_phase2_service_composition.py` → **4 passed**.
- `py_compile` and `git diff --check` reported successful; Git emitted LF/CRLF normalization warnings but no whitespace-check error.

These 55 passing tests are the focused account-UI suites, not a full-repository regression result. The separately recorded Task 9A broader regression remains **9 failed, 155 passed** and must not be represented as fixed by this UI task.

**Scope boundary:** no SQLite implementation, `MainWindow`, authentication/session services, order routing, or live-trading policy was changed in this commit. No commit or push was performed for application code beyond `f8d564f`; the local `.graphify/` artifact was excluded.

**Status at this historical checkpoint (superseded 2026-10-17):** the order-authorization gate was next at the time; it is now complete in code commit `503f6f6`. Account-aware order feedback remains a separate next task. Live trading stays disabled; never automatically replay `POST /order` after HTTP 401.


## Latest checkpoint — Block 9 Order Authorization Gate COMPLETE (2026-10-17)

**Implementation commit pushed:** `503f6f6` — `feat(auth): enforce order authorization gate`.

**Changed files (11):** `ui/order_authorization.py`, `ui/main_window.py`, `ui/order_configuration_page.py`, `ui/strings.py`, `test_block9_order_authorization_gate.py`, `test_ui4_queue_ui_integration.py`, `test_ui5_task2_dry_run_execution.py`, `test_ui5_task3_order_results.py`, `test_ui5_task4_user_logs.py`, `test_ui5_task4_stage3_task3_core_registration.py`, and `test_ui6_task1_diagnostic_mode.py`.

**Behavior:** order authorization fails closed before queue insertion and before the Test/run path proceeds. It verifies the active account and account/broker identity; AuthenticationService login state; SessionManager `LOGGED_IN` state and non-empty local token; an existing authenticated adapter; matching adapter broker identity; and exact equality between the adapter's authenticated-session token and SessionManager token. Missing services, invalid state, inconsistent identity/token, or API exceptions return a controlled denial. Authorization does not initiate login, network access, token refresh, or session mutation. The UI composes this check lazily. The existing `DispatchCore → OrderEngine → M6-A…M6-E` path remains authoritative; Test remains dry-run (`live=False`); no real broker order was sent.

**Verification reported for this checkpoint:**
- `python3 -m pytest -q test_block9_order_authorization_gate.py` → **4 passed**.
- `QT_QPA_PLATFORM=offscreen python3 -m pytest -q test_ui6_task1_diagnostic_mode.py` → **28 passed**.
- Focused gate + UI-4/UI-5/UI-6 suite → **107 passed, 26 failed**. The 26 remaining failures reproduce on the baseline and are the `BrokerManager._account_lock` AttributeError reached when `core/simulation_harness.py` allocates `BrokerManager` via `__new__` without running `__init__`; this out-of-scope issue was not changed.
- Full repository run after the UI-6 fixture adjustment → **1595 passed, 233 failed, 20 skipped, 4 errors**. This is not a green full-suite result; existing failures/errors include the missing `nats` dependency and platform-specific `ctypes.WinDLL` collection failure. The earlier run before the fixture adjustment recorded **1590 passed, 233 failed, 20 skipped, 4 errors**.
- Relevant `py_compile` succeeded. The staged task diff passed `git -c core.whitespace=cr-at-eol diff --cached --check`; the agent environment's broad whole-worktree check still reports pre-existing line-ending noise across unrelated files.

**Architect disposition:** the order authorization gate is complete within the approved scope. This does not mean the full repository test suite is green or that account-aware order feedback is complete.

**Next bounded task:** account-aware order-feedback broker/listener lifecycle, separately scoped. Preserve per-account runtime ownership, existing dispatch/M6 gates and fail-closed behavior; keep live trading disabled and never automatically replay `POST /order` after HTTP 401.

---

# Latest Checkpoint — Block 9 Task 9B: Account-Aware Order Feedback (2026-10-18)

**Implementation commit on `master`:** `9ad15d435c2dc12eb3d95ba3f3ead071f6884e80` — `fix: scope order feedback to account runtime`.

Task 9B implementation covers account-keyed feedback runtime ownership `(account_id, broker_name)`; account-scoped broker resolution through `BrokerManager.get_for_account(...)`; lazy composition and fail-closed session/authorization checks; idempotent listener registration; restart-safe stop/start; account-specific handling of `AcceptedByBourse`, queue-position and order-error events; and lifecycle isolation for logout, account deletion, and broker changes. Active-account switching must not stop other accounts. Identical decision IDs in different accounts must not cross-update rows. Starting feedback is not an order-send action.

**Changed scope:** `ui/main_window.py`, `ui/order_feedback_service.py`, `ui/order_configuration_page.py`, `ui/accounts_page.py`, `test_block9_account_aware_order_feedback.py`, and adjacent UI regression tests.

**Scoped acceptance: COMPLETE.** After architectural review, the fresh focused test command
```powershell
python -m pytest -q test_block9_account_aware_order_feedback.py test_ui5_task4_stage3_task3_core_registration.py test_ui5_task4_stage3_task4_ui_table.py
```
reported **56 passed in 6.09s, exit 0**. No further Task 9B code change is requested at this point.

**Owner-run manual local-app acceptance (2026-10-18):** two accounts on the same broker both logged in; activating either selected that account for current use while the other remained inactive; logging out one account did not disturb the other; logging the exited account back in succeeded and the other account remained normal. No issue was observed. This check covered account login/logout/re-login only; no order was submitted and live trading remains disabled.

**Broader regression boundary:** the whole project is not being declared green. A prior broader run was reported by the coding agent as **57 passed, 9 failed**, with the nine failures attributed to missing `nats`; `py_compile` was reported successful, and one UI-7 failure was reported as baseline. These are prior reported observations, not independently reproduced by the current focused run. Next is broader regression and final acceptance of the local User Application. Distinguish baseline/environment failures from new regressions; do not reopen Task 9B without a reproducible in-scope defect.

Preserve the fail-closed order-authorization gate, `DispatchCore → OrderEngine → M6-A…M6-E`, dry-run `live=False`, and disabled live trading. Feedback must never place or automatically replay an order. Central Server remains out of scope until local-app acceptance is complete.
