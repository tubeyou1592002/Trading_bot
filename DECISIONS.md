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



