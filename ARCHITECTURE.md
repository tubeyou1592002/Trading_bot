\# Trading Bot — Architecture



\## 1. Purpose



This document defines the architectural structure and boundaries of the Trading Bot project.



The primary architectural goal is to keep:



\* User interface

\* Business logic

\* Market data

\* Broker integrations

\* Domain models

\* External APIs



separated from each other.



The system must remain modular so additional brokers can be added without rewriting the core trading logic.



\---



\## 2. High-Level Architecture



```text

User

\&#x20; │

\&#x20; ▼

UI / Application Layer

\&#x20; │

\&#x20; ▼

Core Trading / Order Engine

\&#x20; │

\&#x20; ▼

Broker Interface

\&#x20; │

\&#x20; ├───────────────┬────────────────┐

\&#x20; ▼               ▼                ▼

Agah Adapter   Broker B Adapter   Broker C Adapter

\&#x20; │               │                │

\&#x20; ▼               ▼                ▼

Agah API       Broker B API       Broker C API

```



Market-data flow:



```text

User

\&#x20; │

\&#x20; ▼

Symbol Resolver

\&#x20; │

\&#x20; ▼

TSETMC

\&#x20; │

\&#x20; ▼

Instrument

\&#x20; │

\&#x20; ▼

Broker-specific Instrument Mapping

```



\---



\## 3. Current Repository Structure



```text

Trading\\\_bot/

│

├── main.py

│

├── brokers/

│   ├── \\\_\\\_init\\\_\\\_.py

│   ├── base.py

│   ├── agaah.py

│   ├── device\\\_info.py

│   └── manager.py

│

├── core/

│   └── order\\\_engine.py

│

├── input/

│   ├── \\\_\\\_init\\\_\\\_.py

│   └── keyboard\\\_layout.py

│

├── market/

│   ├── \\\_\\\_init\\\_\\\_.py

│   ├── tsetmc.py

│   └── symbol\\\_resolver.py

│

├── models/

│   ├── \\\_\\\_init\\\_\\\_.py

│   ├── account.py

│   ├── broker\\\_instrument.py

│   ├── instrument.py

│   ├── order.py

│   └── order\\\_validator.py

│

└── test\\\_\\\*.py

```



This represents the current implementation and may evolve as the project develops.



\---



\## 4. Architectural Layers



\### 4.1 UI / Application Layer



`main.py` currently contains the main application/UI entry point.



Responsibilities should include:



\* User interaction.

\* Displaying information.

\* Receiving user input.

\* Calling application services.

\* Displaying results and errors.



The UI should not directly implement broker-specific HTTP requests.



\---



\### 4.2 Core Layer



Current location:



```text

core/

```



The core layer contains broker-independent trading logic.



Current major component:



```text

core/order\\\_engine.py

```



Responsibilities include concepts such as:



\* order workflow

\* execution orchestration

\* coordinating broker calls

\* handling execution results

\* resolving instrument identity through an abstract `InstrumentProvider`



The core layer provides two entry points for order execution:



\* `OrderEngine.execute(...)` — accepts a fully resolved `BrokerInstrument` and an `Order`; performs validation, trading-state check, and dry-run/live dispatch.

\* `OrderEngine.execute_by_ins_code(...)` — accepts a TSETMC `ins_code` plus an `InstrumentProvider`; calls `provider.get_instrument(ins_code)` to resolve the `BrokerInstrument` and then delegates to `execute(...)`. The orchestration belongs to the core layer, not to a broker adapter, so the core stays broker-independent (Decision 003).



Pipeline of `execute_by_ins_code`:



```text

ins_code

    → InstrumentProvider.get_instrument(ins_code)

    → (Instrument, BrokerInstrument)

    → nsc_id consistency check (no overwrite)

    → OrderEngine.execute(...)  (existing)

    → Broker.place\_order(...)

```



If the provider raises `InstrumentLookupError`, the engine returns `OrderExecutionResult` with `mode="BLOCKED"` and a message of the form `Instrument lookup failed: {detail}`. If `order.nsc_id` does not match the provider-resolved `nsc_id`, the engine returns `mode="BLOCKED"` without silently overwriting `order.nsc_id`.



\---



\### 4.3 Broker Layer



Current location:



```text

brokers/

```



The broker layer isolates external broker APIs.



Current components include:



```text

brokers/base.py

brokers/agaah.py

brokers/manager.py

brokers/device\\\_info.py

```



The broker layer is responsible for:



\* authentication

\* account information

\* broker instrument information

\* order submission

\* broker-specific request construction

\* broker-specific response parsing

\* broker-specific error handling



\---



\## 5. Broker Abstraction



The preferred conceptual interface is:



```text

Broker

\&#x20;├── authenticate()

\&#x20;├── get\\\_accounts()

\&#x20;├── get\\\_balance()

\&#x20;├── get\\\_instrument()

\&#x20;├── submit\\\_order()

\&#x20;├── get\\\_order\\\_status()

\&#x20;└── ...

```



Exact method names may differ from this conceptual representation.



In addition to `Broker`, the project defines a separate abstraction, `InstrumentProvider`, for resolving the broker-side identifier of an instrument from a TSETMC `ins_code`:



```text

InstrumentProvider

&#x20;├── get_instrument(ins_code)   -> (Instrument, BrokerInstrument)

&#x20;├── get_nsc_id(ins_code)        -> Optional[str]

&#x20;└── refresh_cache()

```

`InstrumentProvider` lives next to `Broker` in `brokers/base.py`. The contract failure type is `InstrumentLookupError`, defined in the same module (Decision 019). Concrete providers (e.g. `AgaahInstrumentProvider`) raise this exception on lookup failure; the core engine catches it by name and never imports it from a concrete provider.

`OrderEngine.execute_by_ins_code(...)` depends on `InstrumentProvider` as an abstract type, not on any concrete implementation. This is what allows the core engine to remain broker-independent (Decision 003) while still being able to resolve an `ins_code` to a broker-specific `nsc_id` before submitting an order.



The important rule is that the core engine should depend on the abstraction rather than a specific broker.



\---



\## 6. Adding a New Broker



A new broker should normally follow this model:



```text

brokers/

├── base.py

├── manager.py

├── agaah/

│   ├── broker.py

│   ├── auth.py

│   ├── account.py

│   ├── instruments.py

│   └── orders.py

│

└── broker\\\_b/

\&#x20;   ├── broker.py

\&#x20;   ├── auth.py

\&#x20;   ├── account.py

\&#x20;   ├── instruments.py

\&#x20;   └── orders.py

```



However, the existing project structure should not be reorganized merely for theoretical cleanliness.



Refactoring should happen only when it provides a concrete benefit.



\---



\## 7. Broker-Specific Isolation



Broker-specific details must remain inside the broker adapter.



Examples:



\* API URLs

\* HTTP headers

\* authentication tokens

\* request payload formats

\* response formats

\* broker instrument identifiers

\* broker-specific error codes

\* broker-specific order rules



The core engine should not know these implementation details.



\---



\## 8. Market Data Layer



Current location:



```text

market/

```



Important components:



```text

market/tsetmc.py

market/symbol\\\_resolver.py

```



Responsibilities:



\* communicating with TSETMC

\* searching instruments

\* normalizing symbols

\* resolving user input

\* representing market instruments



TSETMC identifiers must not automatically be assumed to be identical to broker identifiers.



Mapping between systems must be explicit.



\---



\## 9. Domain Models



Current location:



```text

models/

```



Models currently include:



```text

Account

BrokerInstrument

Instrument

Order

OrderValidator

```



Domain models should represent trading concepts independently of any specific broker API whenever practical.



For example:



```text

Order

\&#x20;├── symbol/instrument

\&#x20;├── side

\&#x20;├── quantity

\&#x20;├── price

\&#x20;├── validity

\&#x20;└── execution information

```



Broker-specific fields should only be added when there is a justified domain-level need.



\---



\## 10. External API Boundary



External services include:



```text

TSETMC

Agah API

Future broker APIs

```



External API calls should be isolated behind appropriate modules/adapters.



Raw HTTP implementation must not spread throughout the application.



Preferred:



```text

Core

\&#x20; ↓

Broker Adapter

\&#x20; ↓

HTTP/API

```



Avoid:



```text

Core

\&#x20; ↓

requests.post("broker-specific-url")

```



\---



\## 11. Instrument Identity



The system may encounter multiple identifiers for the same financial instrument.



Examples:



```text

TSETMC insCode

ISIN

Broker-specific instrument ID / nscId

```



These identifiers must not be confused.



The system should explicitly represent mappings between identifiers where required.



Current known example:



```text

TSETMC symbol: آكو

ISIN: IRO1ACCO0001

TSETMC insCode: 60235881999727383

```



The corresponding Agah identifier must be resolved through verified mapping logic.



\---



\## 12. Order Execution Architecture



Conceptual flow for the `ins_code`-driven path (Milestone 2):



```text

ins_code

&#x20;      │

&#x20;      ▼

InstrumentProvider.get_instrument(ins_code)

&#x20;      │

&#x20;      ▼

(Instrument, BrokerInstrument)

&#x20;      │

&#x20;      ▼

OrderEngine.execute_by_ins_code(...)

&#x20;      │ (delegates internally)

&#x20;      ▼

OrderEngine.execute(...)

&#x20;      │

&#x20;      ▼

Broker.place_order(order, live=live)

```



Conceptual flow (legacy / fully-resolved path):



```text

User Order Request

\&#x20;      │

\&#x20;      ▼

Order Validation

\&#x20;      │

\&#x20;      ▼

Order Engine

\&#x20;      │

\&#x20;      ▼

Broker Manager

\&#x20;      │

\&#x20;      ▼

Selected Broker Adapter

\&#x20;      │

\&#x20;      ▼

Broker API

\&#x20;      │

\&#x20;      ▼

Order Result

\&#x20;      │

\&#x20;      ▼

Order Engine

\&#x20;      │

\&#x20;      ▼

UI / User

```



The order engine must not directly construct broker-specific HTTP payloads.



\---



\## 13. Multi-Account Execution



The long-term system may execute one logical trading instruction across multiple broker accounts.



Conceptually:



```text

Logical Order

\&#x20;     │

\&#x20;     ▼

Execution Planner

\&#x20;     │

\&#x20;     ├── Account A → Broker A

\&#x20;     ├── Account B → Broker B

\&#x20;     └── Account C → Broker C

```



The exact implementation should be designed only after account management and broker abstractions are sufficiently stable.



\---



\## 14. Timing Architecture



Precise execution timing is a core project requirement.



The eventual design may contain:



```text

Time Synchronization

\&#x20;       ↓

Scheduler

\&#x20;       ↓

Execution Planner

\&#x20;       ↓

Order Engine

\&#x20;       ↓

Broker Adapters

```



Requirements include:



\* precise start time

\* precise end time

\* configurable interval

\* countdown

\* server-time synchronization

\* batch execution



Timing logic should remain independent from individual broker API implementations.



\---



\## 15. Halted / Non-Tradable Instruments



The system may need to wait for an instrument to become tradable.



Conceptually:



```text

Order requested

\&#x20;     ↓

Is instrument tradable?

\&#x20;     │

\&#x20;┌────┴─────┐

Yes         No

\&#x20;│           │

\&#x20;▼           ▼

Send       Wait/Monitor

\&#x20;             │

\&#x20;             ▼

\&#x20;      Tradable?

\&#x20;             │

\&#x20;             ▼

\&#x20;            Send

```



The exact definition of "tradable" must be based on verified market/broker behavior.



Do not assume a single status value from one API is sufficient without testing.



\---



\## 16. Testing Architecture



Testing should exist at multiple levels.



\### Unit tests



Test:



\* models

\* normalization

\* validation

\* order construction

\* mapping logic



\### Integration tests



Test:



\* TSETMC communication

\* broker authentication

\* broker instrument lookup

\* broker balance retrieval

\* broker order request construction



\### Dry-run tests



Dry-run mode must allow execution logic to be tested without submitting a real order.



\### Production testing



Real order submission must never be used as a casual debugging mechanism.



\---



\## 17. Security Boundary



Credentials and secrets must never be part of source code.



Sensitive data includes:



\* passwords

\* access tokens

\* refresh tokens

\* cookies

\* captcha data

\* private API keys

\* authentication headers



Use secure configuration mechanisms.



Never commit secrets to Git or GitHub.



\---



\## 18. Error Handling



Errors should be handled at the appropriate layer.



Conceptually:



```text

Broker API Error

\&#x20;     ↓

Broker Adapter

\&#x20;     ↓

Normalized Broker Error

\&#x20;     ↓

Core / Application

\&#x20;     ↓

UI

```



Raw broker-specific errors should not leak unnecessarily into unrelated parts of the application.



Errors must not be silently swallowed merely to make the application appear successful.



\---



\## 19. Logging



The eventual system should provide useful logging for:



\* authentication

\* instrument resolution

\* order preparation

\* order submission

\* broker responses

\* timing

\* errors

\* dry-run operations



Logs must never expose secrets.



\---



\## 20. Architectural Change Rule



An AI coding agent must not perform major architectural changes without justification.



Before restructuring:



1\. Inspect the current code.

2\. Explain the problem.

3\. Identify the proposed change.

4\. Identify affected components.

5\. Run relevant tests.

6\. Document the decision when appropriate.



Working code should not be rewritten solely for stylistic reasons.



\---



\## 21. Source of Truth



The architecture is defined by:



```text

Git repository

\\+

ARCHITECTURE.md

\\+

PROJECT\\\_CONTEXT.md

\\+

AI\\\_PROJECT\\\_MEMORY.md

\\+

DECISIONS.md

```



Chat conversations provide context, but the repository must remain independently understandable.



\---



\## 22. Development Principle



Preferred development cycle:



```text

Inspect

\&#x20;  ↓

Understand

\&#x20;  ↓

Plan

\&#x20;  ↓

Implement minimally

\&#x20;  ↓

Test

\&#x20;  ↓

Review

\&#x20;  ↓

Commit

```



Every meaningful change should leave the repository in a known, testable state.

