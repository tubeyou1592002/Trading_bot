\# Trading Bot — Architectural Decisions



This file records important project decisions and the reason behind them.



The purpose is to prevent future AI agents from unknowingly reversing important decisions.



\---



\## Decision 001 — Use Git



\*\*Status:\*\* Accepted



The project uses Git as the local version-control system.



\### Reason



The project will be developed incrementally and may be modified by different AI coding agents.



Git provides:



\* history

\* rollback

\* change tracking

\* safe experimentation

\* agent independence



Initial baseline:



```text

f600a6c — Initial project baseline

```



\---



\## Decision 002 — Repository Is the Source of Truth



\*\*Status:\*\* Accepted



The project repository and its documentation are the primary source of truth.



Chat history is useful context but must not be required for the project to remain understandable.



\### Reason



The project may move between:



\* ChatGPT accounts

\* AI assistants

\* coding agents

\* development environments



The project must remain portable.



\---



\## Decision 003 — Broker Independence



\*\*Status:\*\* Accepted



Core trading logic must remain independent of individual brokers.



Preferred architecture:



```text

Core

&#x20;↓

Broker Interface

&#x20;↓

Broker Adapter

&#x20;↓

Broker API

```



\### Reason



The project is intended to support multiple Iranian brokers.



Broker-specific API behavior must not leak into the core engine.



\---



\## Decision 004 — Broker Adapters



\*\*Status:\*\* Accepted



Each broker should have an isolated adapter/integration layer.



Examples:



```text

Agah

Broker B

Broker C

```



\### Reason



Different brokers use different:



\* authentication

\* endpoints

\* headers

\* request bodies

\* identifiers

\* response formats

\* error systems



These differences must be isolated.



\---



\## Decision 005 — TSETMC as Market/Instrument Source



\*\*Status:\*\* Accepted



TSETMC is used for market and instrument discovery.



\### Reason



TSETMC provides the market/instrument information required for symbol resolution.



However, TSETMC identifiers must not automatically be assumed to equal broker identifiers.



\---



\## Decision 006 — Explicit Instrument Mapping



\*\*Status:\*\* Accepted



Mappings between:



```text

TSETMC insCode

ISIN

Broker instrument identifier

```



must be explicit.



\### Reason



Different systems may use different identifiers for the same financial instrument.



The mapping must be verified rather than guessed.



\---



\## Decision 007 — Dry Run Before Real Trading



\*\*Status:\*\* Accepted



Development and testing must prefer dry-run execution.



\### Reason



The project interacts with real financial systems.



Testing by accidentally submitting real orders is unacceptable.



Real-order testing requires deliberate controlled testing.



\---



\## Decision 008 — No Secrets in Git



\*\*Status:\*\* Accepted



Credentials and sensitive authentication information must never be committed.



Examples:



\* passwords

\* tokens

\* refresh tokens

\* cookies

\* captcha data

\* private API keys



\### Reason



Git history can preserve deleted secrets.



Preventing the secret from entering Git is safer than removing it later.



\---



\## Decision 009 — Do Not Guess Undocumented APIs



\*\*Status:\*\* Accepted



Unknown broker API behavior must be investigated and verified.



Agents must not invent:



\* endpoints

\* request fields

\* headers

\* identifiers

\* authentication algorithms

\* status meanings



\### Reason



Broker APIs are external systems and incorrect assumptions can cause failed or dangerous trading operations.



\---



\## Decision 010 — Incremental Development



\*\*Status:\*\* Accepted



The project should be developed incrementally.



Preferred workflow:



```text

Inspect

&#x20;↓

Understand

&#x20;↓

Plan

&#x20;↓

Implement

&#x20;↓

Test

&#x20;↓

Review

&#x20;↓

Commit

```



\### Reason



Small changes are easier to test, review and roll back.



\---



\## Decision 011 — Preserve Working Code



\*\*Status:\*\* Accepted



Working code should not be rewritten merely for stylistic reasons.



\### Reason



Unnecessary refactoring increases risk without necessarily providing functional benefit.



Refactoring should have a documented technical reason.



\---



\## Decision 012 — AI Agents Are Replaceable



\*\*Status:\*\* Accepted



No individual AI agent is considered essential to the project.



\### Reason



The project must continue if:



\* an AI service becomes unavailable

\* free credits expire

\* an account changes

\* a coding tool is replaced



Project continuity must come from Git and project documentation.



\---



\## Decision 013 — Separate Architecture From Implementation



\*\*Status:\*\* Accepted



Architecture defines boundaries and responsibilities.



Implementation details may evolve inside those boundaries.



\### Reason



This allows individual components to improve without repeatedly redesigning the entire project.



\---



\## Decision 014 — Real Trading Is a Separate Risk Level



\*\*Status:\*\* Accepted



Real order submission is treated differently from ordinary development.



\### Reason



A software bug in a trading application can have financial consequences.



The project therefore requires additional validation before production use.



\---



\## Decision 015 — Documentation Is Part of the Project



\*\*Status:\*\* Accepted



Important architecture, API discoveries, decisions, bugs and handoff information must be documented inside the repository.



\### Reason



Important knowledge must survive beyond a single conversation or AI agent.



\---



\## Decision 016 — Current Baseline Must Remain Recoverable



\*\*Status:\*\* Accepted



The initial working state is preserved as a Git baseline.



```text

f600a6c

Initial project baseline

```



Future changes should normally be made through additional commits rather than modifying history.



\### Reason



This provides a reliable recovery point for the current project.



\---



## Decision 017 — Trading State Policy



**Status:** Accepted



A trading state is considered `UNVERIFIED` until it is confirmed by a verified, authoritative source for the given broker.

`UNVERIFIED` is never treated as tradable.



### Policy



* The OrderEngine must safely block order submission whenever the trading state for the target symbol is `UNVERIFIED`.

* Each broker must explicitly implement `Broker.get_trading_state(nsc_id)`. There is no silent default at the abstract layer; a broker that does not implement the contract cannot be instantiated.

* The base `Broker` interface must not provide a fallback that could hide a missing implementation. A newly added broker is required to make an explicit, documented choice about how it reports trading state.

* For Agah specifically, the implementation continues to return `UNVERIFIED` as the intentional, documented behavior until a real, verified tradability source is identified. No Agah endpoint, field, header, or status is invented in the meantime.

* When a broker has a verified source but that source is currently unavailable (for example, a transient network or service failure), it must signal the condition narrowly via `models.trading_state.TradingStateUnavailable`. The engine catches only that narrow case for safe blocking and lets programming errors propagate.



### Reason



A wrongly-allowed order has direct financial consequences, while a wrongly-blocked order only delays execution. The safe default is therefore to refuse to send until the tradability of a symbol is explicitly verified.

Centralizing this rule in a single decision prevents future agents from "helpfully" weakening the default to `VERIFIED_TRADABLE` or from inventing an undocumented Agah endpoint to bypass the `UNVERIFIED` return.

---

## Decision 018 — Resolve Agah nscId by Symbol Search + tseId Verification

**Status:** Accepted

**Decision:**

`TSETMC ins_code` is resolved to an Agah `nscId` through the TSETMC symbol, followed by an Agah instrument search and exact `tseId` verification.

**Mapping:**

```text
TSETMC ins_code
    -> TSETMC.get_info(ins_code)
    -> Instrument.symbol
    -> Agah GET /instruments/all?query=<symbol>&count=50
    -> for each candidate nscId:
           broker.get_instrument(nscId)
           compare tse_id with ins_code
    -> matched nscId
```

**Reason:**

The earlier hypothesis that `TSETMC.cIsin == Agah.nscId` is not reliable as a general mapping.

Agah symbol search provides relevant instrument candidates, while `tse_id == TSETMC ins_code` provides the exact identity verification.

The v6 probe (`investigate_mapping_v6.py`) confirmed 7 of 7 symbols under this mapping.

**Fallback:**

There is no fuzzy or heuristic fallback.

If no Agah result has `tse_id == ins_code`, resolution fails with `InstrumentLookupError`.

Suffix-based heuristics on `nscId` (such as preferring `0001` or `0003`) are probe-side concerns only; the implementation does not encode them.

**Safety:**

`TSETMC ins_code` must never be passed directly as Agah `nscId`.

`cIsin` must not be used as the primary mapping key.

The first search result is never blindly selected.

**Evidence:**

`mapping_v6_results.json` (7/7 symbols matched).

---

## Decision 019 — InstrumentLookupError as InstrumentProvider Contract

**Status:** Accepted

**Decision:**

`InstrumentLookupError` is the official exception of the `InstrumentProvider` contract and is defined in `brokers/base.py` next to the `InstrumentProvider` ABC.

All concrete providers (including `AgaahInstrumentProvider`) and any consumer of the provider (including `core.order_engine.OrderEngine`) must use this single exception class.

A concrete provider must not define its own local `InstrumentLookupError` class. A consumer must not import `InstrumentLookupError` from a concrete provider module.

**Reason:**

* `InstrumentProvider` is a shared abstraction that the core engine depends on. The engine catches the failure of `provider.get_instrument(ins_code)` to block order submission safely.
* The exception type is part of the contract; if each provider defines its own class, the engine would either need a fragile `isinstance` check on the concrete provider or a runtime import of the provider module — both of which break broker independence (Decision 003).
* Defining `InstrumentLookupError` in `brokers/base.py` keeps the contract symmetric: the abstract provider and its abstract failure type live in the same module.

**Constraints:**

* The exception is a plain `Exception` subclass with no required fields beyond the standard message.
* Providers may include diagnostic details in the message; consumers must not parse the message.
* The exception does not carry financial intent and is purely a "lookup failed" signal; it must not be used to communicate tradability or trading state (those are governed by Decision 017).

**Evidence:**

* `brokers/base.py` defines `InstrumentLookupError`.
* `brokers/agaah/instrument_provider.py` re-uses it and no longer defines a local one.
* `core/order_engine.py` imports it from `brokers.base`, never from a concrete provider.
* `test_engine_provider_integration.py` and `test_instrument_provider.py` exercise the contract end-to-end.

---

## Decision 020 — TSETMC Trading State as Source for Order Permission

**Status:** Accepted (Discovery recorded during M5 exploration)

### Discovery

The authoritative source for **market trading state** is **TSETMC**, discovered via the official TSETMC frontend JavaScript mapping.

Endpoint(s) considered:
* `https://cdn.tsetmc.com/api/MarketData/GetInstrumentState/{InsCode}/{DEven}`
* `instrumentState` field embedded in some Market Data responses

Primary field used for mapping:
* `cEtaval` — drives the machine-readable mapping
* `cEtavalTitle` — human-readable title; used only for display/debug, not for mapping

### Discovered cEtaval Mapping (from official TSETMC frontend JS)

```text
"I " → ممنوع (Forbidden)
"A " → مجاز (Permitted)
"AG" → مجاز-مسدود (Permitted-Blocked)
"AS" → مجاز-متوقف (Permitted-Stopped)
"AR" → مجاز-محفوظ (Permitted-Reserved)
"IG" → ممنوع-مسدود (Forbidden-Blocked)
"IS" → ممنوع-متوقف (Forbidden-Stopped)
"IR" → ممنوع-محفوظ (Forbidden-Reserved)
```

### Verified Observations

Two real responses were observed confirming the mapping:
* `A  → مجاز`
* `IS → ممنوع-متوقف`

### Architectural Principle

* `cEtaval` is the basis for the mapping; `cEtavalTitle` is not the source of truth for mapping logic.
* Trading State is a **Market Data** concept. It must be sourced from TSETMC and must **not** depend on a Broker-specific API for its discovery.
* The **Broker** remains responsible for **order submission** via its own API. Market trading state and order permission are distinct concepts: a state of `AR / مجاز-محفوظ` does not mean immediate trade execution; it only means that, per the current architectural decision, order submission is permitted in this state.

### Order Permission Policy (M5)

A **separate concept** from market trading state — this is the **order permission gate** applied by the OrderEngine before submitting an order:

Permitted for order submission:
* `A  → مجاز`
* `AR → مجاز-محفوظ`

All other listed states **block** order submission:
* `AG, AS, I, IG, IS, IR`

Any unknown, missing, invalid, or error state **must** be treated as:
* `UNKNOWN / BLOCK`

### Architecture Principles Recorded

1. TSETMC is the source of Market Trading State.
2. Trading State is a Market Data concept; it must not require a Broker-specific API to discover.
3. The Broker remains responsible for order submission through its own API.
4. `cEtaval` is the primary mapping key; `cEtavalTitle` is informational only.
5. Unknown, missing, invalid, or error states must never permit order submission.
6. Instrument identity must be valid before assigning a Trading State to an Instrument.
7. This discovery does **not** enable Live Trading.
8. M5 does **not** result in real order submission.

### Reason

A wrongly-allowed order has direct financial consequences. By recording the exact TSETMC `cEtaval` mapping and a conservative order-permission gate (only `A` and `AR` allow submission; everything else blocks), the project prevents future agents from inventing undocumented tradeability rules or weakening the gate. This keeps the discovery tied to an explicit, authoritative source (TSETMC frontend JS) rather than to a third-party or guessed interpretation.

### Constraints

* Mapping is based on `cEtaval` only.
* Unknown or unrecoverable states default to `BLOCK`.
* Order permission (`A` / `AR` = allowed) is decoupled from market trading state semantics (`AR` does not imply immediate execution).
* No live order submission is enabled by this decision.

---

## Decision 021 — Block 0 Dispatch Architecture Foundation

**Status:** Accepted — IMPLEMENTED, committed as `7b29897` (Architect approved)

**Decision:**

Block 0 of the Dispatch Engine Execution Roadmap defines the architectural boundary and the base contracts of the Dispatch layer. It is contract-only and introduces no execution behavior.

**Dispatch boundary (Block 0):**

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

**Contracts defined in `core/dispatch_contracts.py`:**

* `Trigger` — abstract trigger interface (`evaluate(now) -> bool`). No scheduler, event bus, timer, or polling.
* `TimeTrigger` / `EventTrigger` — time-based and event-based triggers as contract subclasses only.
* `ExecutionPlan` — data contract between Planner and Dispatch Core (orders, accounts, broker_names, execution_order, conditions, plan_id, created_at).
* `BrokerDispatchRequest` / `BrokerDispatchResponse` — data contract between Dispatch Core and Broker.
* `DispatchResult` — simple, explicit dispatch-level status.

**Constraints:**

* Block 0 does **not** modify `core/order_engine.py`. M6-A through M6-E behavior is unchanged.
* Block 0 adds **no** new capability, token, proof, guard, wrapper, security abstraction, or security mechanism.
* Block 0 adds **no** broker implementation, no live execution, and no new dependencies.
* `live_trading_enabled` is unchanged.
* Block 0 is a pure contract layer; it has no execution behavior.

**Reason:**

The Dispatch Engine roadmap (Block 0 through Block 10) requires a stable, broker-independent contract foundation before any planner, dispatch core, or scheduling logic is built. Defining the boundary and contracts explicitly in Block 0 prevents later blocks from accidentally entangling dispatch concerns with the existing M6-A…M6-E preflight gates, and keeps the core engine broker-independent (Decision 003).

**Evidence:**

* `core/dispatch_contracts.py` — contract definitions.
* `test_block0_dispatch_contracts.py` — 11 direct contract tests, 11/11 PASS.
* Full regression: 134/134 PASS (123 existing + 11 new).
* `core/order_engine.py` unmodified; `git diff` confirms no changes to M6-A…M6-E.
* Committed as `7b29897` — `feat: add Block 0 dispatch architecture foundation`.

---

## Decision 022 — Block 2 Dispatch Core Contract

**Status:** Accepted — Contract defined, implementation NOT STARTED.

**Decision:**

Block 2 (Dispatch Core / Low-Latency Engine) is defined as the shared execution core between the Execution Planner (Block 1) and the existing M6-A…M6-E preflight gates. It implements the execution path using the contracts already established in Block 0.

**Contract alignment:**

Block 2 aligns with the complete Dispatch Core contract defined in `core/dispatch_contracts.py`. The contract is unchanged; Block 2 is responsible for implementing the execution path that uses these contracts.

**Account binding:**

Accounts must be pre-identified for execution before dispatch. The Dispatch Core must NOT re-select, re-resolve, filter, or rebalance accounts during dispatch. The Dispatch Core does NOT call `broker.get_account()` or any account discovery API. Multi-Account lifecycle coordination is out of scope for Block 2 and remains for Block 6.

**Broker binding:**

Brokers must be pre-identified for execution before dispatch. The Dispatch Core must NOT re-select or invent broker instances, create new sessions, or modify broker lifecycle during dispatch. Broker resolution from names to instances uses the existing `BrokerManager` (no new broker abstraction).

**BrokerDispatchRequest as part of the real dispatch path:**

`BrokerDispatchRequest` is the defined normalized contract envelope between Dispatch Core and Broker. The Dispatch Core must establish the real dispatch path that uses this contract. The actual Broker Adapter consuming `BrokerDispatchRequest` is NOT yet implemented; Block 2 must define how the real path will use this contract. The Dispatch Core must NOT construct broker-specific HTTP payloads, headers, or auth tokens.

**Core must not construct broker-specific payloads:**

The Dispatch Core MUST NOT construct broker-specific payloads. It passes only the normalized `BrokerDispatchRequest` envelope. The Broker Adapter is responsible for translating this envelope into the broker's native API request format. This preserves broker independence (Decision 003) and keeps the core layer free of broker-specific implementation details.

**M6-A through M6-E must not be bypassed:**

Block 2 MUST NOT bypass M6-A through M6-E. Block 2 must use the existing `OrderEngine` execution path. All preflight gates (M6-A identity/trading-state, M6-B price/quantity constraints, M6-C BUY capacity, M6-D SELL capacity, M6-E unified capacity) remain intact. The specific method calls (`prepare()`, `execute()`, `execute_by_ins_code()`) that Block 2 uses to enter the `OrderEngine` path are not yet decided and are not recorded here.

**Exact Account → Correct Broker Session/Execution Target:**

The architectural requirement is that each order is dispatched to the exact Account and Broker Session/Execution Target specified during planning. This means:
- The `account_id` binding from `PlannedOrder` must be preserved and used as the execution target.
- The `broker_name` binding from `PlannedOrder` must be preserved and used to select the correct Broker instance.
- The Dispatch Core must NOT re-resolve, rebalance, or reassign accounts or brokers.
- The Dispatch Core must NOT merge accounts, split orders across accounts, or apply any account selection logic.

This requirement is recorded as an architectural requirement. It does NOT implement Multi-Account lifecycle (Block 6) or Multi-Broker execution (Block 7); those remain for their respective blocks.

**Reason:**

The Dispatch Engine roadmap (Block 0 through Block 10) requires a stable, broker-independent dispatch core before scheduling, multi-account, or multi-broker logic is built. Defining the Block 2 contract explicitly prevents later blocks from accidentally:
1. Re-selecting accounts or brokers that were already bound by the Planner.
2. Constructing broker-specific payloads in the core layer.
3. Bypassing the M6-A…M6-E preflight gates.
4. Inventing account rebalancing or broker selection logic before the architectural requirement is explicitly reviewed.

**Constraints:**

* Block 2 does NOT modify `core/dispatch_contracts.py`.
* Block 2 does NOT modify M6-A through M6-E.
* Block 2 does NOT modify any Broker implementation.
* Block 2 does NOT introduce a scheduler, timer, polling, or event bus (Blocks 3/4).
* Block 2 does NOT implement multi-account execution (Block 6) or multi-broker execution (Block 7).
* Block 2 does NOT enable live trading.
* Block 2 does NOT add new dependencies.
* `live_trading_enabled` remains unchanged.

**Evidence:**

* This decision is a contract definition only; no code is implemented yet.
* Block 2 status remains NOT STARTED.
* All existing tests (123+) remain unchanged.

---

## Decision 023 — Independent `ui/` Package for the User Application

**Status:** Implemented — UI-1 Foundation reviewed and approved.

**Decision:**

The User Application has its own top-level package `ui/`:

```text
ui/
    __init__.py
    app.py          # QApplication creation / run entry point
    main_window.py  # Main Window (navigation + content area + mode)
    __main__.py     # `python -m ui` entry point
```

**Points:**

* The current `main.py` (legacy `SymbolSearchWindow` application) is preserved unchanged for compatibility. The new User Application does not import it and does not replace it.
* The new UI Foundation must not bypass the existing Core. OrderEngine, DispatchCore, SafetyGate and M6-A…M6-E remain the only authoritative execution path; the UI layer creates no trading logic.
* `ui/` imports nothing from `core/`, `brokers/`, `market/`, `models/` or `main.py` and performs no broker, TSETMC, credential or network access on its own. Any future trading capability is reached only through the existing Core seams (UI-2 … UI-8 per the documented User Application roadmap in `AI_HANDOFF.md`).
* This decision concerns only UI structure. It introduces no change to the execution architecture (Blocks 0–10 unchanged).

**Reason:**

The User Application roadmap (UI-1 → UI-8) requires a dedicated application shell separate from the legacy single-window prototype in `main.py`. A clean `ui/` package keeps the new shell isolated from the legacy entry point, allows incremental migration without breaking existing workflows, and makes the UI/Core boundary explicit and testable.

**Evidence:**

* `ui/` package (UI-1 Application Foundation).
* `test_ui1_application_foundation.py` — foundation tests, fully offline.
* `main.py`, `SymbolSearchWindow` and `test_main_order_workflow.py` unchanged.

---

## Decision 024 — UI Account View Uses the Existing Account Domain Model

**Status:** Implemented — UI-2.1 (pending user review).

**Decision:**

The User Application displays and manages accounts using the existing
domain model `models.account.Account`:

```text
AccountRecord (ui/account_store.py)
    ├── account: models.account.Account   # the account's own identity
    └── broker_name: str                  # application-layer association
```

**Points:**

* The UI reuses the existing `models.account.Account` model unchanged; account identity validation stays exactly the model's own rule — the UI never relaxes or redefines it.
* The broker association is NOT stored on the Account model. It lives only on `AccountRecord.broker_name` in the application layer (`ui/account_store.py`).
* The UI does not connect to BrokerManager or any Broker API for account management; no broker is instantiated by the UI. The broker selector currently offers only the one broker implemented in the repository (`آگاه`).
* `AccountStore` is purely in-memory (no persistence); there is no active account until the user explicitly selects one, and at most one account is active.
* This decision introduces no change to the execution architecture (Blocks 0–10, DispatchCore, OrderEngine, SafetyGate and M6-A…M6-E unchanged).

**Reason:**

Account identity already exists as a validated domain concept (Task 6.1). Duplicating or modifying it for the UI would create two competing definitions of account identity, and storing a UI concern (broker association) inside the domain model would blur the Block 6 / Block 7 binding architecture. Keeping the association in a thin application-layer record preserves the domain model, keeps the UI/Core boundary explicit, and lets later UI tasks evolve without touching execution architecture.

**Evidence:**

* `ui/account_store.py` (`AccountRecord`, `AccountStore`), `ui/accounts_page.py` (`AccountsPage`).
* `test_ui2_1_account_management.py` — 13 contracts, fully offline.
* `models/account.py`, `core/`, `brokers/`, `market/` unchanged.

---

## Decision 025 — Order Feedback, Queue Position, and the Task 4 Log Are Staged

**Status:** Accepted — Stage 1 and Stage 2 are implemented and verified; the Stage 3 prerequisite (OMS/NATS feedback activation bridge) is COMPLETED; the Stage 3 UI table is also IMPLEMENTED, VERIFIED, and committed as `ecfa5cf`.

### Decision 025 — Implementation Update: Stage 1

**Status:** Implemented and verified.

Stage 1 was implemented as a Core-level instrumentation extension without introducing a second latency system.

Current implemented fields per order:
- `sent_at_ns` — timestamp at the actual application send point to the broker.
- `broker_registered_at_ns` — timestamp when a successful initial Agah registration response is received. The Agah response must contain `isSuccess=true` and `data.decisionId`.
- `matching_engine_registered_at_ns` — reserved for matching-engine registration feedback, but currently remains `None` because the repository does not contain a Pusher/OMS consumer for `OmsStateChanged (100)` / `AcceptedByBourse (5)`.

Important distinction:
- Initial `POST /api/v1/order` success is initial broker/Agah registration only.
- It is not equivalent to final registration in the trading core.
- `AcceptedByBourse (5)` remains the verified trading-core registration signal documented in `AI_PROJECT_MEMORY.md`.

Implementation:
- Commit: `822c46d` — `feat: capture order feedback timing`
- Block 8 latency instrumentation is reused.
- No new event bus, polling mechanism, protocol, or persistence layer was introduced.
- Dry-run does not fabricate broker-registration feedback.
- No real order was sent during Stage 1 implementation or testing.

Verification:
- Focused Stage 1 tests: 10 passed
- Block 8 / engine / M6 / dispatch regression set: 209 passed

**Decision:**

The UI-5 Task 4 feature (live order feedback + user-facing log) is **not** implemented as one combined UI/feedback feature. It is split into three small stages, implemented and verified **independently and in order**:

```text
Stage 1 (Core)  — order feedback & timing contract
Stage 2 (Core)  — per-order queue position
Stage 3 (UI)    — the UI-5 Task 4 user-facing log table
```

Stages 1 and 2 are Core / Broker-layer work, so they are **reclassified as Core tasks that must land before the UI stage**. They are not UI-5 tasks. UI-5 Task 4 stays a **UI-only** task that consumes their contracts, exactly as it already consumes the UI-4 / Block 5 / Block 8 contracts.

**Stage 1 — Order Feedback & Timing Contract (Core):**

* Builds only the missing per-order feedback/timing connection on top of the existing execution infrastructure. No second latency system.
* For each order the system must be able to associate:

```text
sequence
sent_at_ns
broker_registered_at_ns
```

* `sent_at_ns` = the actual moment the order request is sent to the broker API (captured at the application send point).
* `broker_registered_at_ns` = the moment the application receives a valid broker/exchange feedback confirming initial registration (Agah: `isSuccess=true` and `data.decisionId`). This is **not** final trading-core registration.
* The send path **MUST NOT** wait for this feedback. Feedback is independent, and its arrival order must never change send order:

```text
send:      Order 1 -> Order 2 -> Order 3
feedback:  Order 2 -> Order 1 -> Order 3     (each updates only its own order)
```

* Existing Block 8 latency instrumentation is reused where applicable. The following measurements remain conceptually separate and must never be fabricated into one combined value:
  * send → exchange registration,
  * internal application timing,
  * broker/API round-trip timing.

**Stage 2 — Queue Position (Core):**

* Per-order queue position must come from a **verified** broker/exchange source.
* It must never be inferred, estimated, or calculated locally from unrelated data.
* When reliable queue-position data are unavailable, the UI shows an unknown/empty value — never an invented number.
* The existing Agah `getorderposition` capability must be verified against the repository's actual broker contract **before** implementation.

**Stage 2 Implementation Status (UI-5 Task 4 Stage 2):**

* Implementation complete: `brokers/agaah/nats_transport.py`, `brokers/agaah/queue_position.py`, `brokers/agaah/broker.py`
* NATS transport with runtime URL/subject/schema fetching from Agah APIs
* JWT/NKey authentication with fail-closed (no token-only fallback on privateKey parse failure)
* Decoder parses server-provided schema (ordered field list for code 100)
* Queue position fetched from `GET /api/v1/order/getorderposition` with nscId, hostOrderNumber, orderDate
* orderDate extracted from SavedInAsa (2) message, timezone converted (Asia/Tehran → UTC)
* hostOrderNumber extracted from AcceptedByBourse (5) message
* Order correlation via decisionId only
* Non-blocking: OMS handler schedules async fetch without blocking message loop
* Non-blocking: order placement does not wait for queue position
* Fail-closed: missing params, API failure, invalid response → position = None

**Stage 2 Gap — Lifecycle:**

* `start_queue_position_tracking()` / `stop_queue_position_tracking()` have NO call sites in the application.
* The Qt application (`ui/app.py`) has no asyncio event loop; `start`/`stop` are async methods that cannot be called from the synchronous app lifecycle.
* No new event loop bridge, background thread, scheduler, or event bus was created (per task constraints).
* **Gap:** The transport implementation is complete but cannot be activated in the current Qt application lifecycle without a lifecycle bridge (deferred to a separate task).

**Stage 2 Gap — Dependency Declaration:**

* No `requirements.txt`, `pyproject.toml`, `setup.py`, `setup.cfg`, `Pipfile`, `uv.lock`, or `poetry.lock` exists in the repository.
* `nats-py` and `nkeys` are installed on the Agent's system but are not declared in any manifest.
* **Gap:** No dependency manifest exists to declare `nats-py` and `nkeys`. No new package-management architecture was created per constraints.

**Stage 3 — UI-5 Task 4 User-Facing Log (UI):**

**Status: IMPLEMENTED and VERIFIED — commit `ecfa5cf`.**

The user-facing order log table is a live UI monitor that consumes the contracts from Stages 1 and 2 plus the completed feedback activation bridge.

Required seven columns:
1. `زمان ارسال`
2. `حساب`
3. `نماد`
4. `توضیح`
5. `زمان دریافت توسط کارگزاری`
6. `زمان ثبت در هسته معاملاتی در صورت وجود`
7. `وضعیت صف`

Verified behavior:
- Rows are appended in send order and remain in that order.
- Column 5 consumes the existing Stage 1 broker-receipt timestamp.
- Column 6 is populated only by matching-engine registration feedback; `AcceptedByBourse` (action=5) is the only green/registration trigger.
- `SavedInAsa` (action=2) does not green or stamp the row as registered in the trading core.
- Column 7 consumes only the existing Stage 2 queue-position signal through `decisionId` correlation; the UI performs no queue polling or queue-position calculation.
- Unknown/invalid queue feedback is fail-closed and duplicate identical delivery is idempotent.
- `decisionId` is internal correlation state and is never rendered.
- No persistence, export, new logging framework, or trading logic was introduced.
- Real trading remains disabled.

Verification:
- Focused Stage 3 Task 4 tests: 10 PASS.
- Related Stage 3 suite: 126 PASS.
- Combined Stage 3 verification: 136 PASS.
- `git diff --check`: clean before commit.

**Deferred to UI-6:** latency/diagnostic/trace-style presentation and detailed execution timing.


**Conflicts resolved by this decision:**

1. **UI-5 safety rule #4 ("modifies no file under `core/`, `brokers/`, `market/`, or `models/`").** Stage 1 stamps the broker submission boundary and the registration feedback; Stage 2 reads a broker endpoint. Neither can be built inside `ui/`. Resolution: Stages 1 and 2 are Core tasks that precede the UI task; UI-5 Task 4 stays UI-only.
2. **UI-5 safety rule #3 ("Trace ID, Latency, and detailed diagnostics belong to UI-6").** The superseded Task 4 spec listed latency-style columns. Resolution: exchange registration time, send → registration delay, and internal/API timing are **UI-6 scope** and are removed from the UI-5 Task 4 table.
3. **No combined latency value.** Block 8 already keeps the internal-stage layer and the broker/API layer separate (its `clocks_shared` guard leaves derived values `None` rather than fabricating a cross-clock delta). These stages must not merge `confirmation_delay`, internal application timing, and broker/API round-trip timing into one number.

**Constraints:**

* Do not recreate Block 5 execution tracking or Block 8 latency instrumentation; reuse them.
* Do not modify the order-send path merely to display results.
* Do not block timed/burst sending while waiting for broker/exchange feedback.
* Do not guess undocumented broker APIs or queue-position semantics.
* Each stage is implemented and verified independently **before** the next stage begins.
* `live_trading_enabled` remains disabled; no real order is sent by these stages.

**Open items — verify, never invent:**

* `brokers/base.py` today exposes only `get_account` and `place_order`; the Broker contract has no order-status or queue-position method.
* `GET /api/v1/order/{decisionId}` and `GET /api/v1/order/getorderposition` are recorded in `AI_PROJECT_MEMORY.md` only as **observed Agah panel traffic**; that file states the exact order-entry status endpoint "has not yet been fully identified".
* `sent_at_ns` and `broker_registered_at_ns` now exist in the Block 8-based order timing instrumentation. `matching_engine_registered_at_ns` remains unpopulated until a verified OMS/Pusher consumer exists. A final confirmation delay to matching-engine registration is therefore not currently available. Block 8 timestamps are monotonic `perf_counter_ns` ticks, and `models.order.Order.creation_date` is a wall-clock construction stamp, not a send stamp.

* With `place_order(live=False)` an order never reaches an exchange, so dry-run execution has no honest broker or exchange registration timestamp. Stage 1 therefore records no broker-registration timestamp for dry-run, and does not fabricate matching-engine feedback.

**Reason:**

Order feedback and queue position are broker- and core-level facts. They cannot be produced, and must not be guessed, inside the UI layer. Splitting the work keeps the binding UI-5 boundaries intact (the UI still modifies no `core/`/`brokers/`/`market/`/`models/` file, and latency/diagnostic data stays in UI-6), while making each piece independently verifiable against the real broker contract before anything user-facing depends on it. Staging also prevents the UI table from being built on data that does not yet exist and would therefore have to be invented.

**Evidence:**

* `AI_HANDOFF.md` — the UI-5 Task 4 section, rewritten by this decision (supersedes the six-column spec).
* No code implemented by this decision; no test added; `core/`, `brokers/`, `market/`, `models/`, `ui/` unchanged.

---

## Stage 2 Implementation Evidence

* Implementation files: `brokers/agaah/nats_transport.py`, `brokers/agaah/queue_position.py`, `brokers/agaah/broker.py`, `core/order_engine.py`
* Tests: `test_ui5_task4_stage2_queue_position.py` — 39 tests covering NATS transport, OMS decoding, queue position fetch, timezone conversion, non-blocking behavior
* API evidence: `AI_PROJECT_MEMORY.md` §5b — Agah OMS via NATS, OmsStateChanged states, `oms_042` error mapping
* Protocol: NATS WebSocket transport with JWT/NKey authentication (`nkeys_seed_str`)
* Endpoints: `GET /api/v1/pusher/nats` (connection info), `GET /api/v1/Pusher/message-types` (schema), `GET /api/v1/order/getorderposition` (queue position)
* Dependencies: `nats-py`, `nkeys` (installed but not declared — no manifest exists)

---

## Stage 3 Prerequisite Implementation Evidence — Feedback Activation Bridge (COMPLETED)

The lifecycle gap recorded above is now closed. The Stage 3 prerequisite and the Stage 3 UI table are COMPLETED; the UI table is committed as `ecfa5cf`.

* Implementation files: `ui/order_feedback_service.py` (new — `OrderFeedbackService`), `ui/main_window.py`, `ui/test_runner.py`, `brokers/agaah/broker.py`, `brokers/agaah/queue_position.py`
* Lifecycle is ACTIVE: the service starts on entering Order Configuration (`select_page`) and stops on window close (`closeEvent`).
* `TestRunner` and `OrderFeedbackService` use the SAME shared `BrokerManager` / `AgaahBroker` instance (lazy `MainWindow._shared_broker_manager()`), so the order execution path and the OMS feedback path share one broker identity.
* `AcceptedByBourse` (action=5) is the ONLY trigger for core order-registration (`on_order_registered` fires only from `_handle_accepted_by_bourse`); `SavedInAsa` (action=2) does not trigger core registration.
* The asyncio/NATS loop runs on a dedicated background `QThread`; it never touches the GUI thread and never blocks order sends. Receiving path only — no scheduler, no order sending.
* Verification tests (actual runs): 122 (UI-5 core 90 + UI-3.1 regression 32) PASS; full UI regression 206 PASS; core regression (M5/M6/engine/provider/broker manager) 152 PASS. Fully offline — no real Agah/NATS/network.
* Status: COMPLETED — Stage 3 UI table implemented and verified in `ecfa5cf`.

---

## Decision 026 — Finalized UI-6 Roadmap (Four Tasks)

**Status:** Accepted — finalized roadmap. Implementation status: UI-6 COMPLETED after Task 4 verification (2026-10-02); evidence is recorded below.

**Decision:**

UI-6 — Test / Diagnostic Mode consists of exactly four implementation tasks:

1. **Diagnostic Mode Foundation** — establish the `NORMAL` / `DIAGNOSTIC` presentation boundary; keep technical information hidden in Normal Mode; do not change trading/execution behavior or add latency measurement.
2. **Trace ID** — expose and display the existing execution `trace_id` only in Diagnostic Mode; do not generate a UI-specific Trace ID.
3. **Latency & Execution Diagnostics** — present only timing already available from Block 8 in Diagnostic Mode; preserve separate latency categories and leave missing/cross-clock values unavailable. Do not duplicate instrumentation, fabricate values, or combine unrelated timing layers.
4. **Integration, Regression & Documentation** — verify both modes, Trace ID, diagnostics, and unchanged UI-5 behavior; run relevant regressions; mark UI-6 complete only after verification.

**Roadmap order:** `UI-1 → UI-2 → UI-3 → UI-4 → UI-5 → UI-6 → UI-7 → UI-8 → Central Server`.

UI-5 remains COMPLETED. UI-6 Tasks 1–3 are completed; Task 4 (Integration, Regression & Documentation) is COMPLETED. UI-6 is COMPLETE. UI-7 owns Schedule / Countdown, and UI-8 owns End-to-End Integration & Acceptance. Central Server, Admin Panel, new latency instrumentation, new execution/trading logic, historical log persistence, export/filtering, and M6-F order splitting are outside UI-6.

**Architectural rule:** UI-6 consumes and presents existing Block 8 execution/latency information. It does not redesign or duplicate Block 8. Its latency layers remain separate; unavailable or cross-clock values are not synthesized.

**Evidence:**

* Roadmap details are recorded in `AI_HANDOFF.md` §9 and summarized in `AI_PROJECT_MEMORY.md`.
* This decision records the roadmap scope; task completion is tracked in the current status update below.

**Task 1 completion record (2026-10-01):** UI-6 Task 1 — Diagnostic Mode Foundation was completed using the existing `ApplicationMode`; invalid values hide the diagnostic section. Reported verification: 12 focused tests and 182 related UI regression tests passed. At that point Tasks 2–4 were not started; the current status is recorded in the following update. This record does not change the four-task scope or Block 8 boundaries above.

**Current implementation status update (2026-10-01):** UI-6 Task 2 — Trace ID is COMPLETED. The UI presents the existing dispatch-level `DispatchResult.trace_id` only in Diagnostic Mode; invalid or missing results remain unavailable, and a failed new runner attempt immediately clears the previous Trace ID. No ID generation or Core/Broker/Block 8 changes were introduced. Reported verification: 20 focused tests and 190 related UI regression tests passed. Task 3 is next; Task 4 remains not started. UI-6 as a whole is not complete.

**Current implementation status update (2026-10-01):** UI-6 Task 3 — Latency & Execution Diagnostics is COMPLETED. The UI consumes the current run's existing Block 8 report. Dispatch duration, each internal stage per order, each Broker/API call per order, and application-side fields are shown as separate categories. Per-order labels use the report's `Order` identity; Broker/API rows include operation and call number. Missing stage/value and cross-clock fields remain unavailable; the UI does not display cross-order medians or operation sums as individual measurements and adds no instrumentation. Verification: 28 focused tests and 289 selected UI regression tests passed (UI-1, UI-3.2A/B, UI-4, UI-5). UI-3.1 was omitted because its modal-dialog test hangs in this offscreen environment, also on baseline. Task 4 is next; UI-6 remains in progress and is not complete.

**Task 4 completion record (2026-10-02):** UI-6 Task 4 — Integration, Regression & Documentation is COMPLETED, and UI-6 as a whole is COMPLETE. Verified in this session against the actual repository state (not from prior reports): `python -m pytest test_ui6_task1_diagnostic_mode.py -q` → **28 passed**. The acceptance criteria were confirmed by the focused suite: in NORMAL all diagnostic information (Trace ID and every latency/diagnostic row) stays hidden; in DIAGNOSTIC only the current run's real data is shown; the Trace ID is the existing run identifier and a failed new runner attempt never leaves the previous run's Trace ID behind; latency categories (dispatch duration, internal stages, Broker/API calls, application-side) remain separate and a missing or cross-clock value is never fabricated or estimated; and toggling the diagnostic mode does not change order send/execution behavior or any UI-5 behavior. Regression: `python -m pytest test_ui1_application_foundation.py test_ui3_2a_symbol_search.py test_ui3_2b_trading_state_display.py test_ui4_queue_ui_integration.py test_ui5_task3_feedback_service.py -q` → **70 passed** (UI-1, UI-3.2A, UI-3.2B, UI-4, UI-5 subset). Environment limitations recorded honestly, not treated as passes: `test_ui3_1_order_configuration.py` was deliberately **not** run, because its modal-dialog test already hangs in this offscreen environment on the baseline as well; `test_ui5_task4_stage2_queue_position.py` cannot even be collected here (`ModuleNotFoundError: No module named 'nats'`, `nats-py` not installed); and the remaining UI-5 tests that import `brokers.agaah.nats_transport` (`test_ui5_task4_stage3_task3_core_registration.py`, `test_ui5_task4_stage3_task4_ui_table.py::TestGreenRegistration::test_saved_in_asa_never_greens_or_stamps`) fail at that same import in this environment. These failures are collection/environment-level and unrelated to the UI-6 code paths, but they mean the UI-5 Stage 2/Stage 3 coverage was **not** fully re-verified in this session. No code, test, or configuration was changed in Task 4; only this documentation set was updated, and nothing was committed or pushed.

**Follow-up verification (2026-10-02):** In the user's Python 3.13 environment, `nats-py` 2.16.0 was available and the previously blocked UI-5 suites were rerun: `python -m pytest test_ui5_task4_stage2_queue_position.py test_ui5_task4_stage3_task3_core_registration.py test_ui5_task4_stage3_task4_ui_table.py -q` → **79 passed**, resolving the earlier NATS import limitation. The previously blocked Qt tests were also fixed at the test seam only: `QMessageBox.warning` is mocked and asserted, and the UI-3.1 AST allowlist now recognizes UI-6's lazy `core.dispatch_contracts` import. The full affected files passed: `python -m pytest test_ui2_1_account_management.py test_ui3_1_order_configuration.py -q` → **46 passed**. No UI-6 production code changed.

---

## Decision 027 — UI-7 Schedule & Countdown Roadmap (Four Tasks)

**Status:** Accepted — implementation in progress; UI-7 Tasks 1, 2, and 3 are completed (2026-10-02 and 2026-10-03); Task 4 is next. UI-7 as a whole is not complete.

**Decision:** UI-7 consists of exactly four implementation tasks:

1. **Schedule Configuration & Validation** — provide Start Time, End Time, Interval, and Apply Schedule; reuse existing Block 3 timing validation and timestamp generation; use Tehran time (`Asia/Tehran`) as confirmed by the user; summarize accepted input. Establish the clock foundation: NTP disciplines the system clock for high-resolution continuity, while TSETMC is the market-time comparison/calibration source. Account for request elapsed time when estimating offset; apply bounded gradual correction only to an application-level logical clock, never abruptly change the OS clock. Keep countdown and elapsed-time measurement monotonic. The TSETMC body has seconds-only precision, so state its uncertainty and do not promise or fabricate zero-millisecond alignment. User-provided Chrome DevTools evidence identifies unauthenticated `GET https://cdn.tsetmc.com/api/StaticData/GetTime`, returning `200 text/plain` in `MM/DD/YYYY HH:MM:SS` Gregorian format with seconds-only precision. This endpoint is unofficial/undocumented, has no stability/SLA guarantee, and may be IP-restricted. Validate status, content type, exact format, timestamp, timeout, and freshness; inspect `Age`, `Cache-Control`, `Date`, and optional `Expires` / `Last-Modified`. The HTTP `Date` header is GMT/UTC; it must not be mistaken for the Tehran-time body. If Start Time is past but End Time remains ahead, notify and begin once immediately without replaying missed intervals; if End Time has passed, expire without dispatch.
2. **Countdown & Schedule State** — sync once after the main window appears and provide manual sync; show source, offset, uncertainty, and monotonic freshness (30-second Apply limit). Apply consumes the last completed sync or waits for one in flight, without making a new request; missing/stale/failed market time falls back to the system clock with a soft notice. Freeze the effective time and monotonic anchor at Apply so later syncs or wall-clock steps cannot move the countdown. Lock order/queue/schedule controls immediately, including while waiting for sync; change Apply to Stop. Stop cancels a pending or active countdown without dispatch and unlocks controls; expiry unlocks. Task 2 does not dispatch orders. Manual Stop is approved; pause/retry remain out of scope.
3. **Timed Dispatch Integration** — invoke the existing UI/Core dispatch path at due timestamps and within the configured window; preserve identity and Core/SafetyGate/M6-A…M6-E checks; prevent early, late, duplicate, post-window, or compressed catch-up dispatches; keep Test Mode separate from Apply Schedule.
4. **Integration, Regression & Documentation** — deterministically verify timing boundaries, countdown, past-start/expired behavior, site-time timeout/invalid/stale fallback and recovery notices, no duplicate/catch-up dispatch, and unchanged UI-5/UI-6 behavior; record test results before marking UI-7 complete.

**Existing infrastructure:** Block 3 already provides `DispatchTiming`, `TimedDispatchTrigger`, and `TimedDispatchScheduler`. These validate timing and generate deterministic timestamps but intentionally provide no real timer or runtime loop. UI-7 owns the UI-side countdown and due-time coordination and must reuse the Block 3 contracts rather than duplicating schedule math.

**Clock-source decision:** Prefer the stock-market site's server time in Tehran timezone (`Asia/Tehran`, confirmed by the user). NTP disciplines the system clock for high-resolution continuity; compare it with TSETMC, whose seconds-only body limits market-time offset precision. If site time is unavailable, invalid, or stale, use the NTP-disciplined system clock with a soft notice; disclose reduced confidence if NTP is also unsynchronized. Apply bounded gradual correction only to application-level logical time, never abruptly change the OS clock; use a monotonic source for elapsed time/countdowns. Before Apply, a valid, fresh market sync is preferred. Once Apply locks an active schedule, later syncs or system wall-clock steps do not retarget its countdown. The user-provided capture identifies the endpoint and wire format above; the endpoint is unofficial/undocumented. The HTTP `Date` header is GMT/UTC, while the response body is Tehran time. In Task 3, source changes may not duplicate a dispatched slot or replay missed intervals. A past start with a future end begins once immediately after notifying; a past end expires without dispatch.

**Task 1 completion record (2026-10-02):** Clock and schedule configuration foundation implemented in `ui/market_clock.py`, `ui/schedule_settings.py`, and `ui/order_configuration_page.py`, with 102 offline UI-7 tests. Reported results: UI-7 **102 passed**; UI-1/UI-2.1/UI-3.2/UI-6 regression selection **97 passed**; UI-4/UI-5 runnable subset **155 passed**; offline import guard clean. The same baseline selections matched those counts. UI-3.1 `test_5` hangs in this environment, including baseline; one UI-5 Stage 3 table test is blocked by unavailable `nats`. Full UI-3.1 and UI-5 Stage 3 are therefore not claimed as reverified. Overnight windows are unsupported; real endpoint/CDN behavior was not tested. Task 1 is complete; UI-7 remains in progress and Task 2 is next.

**Task 2 completion record (2026-10-03):** Added one-shot startup sync after the main window is shown, manual sync, monotonic freshness display, and Apply/Stop countdown state. Apply does not create a network request; it consumes the last completed sync or waits for one already running, then uses the system clock with a soft notice if market time is missing/stale/failed. The active countdown freezes the effective current time and monotonic anchor. All order/queue/schedule controls lock immediately on valid Apply, including during pending sync; Stop cancels pending/active countdown without dispatch and unlocks controls. Expiry also unlocks. Verification: the user ran the full focused file `test_ui7_task2_countdown_state.py` → **17 passed** after installing `tzdata`; the targeted non-rewind test passed as well. The focused suite includes selected UI-5/UI-6 checks. Reported UI-1/UI-2.1/UI-3.2/UI-6 selection (**97 passed**) and UI-4/UI-5 runnable subset (**155 passed**) were not rerun after the final Task 2-only fixes. No live endpoint request or order dispatch was made. Task 3 is next; UI-7 remains in progress.

**Task 3 completion record (2026-10-03):** Implemented the UI-side periodic dispatch coordinator in `ui/schedule_dispatcher.py`, connected from `ui/order_configuration_page.py` to the existing UI/Core send path. The user-selected millisecond cadence is monotonic; broker groups fan out concurrently, and pending broker responses do not block or cap later cadence turns. A past start triggers once at the first execution opportunity without catch-up; a future start and the window end remain fixed. The full queued destination set is validated before activation: empty queue, missing account, or account/broker mismatch rejects the schedule instead of partially dispatching. Per-group start delay is measured immediately before `runner.run(...)`, not at submit or response completion, and remains separate from Block 8. Stop prevents new turns; already in-flight calls are not force-cancelled. Task 1/2 test fixtures were updated with a valid destination while retaining their schedule/countdown assertions. Reported verification before the final guard correction: Task 3 **63 passed**, Tasks 1–3 **182 passed**, and selected UI-5/UI-6/Block 8 regressions **220 passed**. The user ran the focused regression for the final destination-revalidation guard → **1 passed**; the full suites were not rerun after that correction. No live order was enabled or sent. UI-7 remains in progress; Task 4 is next.

**Boundaries:** No new trading/execution logic, Core/SafetyGate/M6 bypass, live-trading enablement, retries, order splitting (M6-F), or UI-8 end-to-end Broker-boundary acceptance. UI-8 remains the final integration/acceptance phase. Roadmap order remains `UI-1 → UI-2 → UI-3 → UI-4 → UI-5 → UI-6 → UI-7 → UI-8 → Central Server`.
