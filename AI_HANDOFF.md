\# Trading Bot — AI Handoff



\## Purpose



This file is the current handoff document for any AI assistant or coding agent taking over the Trading Bot project.



It must always describe the current project state, the last completed work, known issues, and the next intended step.



\---



\# 1. Current Project State



The project is an actively developed Python trading bot for the Iranian stock market.



The project is currently in the \*\*development and API-integration stage\*\*.



It is \*\*NOT production-ready\*\*.



Real trading must not be enabled casually.



\---



\# 2. Repository State



Local Git repository has been initialized.



Current branch:



```text

master

```



Baseline commit:



```text

f600a6c

Initial project baseline

```



The baseline contains the working project before the project documentation layer was added.



\---



\# 3. Documentation Layer



The project documentation system is currently being established.



Files already created:



```text

AI\\\_PROJECT\\\_MEMORY.md

PROJECT\\\_CONTEXT.md

ARCHITECTURE.md

```



Files still to create:



```text

DECISIONS.md

AGENT\\\_RULES.md

BUG\\\_HISTORY.md

```



After all documentation files are created and reviewed, they should be committed together.



\---



\# 4. Current Repository Structure



```text

Trading\\\_bot/

│

├── main.py

│

├── brokers/

│   ├── \\\_\\\_init\\\_\\\_.py

│   ├── agaah.py

│   ├── base.py

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

│   ├── symbol\\\_resolver.py

│   └── tsetmc.py

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



\---



\# 5. Existing Functionality



The project currently contains initial implementations for:



\* TSETMC symbol search.

\* Instrument resolution.

\* Persian/Arabic symbol normalization.

\* Windows Persian keyboard-layout handling.

\* Broker abstraction.

\* Agah broker integration.

\* Device information handling.

\* Account model.

\* Instrument model.

\* Broker instrument model.

\* Order model.

\* Order validation.

\* Order engine.

\* Agah API tests.

\* TSETMC-to-Agah mapping tests.

\* Order-building tests.

\* Dry-run tests.



\---



\# 6. Agah API Investigation



Agah is the current primary broker being integrated.



Known API base:



```text

https://tseonlineapi.agah.com/api/v1

```



Known areas investigated:



```text

Authentication

Captcha

Financial accounts / balances

Instrument information

Live segmentation

Market indexes

Order submission

Live order decisions

```



Important unresolved areas:



```text

TSETMC insCode → Agah nscId mapping

categoryId

clientKey

deviceInfo generation

exact tradability/order-entry state

production-safe order status handling

```



These must be investigated and verified.



Do not invent missing API behavior.



\---



\# 7. TSETMC



TSETMC is used for market and instrument discovery.



Known search endpoint:



```text

https://cdn.tsetmc.com/api/Instrument/GetInstrumentSearch/{query}

```



Previously tested symbol:



```text

آکو

آكو

```



Example instrument:



```text

Symbol: آكو

Name: آكو باتري ايرانيان

ISIN: IRO1ACCO0001

TSETMC insCode: 60235881999727383

```



\---



\# 8. Current Architectural Direction



The core architecture should remain:



```text

UI

\&#x20;↓

Application / Core

\&#x20;↓

Broker Interface

\&#x20;↓

Broker Adapter

\&#x20;↓

Broker API

```



Market data:



```text

UI

\&#x20;↓

Symbol Resolver

\&#x20;↓

TSETMC

\&#x20;↓

Instrument

\&#x20;↓

Broker Mapping

```



The core must remain broker-independent.



\---



\# 9. Important Development Rules



Any coding agent taking over this project must:



1\. Inspect the repository before modifying code.

2\. Read all project documentation before architectural changes.

3\. Check whether functionality already exists.

4\. Avoid unnecessary refactoring.

5\. Preserve working behavior.

6\. Keep broker-specific code inside broker adapters.

7\. Never hardcode secrets.

8\. Never submit real orders during ordinary testing.

9\. Prefer dry-run tests.

10\. Run relevant tests after changes.

11\. Fix root causes rather than hiding errors.

12\. Document significant architectural decisions.

13\. Report changed files and test results.

14\. Do not assume undocumented broker API behavior.



\---



\# 10. Security



Never commit:



\* username/password

\* access token

\* refresh token

\* cookies

\* captcha information

\* private API keys

\* authentication headers containing secrets



The repository `.gitignore` already excludes:



```text

captcha.png

client\\\_id.txt

.env

.env.\\\*

```



\---



\# 11. User's Development Model



The intended workflow is:



```text

User

\&#x20; ↓

Product decisions / real-world testing

\&#x20; ↓

AI Architect / Technical Advisor

\&#x20; ↓

Coding Agent

\&#x20; ↓

Local repository

\&#x20; ↓

Git

```



The AI coding agent is an implementation worker, not the owner of the architecture.



The project must remain understandable even if the current AI assistant or coding agent is replaced.



\---



\# 12. Agent Replacement Strategy



This project must support switching between AI tools.



Possible agents include:



```text

ChatGPT

Genspark

Claude

Codex

Cline

Roo Code

Other coding agents

```



A new agent should be able to start from the repository itself.



Required first-read files:



```text

AI\\\_PROJECT\\\_MEMORY.md

PROJECT\\\_CONTEXT.md

ARCHITECTURE.md

DECISIONS.md

AGENT\\\_RULES.md

AI\\\_HANDOFF.md

BUG\\\_HISTORY.md

```



\---



\# 13. Last Completed Work



The following work has just been completed:



1\. Git for Windows was installed.

2\. Git repository was initialized.

3\. `.gitignore` was created.

4\. Initial project baseline was committed.

5\. Baseline commit:



```text

f600a6c

Initial project baseline

```



6\. Project memory documentation was started.

7\. `AI\\\_PROJECT\\\_MEMORY.md` was created.

8\. `PROJECT\\\_CONTEXT.md` was created.

9\. `ARCHITECTURE.md` was created.



\---



\# 14. Current Immediate Task



Complete the project documentation layer.



Next files:



```text

DECISIONS.md

AGENT\\\_RULES.md

BUG\\\_HISTORY.md

```



Then:



1\. Review documentation.

2\. Stage documentation files.

3\. Create a documentation commit.

4\. Verify Git status.

5\. Prepare a private GitHub repository.

6\. Push the local repository to GitHub.

7\. Configure the selected AI coding agent.

8\. Continue development from the repository.



\---



\# 15. Important Handoff Instruction



The next AI agent must not immediately start rewriting code.



First:



```text

Read documentation

\&#x20;    ↓

Inspect repository

\&#x20;    ↓

Check Git status

\&#x20;    ↓

Understand current architecture

\&#x20;    ↓

Understand current task

\&#x20;    ↓

Only then modify code

```



If the requested task conflicts with an architectural decision, stop and explain the conflict before making a major architectural change.



\---



\# 16. Current Next Step



Create:



```text

DECISIONS.md

```



Then create:



```text

AGENT\\\_RULES.md

BUG\\\_HISTORY.md

```



After that, commit the complete documentation layer.



The repository should then be ready for GitHub backup and AI-agent handoff.

