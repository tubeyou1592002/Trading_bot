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