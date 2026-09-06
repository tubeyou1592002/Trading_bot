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

`ca3e2cbf — M5: TSETMC trading state integration`



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

### M6 — Order Preflight & Constraints (DEFINED)

M6 Discovery: **COMPLETE**
M6 Architectural Scope: **DEFINED**
M6 Implementation: **NOT STARTED**

#### Goal
Before an order is prepared for submission, all necessary conditions for order validity must be available and verifiable from the correct sources: market trading state, instrument, account, asset, and order constraints.

Core principle (Fail Closed):
- **Valid + Known → continue**
- **Invalid → BLOCK**
- **Unknown / Missing / Error → BLOCK**

#### 1. Common BUY and SELL Conditions (before order submission)

##### Instrument / Identity
- Instrument must be valid.
- Instrument identifiers must be correct.
- Trading state must relate to the same Instrument.
- If Identity cannot be verified → **BLOCK**

##### Account / Broker
- Required account and session information must be valid and usable.
- If access is denied or required information is invalid/missing → **BLOCK**

##### Market Trading State
- Source: TSETMC
- Field: `cEtaval` (mapping per Decision 020)
- Current order submission policy:
  - `"A "` and `"AR"` → **ALLOWED**
  - All other states → **BLOCK**
  - Unknown / Missing / Error / Invalid → **BLOCK**

##### Price
- Must be within `lowerPriceThreshold` and `upperPriceThreshold`.
- Must be compatible with `fixedPriceTick`.
- If not → **BLOCK**

##### Quantity
- Must be greater than zero.
- Must respect `minimumOrderQuantity`.
- Must respect `baseQuantity` / `lotSize`.
- If not → **BLOCK**

#### 2. BUY-specific Conditions
- `quantity <= maximumOrderQuantityForBuy`
- Sufficient tradable cash balance must exist.
- Actual buy capacity must be supported by Agah's calculated quantity.
- Source of balance: `GET /api/v1/financialaccounts/balances`
- Main field: `tradableBalanceT1`
- Source of buy capacity: `GET /api/v1/trades/calculatedquantity`
- Observed parameters: `nscId`, `sideCode`, `fund`, `price`
- **Important architectural decision:** Commission and buy costs are NOT to be hard-coded in the bot. Use Agah's own `calculatedquantity` to determine real buy capacity so that Agah's current rules and possible user discounts are applied by the broker itself.
- Decision: **Requested Quantity <= Agah Calculated Quantity**
- If Agah calculated quantity is unknown or errors → **BLOCK**

#### 3. SELL-specific Conditions
- `quantity <= maximumOrderQuantityForSell`
- User must hold the asset for the given Instrument.
- Currently `portfolio.numberOfShares` is the basis for sell quantity control.
- Source: `GET /api/v1/portfolio`
- Main field: `numberOfShares`
- Current decision: In this milestone, **Requested Quantity <= numberOfShares** → allow; **Requested Quantity > numberOfShares** → **BLOCK**
- Note: At this stage, `numberOfShares` is not claimed to be an independent "sellable quantity" field; it is the current project's sell-quantity control basis.

#### 4. Instrument Constraints (discovered Agah API fields)
The following fields were discovered from the Agah API and must be used for order validation. If already implemented in the Repository, they must NOT be redefined or redesigned.

- `upperPriceThreshold`
- `lowerPriceThreshold`
- `fixedPriceTick`
- `minimumOrderQuantity`
- `maximumOrderQuantityForBuy`
- `maximumOrderQuantityForSell`
- `baseQuantity`
- `lotSize`

#### 5. Order Splitting — PLANNED (not implemented)
This is recorded as part of the M6 plan but **not yet implemented**.

Agah reports via `GET /api/v1/app/config`:
- `canBeDivideBuyOrder = true`
- `canBeDivideSellOrder = true`

Planned behavior (for the future):
- If requested quantity exceeds the maximum allowed per order, it should be split into the minimum number of valid lots.
- Example 1: Maximum = 2000, Requested = 3000 → 2000 + 1000
- Example 2: Maximum = 2000, Requested = 5300 → 2000 + 2000 + 1300
- Each slice must ultimately comply with order rules.

**Not yet implemented:**
- Delay between slices
- Scheduler
- Retry
- Result management per slice
- Cancel/Modify between slices
- Full multi-order orchestration

#### 6. M6 Scope (official record)
M6 — Order Preflight & Constraints
1. Market Trading State
2. Instrument Constraints
3. Account Cash Availability
4. Buy Capacity via Agah
5. Portfolio Quantity for Sell
6. Unified BUY/SELL Preflight
7. Planned Order Splitting

#### 7. Out-of-Scope for M6
The following are explicitly **not** part of M6:
- Scheduler
- Precise Timing
- Multi-account
- Full session lifecycle
- Live Trading
- Retry / Recovery
- Advanced Open Order Management
- Independent "sellable quantity" separate from `numberOfShares`
- Manual commission calculation
- General architecture refactor

#### 8. Relation to M5
- M5 established TSETMC as the source of Market Trading State with verified `cEtaval` mapping and identity verification.
- M6 consumes M5's TradingState as one input among several preflight checks.
- M6 does **not** alter M5's trading-state logic.
- M6 adds the remaining preflight layers (price, quantity, account, buy capacity, sell quantity) around the M5 trading-state gate.



\---



## 20. Critical Rule for Future Agents

\*\*Do not modify the architecture, broker API implementation, authentication mechanism, or real-order behavior based on assumptions.\*\*



Inspect the existing implementation first.



If an API behavior is unknown, mark it as unknown and investigate it.



Never invent an endpoint, request field, authentication mechanism, broker identifier, or trading rule.



