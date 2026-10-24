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
* Historical implementation detail at the time of this decision: `AccountStore` was purely in-memory (no persistence). The persistence detail was superseded by Decision 032 on 2026-10-17; the remaining rule is unchanged: there is no active account until explicit user selection, and at most one account is active in memory.
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

**Status:** Accepted — implemented and complete. UI-7 Tasks 1, 2, and 3 were completed on 2026-10-02 and 2026-10-03, and Task 4 (Integration, Regression & Documentation) was completed on 2026-10-03. UI-7 consists of exactly four tasks and **all four are complete; UI-7 is COMPLETE**. The next phase is UI-8 (End-to-End Integration & Acceptance).

**Decision:** UI-7 consists of exactly four implementation tasks:

1. **Schedule Configuration & Validation** — provide Start Time, End Time, Interval, and Apply Schedule; reuse existing Block 3 timing validation and timestamp generation; interpret user inputs in `Asia/Tehran`; summarize accepted input. Use the Windows system clock, synchronized externally with NetTime/NTP. The application does not run NTP, change the OS clock, or query TSETMC time. At Apply, sample system wall time and monotonic time together and project deadlines to monotonic time. If Start Time is past but End Time remains ahead, begin once immediately without replaying missed intervals; if End Time has passed, expire without dispatch.
2. **Countdown & Schedule State** — show the live system clock labelled «ساعت سیستم» and preserve countdown, state and Apply/Stop controls. Apply anchors system wall time to monotonic time; later wall-clock adjustments cannot move countdowns/deadlines. Stop cancels an active countdown and unlocks controls; expiry unlocks. Task 2 does not dispatch orders. Pause/retry remain out of scope.
3. **Timed Dispatch Integration** — invoke the existing UI/Core dispatch path at due timestamps and within the configured window; preserve identity and Core/SafetyGate/M6-A…M6-E checks; prevent early, late, duplicate, post-window, or compressed catch-up dispatches; keep Test Mode separate from Apply Schedule.
4. **Integration, Regression & Documentation** — deterministically verify timing boundaries, countdown, past-start/expired behavior, site-time timeout/invalid/stale fallback and recovery notices, no duplicate/catch-up dispatch, and unchanged UI-5/UI-6 behavior; record test results before marking UI-7 complete.

**Existing infrastructure:** Block 3 already provides `DispatchTiming`, `TimedDispatchTrigger`, and `TimedDispatchScheduler`. These validate timing and generate deterministic timestamps but intentionally provide no real timer or runtime loop. UI-7 owns the UI-side countdown and due-time coordination and must reuse the Block 3 contracts rather than duplicating schedule math.

**Clock-source decision (updated):** Schedule display and timing use only the Windows system clock. The operating system is synchronized outside the application with NetTime/NTP; the application does not run NTP or change the OS clock. User-entered schedule times remain Tehran wall-clock times. At Apply, the application samples system wall time and monotonic time together, then projects every deadline onto monotonic time so later wall-clock adjustments cannot jump or repeat a run. TSETMC's time endpoint is not used by the schedule or startup paths; its non-time symbol, trading-state, and price-limit data paths remain unchanged.

**Task 1 completion record (2026-10-02):** Clock and schedule configuration foundation implemented in `ui/market_clock.py`, `ui/schedule_settings.py`, and `ui/order_configuration_page.py`, with 102 offline UI-7 tests. Reported results: UI-7 **102 passed**; UI-1/UI-2.1/UI-3.2/UI-6 regression selection **97 passed**; UI-4/UI-5 runnable subset **155 passed**; offline import guard clean. The same baseline selections matched those counts. UI-3.1 `test_5` hangs in this environment, including baseline; one UI-5 Stage 3 table test is blocked by unavailable `nats`. Full UI-3.1 and UI-5 Stage 3 are therefore not claimed as reverified. Overnight windows are unsupported; real endpoint/CDN behavior was not tested. Task 1 is complete; UI-7 remains in progress and Task 2 is next.

**Task 2 completion record (2026-10-03):** Added one-shot startup sync after the main window is shown, manual sync, monotonic freshness display, and Apply/Stop countdown state. Apply does not create a network request; it consumes the last completed sync or waits for one already running, then uses the system clock with a soft notice if market time is missing/stale/failed. The active countdown freezes the effective current time and monotonic anchor. All order/queue/schedule controls lock immediately on valid Apply, including during pending sync; Stop cancels pending/active countdown without dispatch and unlocks controls. Expiry also unlocks. Verification: the user ran the full focused file `test_ui7_task2_countdown_state.py` → **17 passed** after installing `tzdata`; the targeted non-rewind test passed as well. The focused suite includes selected UI-5/UI-6 checks. Reported UI-1/UI-2.1/UI-3.2/UI-6 selection (**97 passed**) and UI-4/UI-5 runnable subset (**155 passed**) were not rerun after the final Task 2-only fixes. No live endpoint request or order dispatch was made. Task 3 is next; UI-7 remains in progress.

**Task 3 completion record (2026-10-03):** Implemented the UI-side periodic dispatch coordinator in `ui/schedule_dispatcher.py`, connected from `ui/order_configuration_page.py` to the existing UI/Core send path. The user-selected millisecond cadence is monotonic; broker groups fan out concurrently, and pending broker responses do not block or cap later cadence turns. A past start triggers once at the first execution opportunity without catch-up; a future start and the window end remain fixed. The full queued destination set is validated before activation: empty queue, missing account, or account/broker mismatch rejects the schedule instead of partially dispatching. Per-group start delay is measured immediately before `runner.run(...)`, not at submit or response completion, and remains separate from Block 8. Stop prevents new turns; already in-flight calls are not force-cancelled. Task 1/2 test fixtures were updated with a valid destination while retaining their schedule/countdown assertions. Reported verification before the final guard correction: Task 3 **63 passed**, Tasks 1–3 **182 passed**, and selected UI-5/UI-6/Block 8 regressions **220 passed**. The user ran the focused regression for the final destination-revalidation guard → **1 passed**; the full suites were not rerun after that correction. No live order was enabled or sent. UI-7 remains in progress; Task 4 is next.

**Task 4 completion record (2026-10-03) — Task 4 COMPLETE, UI-7 COMPLETE:** Task 4 ran the required UI-7 and UI-1→UI-6 verification and closed the one UI-7 regression it found. No UI-7 production bug was found, so no UI-7 implementation file was modified; the single code change was to `test_ui3_1_order_configuration.py`, whose architectural seam contract is authorized to register the two EXISTING Block 3 seams UI-7 reuses, `core.timing_contracts` and `core.timed_dispatch_scheduler`. The contract's laziness rule was preserved and generalized, not relaxed: a new `must_stay_lazy` set covers those two seams alongside `market.symbol_resolver`, and importing either at module level still raises. This was verified by mutation — hoisting the import in `ui/schedule_settings.py` to module level makes `test_14` fail with "imports core.timing_contracts at module level", and the file was restored byte-identically afterwards. Final runs, all offline with no TSETMC request and no real order: UI-7 Tasks 1+2+3 **183 passed** (exit 0); UI-1, UI-2.1, UI-3.1, UI-3.2A, UI-3.2B and all eight UI-4 files **188 passed, 2 deselected** (exit 0); UI-5 (all eight files) and UI-6 **173 passed** (exit 0); Block 3 timing contracts/scheduler/trigger **32 passed** (exit 0); Block 8 tasks 8.2/8.3/8.4/8.5 plus `dispatch_core` **124 passed, 2 failed** (exit 1). An offline import guard was added: importing `ui.main_window`, `ui.order_configuration_page`, `ui.schedule_settings`, `ui.schedule_dispatcher` and `ui.market_clock` with `socket.socket`/`socket.create_connection` disabled creates no socket. Every UI-7 acceptance criterion was re-checked and holds: site/system clock, initial and manual sync, freshness, fallback and user messages; Apply fixing time and the monotonic base; Stop halting future sends and expiry releasing locks; a past start producing exactly one immediate start with no catch-up replay while a future start stays unshifted and nothing starts after the window end; the user-selected millisecond cadence, with a turn never waiting on the previous turn's response and the brokers of one turn reaching the send path together; correct and fixed order/account/broker bindings, with empty queue, invalid account and broker mismatch each rejecting the whole schedule and never sending a partial set; the recorded start being the real `runner.run(...)` entry boundary with Block 8 untouched and unmerged; unchanged UI-5/UI-6 behavior; and no live or real broker access enabled. Remaining known items, all confirmed pre-existing and unrelated to UI-7 by reproducing each identically at pre-UI-7 commit `6901a82`: the two Block 8 `broker_received_at` contract failures in `test_block8_task8_2.py::test_latency_does_not_add_fields_to_existing_contracts` and `test_block8_task8_3.py::test_measurement_keeps_existing_engine_and_result_contracts` — they concern a Broker-received timestamp field and Block 8 and Core are outside Task 4 scope; and the two UI-3.1 hangs `test_5_quantity_enter_and_store` and `test_extra_page_preserves_state_on_fractional_input`, deselected so the remainder could be verified. Previously reported limitation RESOLVED: `nats` is installed, so `test_ui5_task4_stage3_task4_ui_table.py` ran → **10 passed**; the earlier note that UI-5 Stage 3 was blocked no longer applies. Environment limitation: this machine has no IANA tz database, so every run used the out-of-repo shim `PYTHONPATH=/tmp/tzshim` mapping Asia/Tehran to a fixed +03:30, together with `QT_QPA_PLATFORM=offscreen`; no repository file was modified for it. UI-7 consists of exactly four tasks and all four are complete. The next phase is UI-8.

**Boundaries:** No new trading/execution logic, Core/SafetyGate/M6 bypass, live-trading enablement, retries, order splitting (M6-F), or UI-8 end-to-end Broker-boundary acceptance. UI-8 remains the final integration/acceptance phase. Roadmap order remains `UI-1 → UI-2 → UI-3 → UI-4 → UI-5 → UI-6 → UI-7 → UI-8 → Central Server`.

---

## Decision 028 — UI-8 End-to-End Integration & Acceptance Roadmap (Four Tasks)

**Status:** Accepted and complete after completed UI-7. UI-8 has exactly four tasks and all four are complete; **UI-8 is COMPLETE**. The next phase is Central Server. Recorded limitations, not capabilities: one Test pass over a mixed-account/mixed-broker queue remains rejected, and the pre-existing Block 8 `broker_received_at` contract failures plus the two known UI-3.1 hangs stay open for a separately scoped repair.

**Decision:** Split UI-8 acceptance into four bounded tasks:

1. **Single-Account / Single-Broker End-to-End Path** — verify the existing UI → TestRunner → Core → Broker-boundary flow using offline doubles, including order input, plan/dispatch result, and user-visible feedback.
2. **Multi-Account / Multi-Broker Routing and Identity** — verify order/account/broker binding through planning, dispatch, result collection, and UI feedback, including mixed destinations and failure cases.
3. **Safety Gates, Modes, and Diagnostics** — verify fail-closed and M6-A…M6-E checks at the existing Core/SafetyGate boundary; Test Mode remains distinct from Live; verify Diagnostic Mode, UI-5 feedback, and UI-6 Trace ID/latency presentation using existing Block 8 data without merging timing layers.
4. **Regression, Acceptance, and Documentation** — run and record relevant UI-1…UI-7, M6, and Block 8 regressions; confirm no behavior regression or safety bypass; document actual results and limitations; mark UI-8 complete only after required acceptance checks pass.

**Boundaries:** Use offline doubles and stop at the existing Broker boundary. No real order, broker credentials, or Live permission is authorized. Do not redesign Core, M6, Block 8, or UI-7. Central Server, Admin Panel, License/Activation, and multi-user rollout remain later phases. If acceptance reveals a code/test gap, request a separately scoped repair before changing files.

**UI-8 Task 1 completion record (2026-10-03):** Added `test_ui8_task1_single_broker_e2e.py`, one offline E2E test covering one order/account/broker from the actual UI queue and Test action through TestRunner, DispatchIntegration, DispatchCore, OrderEngine, and SimulationBroker. It checks identity preservation, exactly one `live=False` broker call, dry-run result fields, and visible UI feedback; real network and broker construction paths are guarded. The test does not assume a SafetyGate is attached and was reported passing both in the working tree and in a temporary copy of committed HEAD without the pre-existing local `ui/test_runner.py` modification. Focused test: **1 passed**; focused test plus directly related UI-5 Task 2/3 tests: **42 passed**. No production code, settings, or existing tests changed; no live order/network access occurred. Task 1 is complete; Task 2 is next. UI-8 remains in progress.

**UI-8 Task 2 completion record (2026-10-03):** Added `test_ui8_task2_multi_account_multi_broker_e2e.py` with two offline E2E tests. The supported routing path is verified through real UI/TestRunner/Core/OrderEngine flows using two simulation broker/provider pairs: three orders across two accounts and two brokers are delivered only to their assigned simulator in separate single-account passes, with identity, dry-run, and UI-result attribution checked. A mixed-account/mixed-broker queue is explicitly tested and rejected before dispatch; neither simulator is called and the queue remains intact. **One-pass execution of mixed destinations is not currently supported.** This product limitation was recorded rather than bypassed; changing it needs a separate product decision and implementation scope. Reported verification: Task 2 **2 passed**; Task 1 + Task 2 **3 passed**. No production code or unrelated tests changed; no live order or network access occurred. Task 2 verification is complete; Task 3 is next. UI-8 remains in progress.

**UI-8 Task 3 completion record (2026-10-03):** Added `test_ui8_task3_safety_modes_diagnostics.py` with three offline tests using the real UI/TestRunner/Core path and SimulationHarness. They verify dry-run, actual same-run Trace ID and Block 8 timing data shown only in Diagnostic Mode, stale data clearing after a dispatch failure, M6-C fail-closed rejection before broker placement, and unchanged UI result/queue/order-log state when modes switch. Network and real-broker entry points are guarded; no live order was used. Reported result: **3 passed**. The unavailable/cross-clock application-side timing case did not occur in the real report and remains covered by UI-6 fixture tests, so it is explicitly not claimed as real-run proof. No production or other test file changed. Task 3 is complete; Task 4 is next. UI-8 remains in progress.

**UI-8 Task 4 completion record (2026-10-03) — Task 4 COMPLETE, UI-8 COMPLETE:** Task 4 re-checked the Task 1–3 tests against their recorded results and ran the required regressions fully offline. Actual results: UI-8 Tasks 1+2+3 → **6 passed** (exit 0); UI-1 + UI-2.1 → **27 passed** (exit 0); UI-3.1 whole file **timed out at 300 s** on its two known hangs `test_5_quantity_enter_and_store` and `test_extra_page_preserves_state_on_fractional_input`, and with exactly those two deselected → **30 passed, 2 deselected** (exit 0); UI-3.2A + UI-3.2B → **42 passed** (exit 0); UI-4 (nine files) → **89 passed** (exit 0); UI-5 (seven files) → **145 passed** (exit 0); UI-6 → **28 passed** (exit 0); UI-7 (three files) → **183 passed** (exit 0); M6-A…M6-D plus Block 8 tasks 8.2–8.5 → **135 passed, 2 failed** (exit 1). The two failures are the pre-existing Block 8 `broker_received_at` contract tests recorded earlier by UI-7 Task 4 and traceable to the 2026-09-30 commits `2459ece`/`3557c04`; they involve no UI-8 file and Block 8/Core are outside this decision's scope, so they remain an open, separately scoped repair rather than a waived check. No UI-8 defect was found: order/account/broker identity, fail-closed rejection of mixed destinations and of an unfunded BUY order at the real M6-C gate with zero broker placements, dry-run Test mode, Diagnostic-only technical data showing the same-run Trace ID and unmerged Block 8 timing categories, and unchanged UI-5/UI-7 behavior all hold over the real UI → TestRunner → Core → OrderEngine → simulation broker path. No M6/SafetyGate control was bypassed, every broker call used `live=False`, and no live order, credential, network access, or real broker was involved. Task 4 changed only these current status sections; no code, test, or configuration file was modified, and nothing was committed or pushed. UI-8 is COMPLETE; the roadmap continues with Central Server.

---

## Decision 029 — UI-9 Dark Theme, Two-Column Order Layout and Persian/RTL Localization

**Status:** Accepted and COMPLETE. UI-9.1, UI-9.2, UI-9.2b, UI-9.3 and UI-9.4 are COMPLETE and Architect-verified (2026-10-04). UI-9.5 (navigation polish, minimal empty-state, guard test and UI-9 closure) is now COMPLETED and verified in this session (2026-10-06). **UI-9 as a whole is COMPLETE.** The two long-standing modal-dialog hangs were fixed by UI-9.4; the old deselect flags used in earlier tasks are now obsolete.

**Decision:**
1. The User Application uses one dark theme, defined by tokens in `ui/theme.py` (palette, a 4/8/12/16/24 spacing scale, geometry) and applied from `create_app()` and `MainWindow`. PySide6 is kept; no framework change.
2. The Order page is split into two columns — order information and scheduling — with the tables (`Order Queue`, `Test Results`, `Order Log`) at the bottom, inside an inner `QScrollArea`.
3. The interface is fully Persian and right-to-left. RTL is applied **only** in `create_app()` (`ui/app.py`). The required column orientation is **RIGHT = order information, LEFT = scheduling**, and it is measured, not assumed.
4. Every user-facing string lives in `ui/strings.py` (single catalogue).
5. Digit policy: **LATIN** digits for the countdown and technical timestamps, **PERSIAN** digits for money, price and quantity, through one centralized formatter.
6. Placeholder and separator characters must be drawable by the chosen font: `-` (U+002D) is used instead of `—` (U+2014) and `→` (U+2192).

**Reason:** the Product Owner asked for a professional dark appearance, a clearer order page, and a fully Persian right-to-left interface — while explicitly keeping the order-send path unchanged.

**Constraints preserved:** no change to `core/order_engine.py`, `core/dispatch_core.py`, `core/safety_gate.py`, `ui/test_runner.py`, the logic of `ui/schedule_dispatcher.py`, or the `Plan → Dispatch → Broker` path. M6-A…M6-E remain authoritative; `live_trading_enabled` stays disabled; no new dependency was added; no font file is bundled into the repository.

**Verified (Architect, independent runs):** the mandated baseline → **310 passed, 2 deselected, EXIT=0**; all 30 `test_ui*.py` files → **563 passed, 2 deselected, EXIT=0** (the whole UI suite is green); an independent `QRawFont` audit found **0 missing-glyph characters** in NORMAL and DIAGNOSTIC mode. The two pre-existing Block 8 `broker_received_at` failures remain and are not part of UI-9.

**Recorded findings (verified, so they are not rediscovered):**
- **RTL and programmatic row selection:** with app-level `RightToLeft`, a `QTableWidget` that uses `setSelectionBehavior(SelectRows)` and was **created while RTL was already active** silently turns `selectRow()` into a no-op (`currentRow()` returns −1). **Real mouse clicks are unaffected** — verified on the real `AccountsPage` — and `setCurrentCell(row, 0)` works under RTL. No product behaviour was changed; the single affected test (`test_ui2_1_account_management.py::test_12`) now uses `setCurrentCell`, which was explicitly authorized.
- **Missing glyphs in IRANSansX:** U+2014 (`—`), U+2013, U+2010, U+2015, U+00B7, U+2022, U+2192 (`→`), tatweel and ZWNJ are absent and render as empty boxes; only U+002D (`-`) renders. All user-facing `—` and `→` were replaced. One U+2014 is kept on purpose in `ui/order_config_state.py`, inside a developer-facing exception message that never reaches a widget.

**Test-contract consequence:** tests that asserted English UI literals now import and assert the `ui/strings.py` constants (or `ui/user_log.EMPTY_CELL`), so they cannot go stale again. Test intent was preserved; no test was weakened or deleted.

**Consequences / limitations:** a machine without IRANSansX falls back through the font chain; the pre-existing Block 8 failures and the uncommitted `ui/test_runner.py` change remain open and separately scoped. Nothing was committed or pushed by the implementing agent — the checkpoint is completed by the Architect after review.

### UI-9.4 completion record (2026-10-04) — inline validation errors

**Delivered:** the six blocking `QMessageBox` calls were removed — three in `ui/order_configuration_page.py` (invalid side / price / quantity) and three in `ui/accounts_page.py` (invalid account ×2, no selection). Each page now shows one inline error label, styled from the theme's danger role (`#ef4444`) with all spacing taken from `ui/theme.py` tokens. The label is empty and hidden when there is no error — the layout item reports `isEmpty()==True` and the group box `sizeHint` is unchanged (Order 344 px, Accounts 184 px), so error-free layout is byte-for-byte the same as before. On a new error it shows the matching Persian `ui/strings.py` constant; on the next successful action it clears. No new string was added to the catalogue and no English text was introduced.

**Validation semantics unchanged:** the same conditions, in the same order, accept and reject exactly the same values. Only the display channel changed. `ui/theme.py` was left untouched (its two now-dead `QMessageBox` QSS rules were deliberately not removed).

**The modal-dialog hangs are resolved.** `test_ui3_1_order_configuration.py` now runs with **no deselection at all**: 32 passed, 0 deselected, `EXIT=0` — including `test_5_quantity_enter_and_store` and `test_extra_page_preserves_state_on_fractional_input`, which previously hung indefinitely and had to be deselected in every run since UI-7.

**Architect-verified results (independent runs):**
- the previously mandated baseline selection still reports **310 passed, 2 deselected, EXIT=0** (the two deselects are now redundant but harmless)
- **all 30 `test_ui*.py` files, with no deselection: 565 passed, 0 failed, 0 deselected, EXIT=0** — 565 = 563 + the two tests that were freed
- `QMessageBox` call sites in `ui/`: **none** (only comments and the dead QSS text remain)
- both Block 8 `broker_received_at` failures unchanged (pre-existing)
- exactly four files changed: the two product files and the two authorized test files. `ui/theme.py`, `ui/strings.py`, `core/*`, `ui/schedule_dispatcher.py` and `ui/test_runner.py` are untouched.

**Test updates (authorized):** `test_ui3_1_order_configuration.py::test_4_price_enter_and_store` and `test_ui2_1_account_management.py::test_11_accounts_page_creates_no_real_broker` no longer monkeypatch the removed `QMessageBox` seam; they assert the inline error label instead. Both keep their original intent and their other assertions intact. Test intent was preserved; nothing was weakened or deleted.

**Accepted limitation (Product Owner decision):** the inline message carries the Persian dialog-title constant (e.g. «قیمت نامعتبر») rather than the removed dialogs' English reason body (e.g. "Price must be an integer …"). The Product Owner reviewed this and accepted it as sufficiently clear for the user; surfacing the reason would require new Persian reason constants and is not part of UI-9.

**Housekeeping noted, not caused by this task:** `test_ui5_task3_feedback_service.py` is a 0-byte tracked file (0 bytes at HEAD too), so a whole-suite run reports `EXIT=5` / "no tests collected" for it. It is not a failure but it means a literal 30/30 `EXIT=0` gate is not meaningful until that file is either populated or removed.

### UI-9.5 completion record (2026-10-06) — navigation polish, minimal empty states, guard test, UI-9 closure

**Delivered:** the navigation sidebar is now a distinct panel (`QFrame#navPanel` — surface background + separating right edge) so it reads as navigation rather than as another page; the active entry is unambiguous (the existing `QPushButton:checked` accent rule plus a dedicated sidebar surface). The Home and Settings placeholder pages are now a **minimal** empty-state panel (`QFrame#panel` with a centred title and a muted Persian description) so the application's first screen (Home, which the app opens on) is not bare. The last user-visible English-ish placeholder text — the developer-note `PLACEHOLDER_PAGE_BODY` — was replaced with a Persian user-facing sentence in `ui/strings.py`. All colours, spacing, radii and font sizes come from `ui/theme.py` tokens; no magic numbers, no new hex.

**One new guard test added — the only new test file authorized by this task:** `test_ui9_task5_ui_polish.py` (offline, deterministic, own file-local `qapp` fixture). It asserts for the surfaces this task touches (the main window, its navigation, the placeholder pages) that (1) no displayed user-facing string is a hard-coded English literal — user-facing text comes from `ui/strings.py` — and (2) no displayed character lacks a glyph in the application font — checked against the real font file's cmap (fontTools, with a `pytest.skip` fallback when fontTools is not installed), where a missing codepoint means `.notdef` (the empty box). This is the automatic detection of the UI-9.3 missing-glyph defect class (`—` / `→` rendering as empty boxes), which had previously been found by eye only.

**Deferred (recorded, not done):** the real design and content of Home and Settings. They remain placeholders; the temporary empty-state added here is replaced when those pages are actually implemented. Investing a full design in them now would be wasted work.

**The old deselect flags are obsolete.** UI-9.4 fixed the two long-standing modal-dialog hangs (`test_5_quantity_enter_and_store`, `test_extra_page_preserves_state_on_fractional_input`), so `test_ui3_1_order_configuration.py` now runs with **no deselect flags at all**. Any earlier runbook that deselects them is stale.

**Architect-verified results (this session, actual runs):**
- pre-edit baseline (Step 1, before any edit): **565 passed, 0 failed, 0 deselected, EXIT=0**
- post-edit full 30-file sweep (Step 3, after edits): **565 passed, 0 failed, 0 deselected, EXIT=0** — no regression
- new guard test `test_ui9_task5_ui_polish.py`: **112 passed, 0 failed, EXIT=0** (0.46 s, own run)
- Block 8 pair (60 s cap, pre-existing): **EXIT=1, 2 failed** — unchanged, reported not claimed green
- structural invariants preserved (Step 3.3): `content_area.count() == 4`; `set(window.placeholder_pages) == {"Home", "Settings"}`; `pages[key] is placeholder_pages[key]` and `content_area.currentWidget() is placeholder_pages[key]` for both keys (and through navigation clicks); `set(window.nav_buttons) == {"Home", "Accounts", "Order Configuration", "Settings"}`; Order page C5 parents intact (`queue_list.parent().title() == GROUP_ORDER_QUEUE`, `result_list.parent().title() == GROUP_TEST_RESULTS`); `ui/test_runner.py` diff unchanged (pre-existing 23+/10−, verified via `git diff --numstat`).
- English sweep over `ui/`: **none found** on user-facing surfaces reachable from the main window / navigation / placeholder pages; every user-facing string there comes from `ui/strings.py`. Internal English (page keys, `ApplicationMode` enum values, developer-facing exception messages) is intentional and left in place.

**Files changed by this task:** `ui/theme.py` (add nav panel + empty-state panel token-driven rules), `ui/main_window.py` (nav area is now a `QFrame#navPanel`; placeholder pages are minimal centred panels; `QFrame`/`QSizePolicy` imports added), `ui/strings.py` (replace developer-note `PLACEHOLDER_PAGE_BODY` with Persian user-facing text), plus the new test file `test_ui9_task5_ui_polish.py`.

**Constraint C12 note:** `ui/theme.py` was modified only to add token-driven rules using the existing palette/spacing/radius tokens — no new hex, no magic numbers.

**Constraints preserved:** C1–C13 all hold. In particular: C2 (`ui/test_runner.py` untouched), C4 (page identities preserved — the placeholder widget class changed from `QLabel` to `QFrame` but every identity assertion still holds because no test asserts `QLabel`), C5 (Order-page parents intact), C6 (new test file imports nothing from `main`/`brokers.*`/`core.*`), C8 (Block 8 failures reported, not claimed green), C10 (no commit, no push), C11 (no user-facing English introduced), C13 (bound in 2.2 not exceeded).

**Screenshots (mandatory):** captured via the real application path — `ui_app.create_app([])` (which applies theme, font and RTL) — then `MainWindow` shown and grabbed. `photos/ui95_home.png`, `photos/ui95_settings.png`, `photos/ui95_navigation.png`. The offscreen font note was applied (`QFontDatabase.addApplicationFont(IRANSansX-Regular.ttf)` **after** the `QApplication` exists). Navigation-bar geometry verified programmatically: `nav.x=1091` on a 1280-wide window → sidebar is on the RIGHT under RTL. Empty-state geometry verified: labels are `Preferred/Fixed` (not stretched; `labels_full_width=False`), the title+description group is pulled to the vertical middle of the card by stretch above/below (1 above, 2 below).

**Known limitations:** a font file is not bundled, so a machine without IRANSansX falls back through the chain; the two pre-existing Block 8 `broker_received_at` failures and the pre-existing uncommitted `ui/test_runner.py` change remain open and separately scoped; `test_ui5_task3_feedback_service.py` is a 0-byte tracked file (0 bytes at HEAD), so a literal 30/30 `EXIT=0` gate is not meaningful until it is populated or removed.

**COMMIT / PUSH NOT DONE** — awaiting Architect review.

## Decision 030 — UI-10 Order page defaults, side colours and a live market clock

**Status:** Accepted and COMPLETE (delivered and verified in this session, 2026-10-06). Presentation and defaults only; no dispatch behaviour is implemented or changed, no validation rule changed, no order-send path touched.

**Recorded Product-Owner decision — the interval default is `1`, NOT `0`.** The Product Owner asked for a default schedule interval of 0 seconds, but the repository forbids it: `ui/schedule_settings.py::_parse_interval` rejects `seconds <= 0` because a zero gap would degenerate the schedule into a burst. That validation rule is NOT changed by this task. The burst requirement ("send like a burst every 100 ms") is delivered by the EXISTING `dispatch interval (ms)` field and `PeriodicScheduleDispatcher` (UI-7 Task 3); its default is now `100`. No new burst mechanism was built.

**Delivered (all on the Order Configuration page):**
1. **Side default + colours.** BUY is preselected at construction: the BUY radio is checked AND the side goes through the existing `config.set_side(BUY)` setter (never a direct attribute write), so `page.config.side == BUY` immediately after construction. The side text is colour-coded via new token-driven theme rules — `QRadioButton[variant="buy"]` → `success` (green خرید), `QRadioButton[variant="sell"]` → `danger` (red فروش). No new hex, no new tokens; keys, labels, `setCheckable` behaviour and the click→`config.side` path are unchanged.
2. **Live system clock row.** The «ساعت سیستم» row displays Windows system time converted to Tehran and updates once per second. It makes no network request and makes no claim about measured offset or in-app NTP synchronization.
3. **Schedule controls.** Manual refresh/sync buttons and their TSETMC status rows are absent. Apply/Stop, schedule state, countdown, and summary remain.
4. **Pre-filled schedule defaults.** `schedule_start_input = "08:44:58"`, `schedule_end_input = "08:45:05"`, `schedule_interval_input = "1"` (smallest legal value — see the decision above), `dispatch_interval_input = "100"`. All are real field values accepted by the existing validators unchanged.

**New strings (all in `ui/strings.py`, C11):** `LABEL_CLOCK_STATUS`, `CLOCK_PROGRAM_TIME_SUFFIX` (both Persian-only so the UI-9.5 English guard passes them).

**Constraints:** C1–C13 all hold. In particular C3 (the clock row makes no network call), C7 (attributes `schedule_timezone_label` and `clock_status_label` remain reachable, nothing renamed), C12 (`ui/theme.py` only gained the two variant rules using existing tokens), C13 (no existing test changed — the first pass broke 3 tests by eagerly creating the clock service at construction; the fix made the row lazy-safe rather than touching any test, and the full suite then passed).

**Verified (this session, actual runs, bounded runner):** pre-edit baseline **677 passed** (565+112), EXIT=0; post-edit full 31-file sweep **679 passed, 0 failed, EXIT=0** (the +2 are the guard test's two new parametrized Persian assertions for the new strings — no existing test changed); Block 8 pair 60 s cap **EXIT=1, 2 failed** (pre-existing, unchanged). Structural values: `config.side == BUY` and BUY checked at construction; SELL click still sets `config.side == SELL`; the four inputs read exactly `08:44:58 / 08:45:05 / 1 / 100`; the schedule form contains no duplicated row label; the clock row read twice ~2 s apart showed a changed second. Screenshots: `photos/ui10_order_buy_sell.png` (page with green خرید / red فروش), `photos/ui10_clock_schedule_rows.png` (clock row + pre-filled defaults).

**Out of scope, untouched:** dispatch behaviour and `PeriodicScheduleDispatcher`, `_parse_interval` (`0` stays illegal), `core/*`, `ui/test_runner.py` (still only its pre-existing 23+/10− uncommitted change), `ui/schedule_dispatcher.py`, every other page/row/colour.

**COMMIT / PUSH NOT DONE** — awaiting Architect review.


---

## Decision 031 — Per-Account Broker Runtime and Account-Page Authentication

**Status:** Accepted architectural direction (Product Owner confirmed on 2026-10-15). Phase 1 Tasks 1A (`9efb88e`) and 1B (`39bd0d6`) and Phase 2 Tasks 2A (`ccdd563`), 2B (`23802a7`) and 2C (`56a317b`) are complete within their documented scopes. Phase 3 Task 3A (`fbdc112`) establishes account display-name UI; Task 3B-1 (`e4a0796`) composes/injects lazy account services; Task 3B-2 (`f8764c0`) wires credential save/delete; Task 3B-3 (`c8ec626`) wires begin/cancel login and public challenge display. MainWindow shares its cached `BrokerManager` between AuthenticationService's adapter factory and TestRunner/DispatchCore. Phase 3 Task 3B-5 integrated offline UI acceptance was completed in commit 19d9558; trading-state, instrument identity and feedback still use name-only or separate-manager paths. The owner-approved Task 3B-1 through 3B-5 order is complete. Task 5 Stage 1, 2A, 2B and 2C.1/.2/.3a/.3b are complete; Task 5 Stage 3 offline integration/regression audit remains for formal closeout. After it is accepted, proceed to Task 9 account-aware routing. See AI_HANDOFF.md for the current bounded task.

## Completion Record — Block 9 Phase 3 Task 3B-1: Lazy service composition/injection — COMPLETE (2026-10-15)

- **Commit pushed:** `e4a0796` — `feat: inject lazy account services`.
- **Changed and committed files:** `ui/main_window.py`, `ui/accounts_page.py`, `test_block9_phase2_service_composition.py`.
- **Design:** MainWindow lazily caches one CredentialStore and one SessionManager; AuthenticationService uses those exact shared instances. AccountsPage accepts optional keyword-only service callbacks; MainWindow injects lazy lambdas without executing them during page/window construction. Construction failure does not cache an incomplete AuthenticationService.
- **Owner/agent-reported offline verification:** `python3 -m pytest -q test_block9_phase2_service_composition.py` → **4 passed**; account-management tests → **24 passed**; UI foundation + account-management tests → **37 passed**; focused AuthenticationService/Agah adapter/integration suite → **145 passed**. `py_compile` and targeted `git diff --check` succeeded. The agent environment did not have the Windows `py` launcher, so equivalent `python3` commands were used.
- **Final owner review:** only the three allowed Task 3B-1 files were staged and committed; cached diff check passed. The unrelated local `test_ui2_1_account_management.py` worktree marker had no content diff; `ui/test_runner.py` and other unrelated artifacts remained unstaged.
- **Scope boundary:** no credential/login UI action, real vault access, network request, broker login, or order was added/performed.


## Completion Record — Block 9 Phase 3 Task 3B-2: Credential save/delete UI — COMPLETE (2026-10-15)

- **Commit pushed:** `f8764c0` — `feat: add account credential management UI`.
- **Files:** `ui/accounts_page.py`, `ui/strings.py`, `test_ui2_1_account_management.py`.
- **Decision applied:** selected-row identity is the actual account ID plus the broker name stored in the account record. UI credential operations are explicit user actions routed only through the injected `CredentialStore`; no credential read-back, prefill, or page-construction vault action is allowed. Password entry remains masked, entered values are passed verbatim after blank-only validation, sensitive fields clear after save/delete attempts, and UI messages do not expose backend exception details.
- **Reviewed scope:** only the three allowlisted files were staged; `git diff --cached --check` passed. The unrelated local `ui/test_runner.py` modification and untracked artifacts were excluded from the commit.
- **Reported offline verification:** agent-reported account-management **33 passed**, UI-foundation + account-management **46 passed**, service-composition + CredentialStore **68 passed, 7 skipped**, with compilation and scoped diff checks passing. These results were reported by the implementation agent using `python3`; no claim is made that the owner reran them locally.
- **Safety:** no real vault access, broker login, CAPTCHA request, network request or order was performed.
- **Next bounded task:** Task 3B-4 — complete login, local logout and per-account status. See `AI_HANDOFF.md`; account-bound trading-state, instrument identity, dispatch and feedback routing remain outside this task.


## Completion Record — Block 9 Phase 3 Task 3B-3: Begin/cancel login and generic challenge display — COMPLETE (2026-10-16)

- **Commit pushed:** `c8ec626` — `feat: add account login challenge UI`.
- **Files:** `ui/accounts_page.py`, `ui/strings.py`, `test_ui2_1_account_management.py`.
- **Accepted behavior:** Login begins only on explicit user action using the selected row's real account ID and the injected AuthenticationService; challenge images are Base64-decoded and validated; bad, missing or unsupported challenge content fails closed. Cancellation and cleanup call `cancel_login(pending_account_id)` for the original attempt rather than the selected row.
- **Owner-reported final offline verification:** account-management **37 passed**; UI foundation + account-management **50 passed**; service-composition/authentication/Agah-adapter/integration **149 passed**; `py_compile` passed. Used `python3` because `py -3` was unavailable in the test environment.
- **Final git evidence:** exactly the three allowed files staged; cached `git diff --cached --check` passed; commit `c8ec626` pushed successfully from `8bb7f54`.
- **Safety:** no real credential, vault, broker/network login, CAPTCHA endpoint or order was used. Complete login, logout and status remain for Task 3B-4.

### Accounts-page integration execution order — accepted by Product Owner (2026-10-15)

**Owner-approved Task 3B implementation order (2026-10-15):** The Product Owner accepted the following sequence. Acceptance applies to the order of work; each implementation task still requires an Architect-defined allowlist, exact acceptance criteria, and review before the next task starts.

1. **Task 3B-1 — Lazy service composition/injection and offline construction tests.** Provide AccountsPage with controlled/lazy access to the already-composed shared services without triggering service, vault, network, or login work during MainWindow/AccountsPage construction. No credential/login UI actions in this task.
2. **Task 3B-2 — Credential save/delete UI.** Wire explicit user-triggered save/delete via CredentialStore; cover success, missing credential, validation/backend failures, and secret non-disclosure with fake in-memory backends.
3. **Task 3B-3 — Begin/cancel login and generic challenge display.** Use AuthenticationService and its public LoginChallenge contract; display the challenge only when returned, keep broker-specific CAPTCHA details inside the adapter, and test with fakes.
4. **Task 3B-4 — Complete login, local logout, and per-account status.** Confirm status from public service APIs; prove state and UI for one account cannot change another account using at least two fake accounts on the same broker.
5. **Task 3B-5 — Integrated offline UX acceptance.** Verify the entire credential → challenge → response → status flow, offline construction, and regressions. No real vault/network/login/order is allowed.

**Rules for all five tasks:** implement in sequence; Architect reviews each report/diff before the next task starts; each task gets its own exact allowed-file list and focused test commands; never stage broadly or touch unrelated local work; keep account-bound trading-state, instrument identity, order routing, NATS/queue-position, and feedback fixes in the separate later phase. The current approval does not itself authorize implementation outside the individually issued task. Preserve the existing dark RTL direction and do not perform a broad redesign without separate approval.

### Decision

Each local application account must have a fully independent authenticated broker runtime, even when many accounts use the same broker. The Accounts page is the user's entry point for account login/logout and per-account status.

The authoritative runtime identity is the pair `(account_id, broker_name)`. `AccountStore` currently requires `account_id` to be unique in the local application; retaining the pair as the runtime key also makes broker association explicit and prevents accidental cross-account reuse.

### Required ownership and wiring

1. The existing `BrokerManager` / provider registry is to be extended to resolve account-owned instances, rather than introducing a parallel order-dispatch path. Its account-aware contract must provide a broker and its matching instrument provider by `(account_id, broker_name)`. Each pair receives its own broker object, HTTP session, in-memory access/refresh token state, authentication adapter/recovery handler, and provider/cache. These objects must never be shared between two account IDs, even if both use `آگاه`.
2. The `AuthenticationService` adapter factory must use the same account-owned broker instance managed by that registry. Authentication/recovery and order dispatch may not create separate instances for the same account, nor may a name-only broker lookup be used as a fallback for account-bound work.
3. The application composition layer (the existing `MainWindow` / application wiring boundary) creates the account, credential, session, authentication and broker-management services once and injects them into consumers. The `AccountsPage` calls those services and renders status; it does not instantiate brokers, manage tokens itself, or implement broker-specific authentication.
4. `AccountsPage` is the integration point for adding/selecting accounts and for per-account login/logout/status. Credentials continue to be stored only through `CredentialStore` in the OS secure vault. CAPTCHA/login behavior remains behind the broker's existing authentication adapter. The current authenticated-session contract needs a public, fail-closed per-account logout operation before the UI can wire logout.
5. The active account determines which account a new UI order belongs to; changing the active selection must not log out, overwrite or otherwise change other accounts. Before order preparation/execution, the application must require the selected account to be logged in with a usable account-owned runtime.
6. The existing order execution chain remains authoritative: account binding from the plan is preserved and resolved to the matching account-owned broker/provider, then execution continues through `DispatchCore → OrderEngine → M6-A…M6-E`. No duplicate dispatch path, core-side broker-specific authentication logic, account re-selection, or live-trading enablement is permitted.
7. Any instrument resolution, trading-state query, queue-position/NATS transport and order-feedback listener used for an account must be bound to that same account-owned broker/provider. Feedback from one account must not be attributed to another account's order.

### Fail-closed rules

- An unknown account, broker mismatch, missing login/session, missing account-owned broker, or inconsistent runtime must stop that operation. No default account, broker-only fallback, or shared authenticated broker may be substituted.
- HTTP 401 recovery remains bounded and account-scoped. It must update the token/session view belonging to that same account; `POST /order` must never be automatically replayed after 401.
- Credentials remain in the OS vault. Access/refresh tokens and authenticated HTTP state stay in memory for their own account only.
- Live trading stays disabled during these tasks. Use fake/offline HTTP sessions and deterministic tests only.

### Required acceptance evidence

Tests must use at least two distinct accounts on the same broker and prove:
- each account gets a distinct broker object, HTTP session, provider instance/cache, token state and recovery handler;
- login, refresh, logout, recovery failure and account switching for one account do not mutate another;
- an order's explicit `account_id` resolves to that account's exact broker/provider through the existing dispatch chain;
- stale/missing account runtime fails closed;
- instrument lookup and order-feedback/queue-position events remain account-correct;
- the existing M6-A…M6-E gates remain active and no `POST /order` retry occurs;
- all network-sensitive tests are fake/offline and no real order is sent.

### Scope boundary and execution order

This decision records the architecture only; no implementation or UI redesign is authorized by this record itself. Before implementation, the Accounts-page visual/UX proposal must follow the existing roadmap approval gate. Then split the work into small stages: (1) lock the account-aware manager/service contracts and public logout lifecycle, (2) compose and inject the services, (3) connect account-row login/logout/status/CAPTCHA behavior, (4) route identity, trading-state, instrument provider, dispatch and feedback by account, and (5) run focused then broad regression. Each stage must identify exact allowed files and acceptance tests before an agent starts.

**Roadmap naming note:** this is subtask 9, “Account-Aware Order Routing,” under Block 9 — Account & Session Management. It is distinct from the separate simulation/stress roadmap whose existing tests are named `test_block9_task9_1.py` through `test_block9_task9_7.py`; do not merge their scopes.

---


\## Decision 017 — Account UI Status Is Not Order Authorization

\*\*Status:\*\* Accepted

Phase 3 account-page status is an informational view of the public per-account AuthenticationService state. It does not, by itself, gate order submission or prove the entire broker route is production-ready. Active-account, logged-in-session and usable-session enforcement belongs to the separate account-bound routing phase.

\### Reason

UI completion and offline acceptance must not be mistaken for production order gating. Keep account authentication isolated, fail closed when account/runtime identity cannot be verified, preserve the existing `DispatchCore → OrderEngine → M6-A…M6-E` chain, and never automatically replay `POST /order` after HTTP 401.

---

## Decision 032 — Persist Non-sensitive Account Metadata Locally with SQLite

**Status:** Accepted and implemented (2026-10-17; code commit `fa3e6ad`).

**Decision:**

The production `AccountStore` persists account metadata and user-defined order in a local SQLite database. On Windows the default path is `%LOCALAPPDATA%\Trading Bot\accounts.db`. If `LOCALAPPDATA` is unavailable, the path falls back to `XDG_DATA_HOME/Trading Bot/accounts.db`, or `~/.local/share/Trading Bot/accounts.db`.

Only `account_id`, `broker_name`, `display_name`, and `position` are persisted. Username and password remain exclusively in `CredentialStore` backed by the operating-system credential vault; they are not written to SQLite or ordinary files. Active-account selection, login status, sessions, access tokens, and refresh tokens remain in memory and are never restored from the database.

The implementation uses Python's standard-library `sqlite3`; repository paths can be injected so tests use temporary databases. Repository changes are committed before corresponding in-memory state is changed. Delete/move/reorder operations resequence positions within one SQLite transaction; temporary positions are calculated from the existing maximum to avoid collisions with the `UNIQUE(position)` constraint. Errors exposed to callers use generic messages without database values or secrets.

This decision supersedes only the in-memory-only persistence detail recorded in Decision 024. The existing `models.account.Account` domain model, broker association in `AccountRecord`, active-account selection rule, OS-vault credential boundary, and broker-independent order architecture remain unchanged.

**Verification recorded:** the owner ran the four focused repository/persistence/account-management/UI-foundation test files with `LOCALAPPDATA` and `XDG_DATA_HOME` directed to a temporary directory: **67 passed in 4.06s**. The real user database was not touched. This is focused verification, not a claim that the entire repository regression suite is green.

**Reason:** account metadata and display order should survive application restarts without persisting secrets or authenticated runtime state, and the persistence implementation must remain testable without touching a user's real database.


---

## Decision 033 — Accounts Page Redesign and CAPTCHA Dialog

**Status:** Accepted and implemented (2026-10-17; code commit `f8d564f`).

**Decision:**

The approved Accounts-page redesign uses a right-to-left account-management view with a unified add-account form. The application generates each internal account ID; users provide a display name, select an available broker, and enter credentials. Account metadata and ordering continue through `AccountStore`; credentials continue through `CredentialStore` and the operating-system credential vault. Credentials must not be written to SQLite or ordinary files.

The page distinguishes active-account selection from login status and provides account-scoped row actions for activation, login/logout, editing, deletion, and manual ordering where available. The page delegates authentication to the existing `AuthenticationService`; it must not implement broker-specific login/token handling or introduce another order path.

A CAPTCHA dialog is shown only when the public authentication contract returns a valid image challenge. The Base64 payload and image are validated before display. The challenge is presented in an RTL modal `QDialog`; when a returned challenge is invalid, the UI attempts to cancel that pending login and retains generic, non-sensitive error reporting. An unsuccessful cleanup attempt must not expose provider details.

This is a UI/presentation decision and does not change SQLite persistence semantics in Decision 032, per-account session ownership, order authorization, the existing `DispatchCore → OrderEngine → M6-A…M6-E` chain, or live-trading policy.

**Verification recorded:** the focused offline suites passed: `test_ui2_1_account_management.py` **49 passed**, `test_block9_phase3_accounts_ui_integration.py` **2 passed**, and `test_block9_phase2_service_composition.py` **4 passed** (55 total). `py_compile` and the relevant diff checks were reported successful. This is focused UI verification, not a claim that the full repository regression suite is green.

---
 
## Decision 034 — Fail-Closed UI Order Authorization Gate

**Status:** Accepted and implemented (2026-10-17; code commit `503f6f6`).

**Decision:**

The order-configuration UI must deny queue insertion and Test/run execution unless the selected active account is valid and has a usable, account-matched authenticated session. The gate verifies the active account ID and broker, AuthenticationService's logged-in state, SessionManager's `LOGGED_IN` state and non-empty local token, the account's authenticated adapter, the adapter broker identity, and exact equality between the SessionManager token and the adapter's authenticated-session token. Missing services, inconsistent identity or token state, or exceptions deny the operation with a controlled non-sensitive result.

Authorization is a local validation step only. It does not start login, perform network access, refresh tokens, or mutate authentication/session state. It must remain broker-independent and must not add a parallel execution path. The existing `DispatchCore → OrderEngine → M6-A…M6-E` chain stays authoritative; Test remains dry-run (`live=False`); live trading remains disabled. Never automatically replay `POST /order` after HTTP 401.

**Implementation and verification:** commit `503f6f6` adds the authorization gate and focused offline tests. The standalone gate suite reported **4 passed**; UI-6 reported **28 passed**. The focused gate + UI-4/UI-5/UI-6 selection reported **107 passed, 26 failed**; all 26 remaining failures were reproduced on baseline and concern the out-of-scope `BrokerManager._account_lock` initialization issue. The full repository run reported **1595 passed, 233 failed, 20 skipped, 4 errors**; the repository-wide regression is not green, and existing errors include missing `nats` and a platform-specific `ctypes.WinDLL` collection failure. Relevant `py_compile` succeeded; the staged task diff's CR-at-EOL-aware whitespace check was clean.

This decision records a UI authorization boundary; it does not claim that all repository regressions are fixed or that account-aware feedback is complete.

---

## Decision 035 — Account-Scoped Order Feedback Runtime and Lifecycle

**Status:** Implemented and accepted at scoped level (2026-10-18; code commit `9ad15d435c2dc12eb3d95ba3f3ead071f6884e80`). Broader local-application regression/final acceptance remains the next phase.

**Decision / contract:**

- A feedback runtime is identified by `(account_id, broker_name)`, not broker name alone.
- Resolve the broker through `BrokerManager.get_for_account(account_id, broker_name)`; do not use a name-only/global broker lookup for account feedback.
- Runtime creation and startup fail closed when account identity or a usable authorized session is missing.
- Broker listener installation is idempotent. A stop/start cycle reuses the cached runtime and must not duplicate listeners.
- Feedback for `AcceptedByBourse`, queue position, or an order error may update only the originating account's matching order row. Identical decision IDs across accounts remain isolated; unknown and cross-account events are no-ops.
- Logout, account deletion, and broker change stop only the affected account runtime. Merely switching the active account must not stop another account's runtime.
- The feedback service is not an order dispatcher and must never send orders.

This decision does not alter the existing order authorization gate or the `DispatchCore → OrderEngine → M6-A…M6-E` execution/preflight chain. Test remains dry-run (`live=False`); live trading stays disabled.

**Scoped verification:** the focused command
```powershell
python -m pytest -q test_block9_account_aware_order_feedback.py test_ui5_task4_stage3_task3_core_registration.py test_ui5_task4_stage3_task4_ui_table.py
```
reported **56 passed in 6.09s, exit 0**. The implementation's scoped acceptance is complete; do not require further Task 9B changes without a reproducible in-scope defect.

**Owner-run manual local-app acceptance (2026-10-18):** two accounts on the same broker both logged in; activating either selected that account for current use while the other remained inactive; logging out one account did not disturb the other; logging the exited account back in succeeded and the other account remained normal. No issue was observed. This check covered account login/logout/re-login only; no order was submitted and live trading remains disabled.

**Next gate:** broader regression and final acceptance of the local User Application. A prior coding-agent report recorded 57 passed / 9 failed, attributed to missing `nats`, and described one UI-7 failure as baseline; these remain reported historical observations until verified/classified in the broader run. This is not a claim that the full repository suite is green. Central Server remains outside the scope of this acceptance phase.

---

## Decision 036 — Explicit Execution Mode, Frozen Dispatch Snapshot, Optional NATS Feedback

**Status:** Implemented in working tree; scoped offline verification pending.

**Decision / contract:**

- Every new page/session starts in Dry Run. Live selection is explicit and requires a per-action confirmation displaying the exact account/broker, queue size, schedule window/cadence, planned turns, and total possible submissions.
- The existing `SafetyGate` remains the only live-permission authority at `DispatchCore`; OrderEngine and broker locks remain independent. The UI may not set a live flag or enable a broker lock directly.
- Current production readiness is incomplete: there is no authoritative M6/broker readiness provider, and AgaahBroker's `live_trading_enabled` defaults to `False`. Live therefore fails closed before dispatch until those real prerequisites are supplied. The active account/session authorization and account-scoped broker resolution are checked using existing services; neither substitutes for the missing SafetyGate inputs.
- A schedule freezes its exact target entries, accounts, brokers, mode, and timing. After Live confirmation, active account and queue identity are rechecked; a changed snapshot is not started and requires a fresh summary/confirmation. Account switching elsewhere cannot retarget an active schedule.
- Every scheduled turn resubmits the complete frozen queue. The UI reports the maximum possible sends as `planned turns × frozen order count`. Stop prevents future turns; it does not claim to cancel sends already handed to the existing path.
- NATS/OMS is an optional receive-only feedback channel. Bootstrap failure, timeout, or later disconnect only marks feedback unavailable with `بازخورد از سازمان بورس دریافت نشده`; it never changes Live permission, pauses/stops scheduling, modifies the initial HTTP result, or causes POST replay. HTTP send results and delayed OMS feedback remain separate. Correlation remains decision-ID/account scoped.

**Verification boundary:** all new tests use local fakes/mocks. No live broker endpoint or `POST /order` is used. Live behavior can be exercised only with explicit simulated readiness and a SafetyGate; production remains blocked until its missing readiness contracts are provided.

---

## Decision 037 — Pre-Armed Scheduled Live Dispatch

**Status:** Approved; implementation in progress. Tasks 11.1, 11.3 and the Task 11.3 M6-validity correction are complete within their offline/core contract scope. Tasks 11.4–11.7 remain open.

**Context:** Block 10 established a controlled Live boundary and simulation-only acceptance. Production remains fail-closed. The current UI schedule re-enters the runner per due turn; `execute_by_ins_code()` resolves the instrument on the execution path, and `OrderEngine.prepare()` performs trading-state and capacity reads. This adds variable work at the firing instant and does not meet the owner's requirement to queue orders, apply a schedule, and complete checks before countdown/firing.

**Decision:** Introduce Block 11 as a targeted `PREPARE/ARM → FIRE → OBSERVE` lifecycle. Apply freezes a batch and performs account/session/readiness checks, instrument resolution, M6-A…M6-E checks, payload construction, SafetyGate evaluation, and explicit approval before countdown starts. The resulting prepared orders and authorization are immutable and bound to the exact account, broker, payload, schedule window, repetition count, and M6 evidence. A complete successful M6 result is valid for that one execution snapshot through its schedule end; no source-specific M6 TTL is required and no M6 network check is repeated at firing. Failed, mutated, mismatched, or late preparation disarms the batch; it never performs recovery work at the firing instant.

At each due time, prestarted senders release only the already-prepared payloads using monotonic schedule timing. The firing path does no database access, instrument resolution, M6/readiness HTTP call, credential refresh, modal interaction, or new worker-pool construction. It does not wait for earlier HTTP responses or NATS feedback. Initial HTTP results and delayed NATS events are processed asynchronously and correlated to the exact order/account. No automatic POST retry/replay is allowed.

**Safety and freshness:** M6-A…M6-E are not weakened; they remain the authoritative per-order checks but execute before the batch is armed. The owner-approved M6 validity rule is execution-scoped: the full successful evidence, completion time and execution identity are frozen into the prepared order and batch snapshot and remain valid until that snapshot's schedule end. A new scheduled execution requires fresh M6 preparation and a different execution identity. A local snapshot/account/session/window check may disarm at firing time but must never perform a network M6 refresh then. If evidence is incomplete, unsuccessful, duplicated, mismatched, or the snapshot changes, nothing is sent. The broker remains the final authority to accept/reject an order.

**Task 11.1 owner decisions (2026-10-23):** Each queued order and its locally known session remain bound to that order's account and broker through one scheduled run; only accounts used by queued orders must be logged in. Changing the UI active account alone does not change destinations or disarm the run. Local logout, invalidation, deletion, broker change, or session change for a destination account disarms it. Queue/order specifications remain frozen from Apply until completion; changes require a fresh Apply. No network probe is added for remote session validity. The user checks displayed purchase power and market price bounds before Apply, so the scheduler does not re-fetch those display values as freshness checks. This does not waive mandatory M6/SafetyGate work, which remains a pre-arm responsibility of later tasks. Every planned turn resends the whole frozen queue, and the maximum submission count must be shown as planned turns multiplied by queue size. Incomplete, failed, changed, or late preparation disarms and sends nothing.

**Task 11.1 implementation stages (2026-10-23):** Destination readiness and account-bound multi-destination dispatch are implemented. The schedule validates only destination accounts in the frozen queue; the dispatcher groups by `(account_id, broker_name)` and sends each group through its pre-resolved Account. Same-turn groups fan out without waiting for earlier HTTP responses. This does not implement prepared-order/submit separation or enable production Live.

**Task 11.2 implementation checkpoint (2026-10-23):** Added immutable `PreparedOrder` / `PreparedBatch` results and an additive broker `submit_prepared_order(payload)` capability. Preparation resolves the instrument, runs the full side-specific M6-A…M6-E checks, captures source/time/duration evidence, and builds the payload once. Submission accepts only the exact unchanged order, account, broker, payload, and evidence; batch preparation is all-or-nothing. The existing `place_order(order)` contract and behavior are unchanged. Reported offline verification: **15 targeted tests passed** and `py_compile` succeeded; no real endpoint/order was used.

**Task 11.3 implementation checkpoint (2026-10-24):** Added the immutable `LiveBatchAuthorization` / snapshot model and an evidence-based batch readiness API. It binds queue-entry/order identity and specification, prepared payload and M6 evidence/completion time/execution identity, every destination Account and local session generation/token fingerprint, the resolved account-scoped broker instance/capability, schedule window/cadence/planned turns, and `max_submissions = planned_turns × order_count`. Multi-account authorization checks each destination independently and does not require the UI active account to match every order. The aggregate M6 and broker contract values are derived only after every prepared item and destination passes actual validation; no generic `READY`/`ACTIVE` status or broker lock is manufactured. Before use, callers must recapture and compare the complete current snapshot; `submit_prepared_order(..., live=True)` rejects missing authorization, stale/mismatched scope, and does not rerun M6/network checks. A thread-safe per-authorization ledger claims each attempt before broker hand-off and enforces both the maximum total submission count and each order's planned-turn limit, preventing an ambiguous claimed attempt from being retried under the same permit. Legacy `place_order(order)` and Dry Run behavior are preserved. Focused offline verification: **40 tests passed** across Task 11.3, prepared-order, authorization, Live-readiness, and destination-dispatch suites; relevant `py_compile` passed. Additional Block 10 dispatch tests reported **12 failures** before reaching changed code because the existing `SimulationHarness` fixture constructs `BrokerManager` without `_account_lock`; 10 tests in that selection passed. No real network or order was used. The production `PREPARED_SOURCE_TTLS` remains empty and is no longer an acceptance prerequisite: authorization expiry is exactly the schedule end. Task 11.4 must wire pre-arm/countdown, supply a unique execution identity, create one ledger per run, and pass the recaptured current snapshot at firing; Task 11.5 remains responsible for the low-latency worker/dispatcher path.

**M6 execution validity:** No source-specific TTL is required for M6 evidence in a scheduled execution. `PreparedOrder` records complete successful gate evidence, source timestamps, completion time and a unique execution identity. Authorization binds these records to the exact queue/payload/destination snapshot and expires at `ScheduleSnapshot.end`; local validation during that same execution checks the frozen evidence and snapshot without refreshing M6 or comparing speculative source TTLs. A fresh run has a distinct execution identity and must perform M6 preparation again. This policy does not enable a broker Live lock or change SafetyGate.

**Repeated dispatch:** Existing schedule semantics send the full frozen queue every planned turn. Live UI must show the exact maximum number of submissions (`planned turns × queue size`). Pre-arm must validate aggregate repeated exposure according to the broker contract; if that cannot be safely established, Live repetition is rejected. No implicit deduplication is assumed.

**Latency objective:** Remove avoidable application work between scheduled due time and POST initiation. Measure schedule due time, scheduler wake/release, POST initiation, HTTP response, and NATS feedback separately. Do not claim zero end-to-end latency; Windows scheduling, network transit, and broker processing remain outside full application control.

**Scope:** Block 11 supersedes Block 10's original exclusion of schedule/M6 lifecycle redesign only for the pre-armed scheduled-Live lifecycle. It does not redesign unrelated Block 5–9 capabilities, weaken account authorization, bypass SafetyGate/M6, or enable a global broker lock from UI code.

**Tasks:**
1. **11.1 Firing contract and freshness policy** — define schedule start/deadline, repetition semantics, maximum submission count, data freshness by source, invalidation, and disarm behavior.
2. **11.2 Prepared order / submit separation** — produce immutable prepared orders from instrument resolution and M6-A…M6-E; submission consumes only a matching, unexpired prepared result.
3. **11.3 Live readiness and batch-scoped authorization** — connect only verifiable account/session and broker capability evidence; aggregate actual M6 results; bind approval to the frozen batch and maximum submissions; never invent READY statuses or toggle a global broker lock from UI.
4. **11.4 Pre-arm workflow and countdown** — Apply freezes and prepares the batch; countdown starts only after all checks and approval; failures/staleness/deadline miss disarm without late sends.
5. **11.5 Low-latency fire path** — prestart workers/connections; release prepared submissions at each due time without serial response waits; verify transport concurrency and account isolation; no retries.
6. **11.6 Latency instrumentation and offline verification** — measure due/wake/release/POST/HTTP/NATS separately; prove the hot path performs no preparation; test with fakes/mocks only.
7. **11.7 Controlled owner-run Live qualification** — after review, document one owner-operated single-order/single-turn qualification; do not send real orders in implementation or automated tests. Burst repetition requires separate owner acceptance of maximum exposure.

**Acceptance boundary:** Each task is accepted on offline tests and review. Production readiness is not claimed until Tasks 11.1–11.6 are complete. Task 11.7 is owner-operated and requires explicit owner action; the coding agent never sends a real order.
