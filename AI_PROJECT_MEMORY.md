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

`f600a6c — Initial project baseline`



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



\## 20. Critical Rule for Future Agents



\*\*Do not modify the architecture, broker API implementation, authentication mechanism, or real-order behavior based on assumptions.\*\*



Inspect the existing implementation first.



If an API behavior is unknown, mark it as unknown and investigate it.



Never invent an endpoint, request field, authentication mechanism, broker identifier, or trading rule.



