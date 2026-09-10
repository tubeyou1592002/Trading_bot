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