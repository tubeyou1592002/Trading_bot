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

#### 4.1.1 Order Workflow Integration (M4-B)

`main.py` (`SymbolSearchWindow`) integrates the existing broker/provider/engine abstractions via a dry-run-only order workflow:

```text
on_broker_changed(broker_name)
    ├── current_broker = BrokerManager.get(broker_name)
    └── current_provider = BrokerManager.get_instrument_provider(broker_name)

select_symbol(item)
    └── selected_instrument = Instrument (stored for order use)

send_order()
    ├── resolve nsc_id via current_provider.get_nsc_id(ins_code)
    ├── build Order from UI inputs (side, price, quantity)
    ├── obtain Account via current_broker.get_account()
    └── OrderEngine.execute_by_ins_code(broker, provider, ins_code, order, account, live=False)
```

Properties of the integration:

\* `send_order()` is pure orchestration — no business logic is duplicated in the UI layer.
\* `live=False` is hard-coded; no live order path is reachable.
\* `Account` is obtained from `broker.get_account()` (real Broker API) — no placeholder.
\* `main.py` does not bypass any abstraction layer: the flow goes through `BrokerManager` → `InstrumentProvider` → `OrderEngine` → `Broker`.
\* `core/`, `brokers/base.py`, `brokers/agaah/`, `models/`, `market/`, `input/` are unchanged.
\* For the real `AgaahBroker`, orders are blocked at `prepare()` because `get_trading_state` returns `UNVERIFIED` (Decision 017). Per M6-A, `OrderEngine.prepare()` now enforces fail-closed behavior: `UNVERIFIED` (Unknown / Missing / Error / Unverified) is interpreted as `BLOCKED`. This is the expected safety behavior.



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



### 4.3.1 BrokerManager wiring (M4-A)

M4-A adds a single method, `BrokerManager.get_instrument_provider(name)`, that returns a per-broker cached `InstrumentProvider`. The wiring is intentionally minimal: no factory map, no plugin registry, no generic broker/provider abstraction layer.

```text

BrokerManager

├── brokers["آگاه"]

│      └── AgaahBroker

│

└── providers["آگاه"]

       └── AgaahInstrumentProvider

              └── same AgaahBroker instance (from self.brokers["آگاه"])

```

Properties of the wiring:

\* The provider is created **lazily** on the first call to `get_instrument_provider(name)`. It is not constructed in `__init__`.

\* The provider is **per-broker cached** in `self.providers[name]`. A second call for the same name returns the exact same instance.

\* The provider wraps the **same broker instance** stored in `self.brokers[name]`. The manager does not construct a fresh `AgaahBroker()` for the provider. This is required so that the provider's session, auth state, and in-memory cache share the broker's lifecycle.

\* If the broker name is unknown, `get_instrument_provider` raises `ValueError` with the same style as `BrokerManager.get`.

\* `BrokerManager` remains structurally Agah-specific in M4-A, exactly as it was before. The hard-coded `brokers["آگاه"] = AgaahBroker()` is unchanged.

\* No factory map, no plugin architecture, no registry, no DI framework was added.

\* This change is wiring only. It does not modify mapping logic, `InstrumentLookupError`, or `OrderEngine.execute_by_ins_code`.

\* `main.py` is now a consumer of the provider (M4-B): `on_broker_changed` calls `get_instrument_provider` and `send_order` calls `OrderEngine.execute_by_ins_code`.



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



\## 22. Dispatch Engine Architecture

### 22.1 Dispatch Boundary

The Dispatch Engine extends the existing architecture with a new layer between the UI/Application and the existing Order Engine:

```text
Trigger
    │
    ▼
Planner (Block 1)
    │
    ▼
Dispatch Core (Block 2)
    │
    ▼
existing M6-A … M6-E  (OrderEngine.prepare / execute)
    │
    ▼
Broker
```

The Dispatch Core is broker-independent (Decision 003) and does not modify the existing M6-A…M6-E preflight gates.

### 22.2 Block 2 — Dispatch Core / Low-Latency Engine

Block 2 is the shared execution core of the Dispatch Engine. It receives an `ExecutionPlan` from Block 1 and dispatches orders through the existing `OrderEngine` path.

**Core / OrderEngine / Broker Adapter boundaries:**

- **Dispatch Core → OrderEngine:** The Dispatch Core delegates to `OrderEngine.execute()` (or `OrderEngine.execute_by_ins_code()`). It does NOT bypass `OrderEngine.prepare()`. All M6-A…M6-E preflight gates run inside `prepare()` before any order is sent to the Broker.
- **Dispatch Core → Broker Adapter:** The Dispatch Core sends a normalized `BrokerDispatchRequest` envelope. It does NOT construct broker-specific HTTP payloads, headers, or auth tokens. The Broker Adapter translates the envelope into the broker's native API call.
- **Dispatch Core → BrokerManager:** The Dispatch Core resolves broker names to instances through the existing `BrokerManager`. It does NOT create new broker instances or modify broker lifecycle.
- **Dispatch Core → InstrumentProvider:** The Dispatch Core resolves instruments through the existing `InstrumentProvider` abstraction (Decision 019). It does NOT call broker-specific instrument APIs directly.

**Account and Broker binding:**

- Accounts and brokers must be pre-identified for execution before dispatch.
- The Dispatch Core must NOT re-select, re-resolve, filter, or rebalance accounts or brokers during dispatch.
- Each order in the plan is paired with an `account_id` and `broker_name` via `PlannedOrder` (Block 1) during planning.
- Multi-Account lifecycle coordination is out of scope for Block 2 and remains for Block 6.

**BrokerDispatchRequest boundary:**

`BrokerDispatchRequest` is the defined normalized contract envelope between Dispatch Core and Broker. The Dispatch Core must establish the real dispatch path that uses this contract. The actual Broker Adapter consuming `BrokerDispatchRequest` is NOT yet implemented; Block 2 must define how the real path will use this contract. The Dispatch Core never constructs broker-specific payloads.

**M6 preservation:**

Block 2 MUST NOT bypass M6-A through M6-E. Block 2 must use the existing `OrderEngine` execution path. All preflight gates remain intact. The specific method calls (`prepare()`, `execute()`, `execute_by_ins_code()`) that Block 2 uses to enter the `OrderEngine` path are not yet decided and are not recorded here.

**Dry-run:**

`live` in `BrokerDispatchRequest` remains False by default. Block 10 defines the controlled Live boundary; production scheduled Live remains unavailable until the pre-armed lifecycle in Block 11 is implemented and explicitly approved.

### Explicit execution mode and optional OMS feedback (Decision 036)

The Order Configuration page defaults each fresh use to Dry Run. Live is a
separate explicit selection; the UI preflights the existing account/session,
account-scoped broker lock, and SafetyGate prerequisites before showing a
final confirmation. It then freezes the exact queue/account/broker/timing
snapshot, displays planned turns and the maximum possible sends, and checks
that snapshot again after confirmation. A changed snapshot is not dispatched
under the old approval. Active schedule sends continue to use those frozen
targets even if the selected account changes elsewhere in the application.

No UI path writes `live=True`, flips `live_trading_enabled`, or bypasses
`SafetyGate`, OrderEngine, or broker locks. Production Live currently fails
closed because no authoritative M6/broker-readiness provider is wired and the
real broker live lock is hard-off by default. A simulated readiness provider
in tests is not production permission.

NATS/OMS is an optional, receive-only feedback path. Its connection/startup
failure or later disconnect updates feedback availability only; it does not
gate Live, block a send, pause cadence, or cause `POST /order` replay. Initial
HTTP order results remain distinct from delayed feedback, which is correlated
by stable decision ID and account/broker scope. Missing feedback is not an
order success/failure verdict. Stop blocks future turns but does not claim to
cancel requests already started. Each scheduled turn resends the full frozen
queue, so possible total submissions are planned turns multiplied by frozen
queue size.

### Pre-armed scheduled Live lifecycle (Decision 037 / Block 11)

The scheduled-Live requirement is a two-phase lifecycle: `PREPARE/ARM` before the firing window, then `FIRE/OBSERVE` at each scheduled instant. The countdown starts only after the complete queue has passed preparation, readiness checks, and explicit approval. The prepared batch freezes account, broker, payloads, schedule, repetition count, and freshness metadata. Any material mutation, failed prerequisite, stale source, or missed start deadline disarms the batch and sends nothing.

Instrument resolution and M6-A…M6-E remain mandatory, but their network reads run during pre-arm preparation. A prepared order is immutable and account-bound; submission consumes only an unexpired prepared result. At the firing instant the application must not perform database access, instrument resolution, M6/readiness HTTP calls, credential refresh, new worker construction, modal interaction, or wait for HTTP/NATS responses. It uses a prestarted sender and monotonic timing to release the authorized payloads. NATS remains receive-only and optional.

Every due turn currently resends the entire frozen queue. Live arming must disclose the exact maximum count (`planned turns × queue size`) and validate aggregate repeated exposure; if that cannot be proven from the prepared batch and broker contract, the plan remains unarmed. No automatic POST retry is allowed. Measure planned due, scheduler wake/release, POST initiation, HTTP response, and NATS feedback separately; zero avoidable application work is the objective, not a claim of zero Windows/network/broker latency.

Block 11 is in progress. Task 11.1's contract and its destination-readiness and account-bound dispatch implementation stages are complete. Each queued order remains bound to its own account, broker, and locally known session; only accounts represented in the queue must be logged in, and changing the UI active account alone does not change destinations. Local destination-session or queue changes disarm the run. The scheduler does not probe remote session validity or re-fetch the user's displayed purchase-power and market-price-bound values. Mandatory M6/SafetyGate checks remain unchanged and must be handled by later pre-arm work, not moved to the firing instant. Tasks 11.2–11.7 remain incomplete, so this does not make production Live ready or authorize real orders.

**Out of scope for Block 2:**

- Scheduler, timer, polling, or event bus — Block 3/4 handle these.
- Multi-account execution coordination — Block 6.
- Multi-broker routing logic — Block 7.
- Latency measurement and optimization — Block 8 (base timestamps recorded in Block 2, analysis in Block 8).
- Order splitting (M6-F) — Deferred.
- Real trading — Block 10.
- Any new broker abstraction, security mechanism, token, proof, or guard.
- Any modification to M6-A through M6-E.
- Any change to `core/dispatch_contracts.py`.

---

## 23. Development Principle

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

---

## Current Implementation Note — Block 9 Order Authorization Gate (2026-10-17)

Code implementation pushed in `503f6f6` (`feat(auth): enforce order authorization gate`).

The UI authorization boundary is implemented in `ui/order_authorization.py` and invoked by `ui/order_configuration_page.py` before queue insertion and before the Test/run path proceeds. `ui/main_window.py` supplies a lazy factory, so normal UI construction does not force authentication services, vault access, broker login, or network activity.

The gate denies unless all of the following hold: the active account matches the requested account; stored account ID and broker identity match; AuthenticationService reports that account logged in; SessionManager reports `LOGGED_IN` and holds a non-empty local token; an adapter exists and reports authenticated; the adapter broker identity matches; and the adapter's authenticated-session access token exactly matches the SessionManager token. Missing dependencies, inconsistent values, and API exceptions fail closed with a controlled non-sensitive result. The gate itself does not login, refresh tokens, access the network, or mutate session state.

This is a UI-level prerequisite, not a replacement for Core safeguards. Orders continue through `DispatchCore → OrderEngine → M6-A…M6-E`; Test remains dry-run (`live=False`); no live order was sent. The focused gate suite reported **4 passed**, UI-6 reported **28 passed**, and the combined focused gate/UI-4/UI-5/UI-6 selection reported **107 passed, 26 failed**. The 26 failures reproduce on baseline and concern the out-of-scope `BrokerManager._account_lock` initialization issue. The full repository run reported **1595 passed, 233 failed, 20 skipped, 4 errors** and remains not green. Account-aware order feedback/listener lifecycle remains separate work.

---

# Current Implementation Note — Block 9 Task 9B: Account-Scoped Order Feedback (2026-10-18)

Implementation commit: `9ad15d435c2dc12eb3d95ba3f3ead071f6884e80`.

The UI feedback runtime is owned by the account/broker identity tuple `(account_id, broker_name)`. `MainWindow` caches runtimes per tuple and resolves brokers through `BrokerManager.get_for_account(account_id, broker_name)`; a name-only broker lookup is not an acceptable fallback for this path. Construction remains lazy so opening the UI does not itself create feedback/authentication runtimes or initiate network activity.

The feedback service installs broker listeners idempotently and supports stopping/restarting the same account runtime without duplicate registrations. Feedback events are bound to the originating account. Registration, queue position and order-error events for unknown/cross-account decisions must not update another account's rows. Logout, deletion and broker change stop only the affected account runtime; changing the active account alone does not stop the previous account runtime.

Runtime start is not order authorization and never sends an order. The existing fail-closed UI authorization gate, `DispatchCore → OrderEngine → M6-A…M6-E` chain, dry-run `live=False`, and disabled live-trading policy remain authoritative.

**Scoped acceptance: COMPLETE.** The focused acceptance/regression command covering `test_block9_account_aware_order_feedback.py` and the two changed UI registration/table suites reported **56 passed in 6.09s, exit 0**. No additional Task 9B implementation is requested unless a reproducible in-scope regression is found.

**Owner-run manual local-app acceptance (2026-10-18):** two accounts on the same broker both logged in; activating either selected that account for current use while the other remained inactive; logging out one account did not disturb the other; logging the exited account back in succeeded and the other account remained normal. No issue was observed. This check covered account login/logout/re-login only; no order was submitted and live trading remains disabled.

**Next architecture gate:** broader regression and final acceptance of the local User Application. The prior coding-agent report of 57 passed / 9 failed (failures attributed to missing `nats`) and one UI-7 baseline failure should be treated as reported historical evidence until reproduced/classified in that broader run. The focused 56-pass result does not establish that the entire repository suite is green.
