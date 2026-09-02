\# Trading Bot — AI Agent Rules



These rules apply to every AI coding agent working on this repository.



\---



\## 1. Inspect Before Editing



Never modify project files immediately after receiving a task.



First inspect:



\* repository structure

\* relevant source files

\* tests

\* Git status

\* project documentation



\---



\## 2. Read Project Documentation



Before significant work, read:



```text

AI\\\_PROJECT\\\_MEMORY.md

PROJECT\\\_CONTEXT.md

ARCHITECTURE.md

DECISIONS.md

AI\\\_HANDOFF.md

BUG\\\_HISTORY.md

```



If a file does not exist yet, do not invent its contents.



\---



\## 3. Check Existing Functionality



Before creating a new class, function, module or file:



1\. Search the repository.

2\. Determine whether equivalent functionality already exists.

3\. Reuse existing code when appropriate.



Do not create duplicate implementations.



\---



\## 4. Respect Architecture



Do not introduce broker-specific logic into the core trading engine.



Follow:



```text

Core

\&#x20;↓

Broker Interface

\&#x20;↓

Broker Adapter

\&#x20;↓

Broker API

```



\---



\## 5. No Unnecessary Refactoring



Do not rewrite working code simply because a different style looks cleaner.



A refactor must have a technical reason.



Examples of valid reasons:



\* bug prevention

\* required feature

\* architectural boundary

\* performance issue

\* maintainability problem

\* testability improvement

\* security issue



\---



\## 6. Do Not Guess External APIs



For broker and TSETMC APIs:



\* do not invent endpoints

\* do not invent request fields

\* do not assume undocumented status values

\* do not assume identifiers match

\* do not guess authentication mechanisms



If something is unknown, mark it as unknown and investigate it.



\---



\## 7. Protect Secrets



Never place secrets in:



\* Python source code

\* documentation

\* test files

\* Git commits

\* GitHub



Never expose:



\* passwords

\* access tokens

\* refresh tokens

\* cookies

\* private API keys

\* authentication headers containing secrets



\---



\## 8. Real Orders Are Forbidden During Ordinary Development



Do not submit real trading orders merely to test functionality.



Use:



\* unit tests

\* mocks

\* dry-run

\* request construction tests

\* controlled integration tests



Real order testing requires explicit deliberate action.



\---



\## 9. Test Every Meaningful Change



After modifying code:



1\. Run relevant tests.

2\. Run the application if appropriate.

3\. Inspect errors.

4\. Fix root causes.

5\. Report test results.



Do not claim success without testing.



\---



\## 10. Do Not Hide Errors



Do not use broad exception handling simply to make the application appear successful.



Avoid patterns such as:



```python

try:

\&#x20;   ...

except Exception:

\&#x20;   pass

```



unless there is a documented reason.



Errors should be handled intentionally.



\---



\## 11. Keep Changes Focused



A task should modify only the files necessary to accomplish it.



Avoid unrelated cleanup during feature work.



\---



\## 12. Preserve Backward Compatibility Where Practical



Before changing an existing interface:



\* inspect callers

\* inspect tests

\* determine dependencies

\* update affected code deliberately



Do not break existing functionality accidentally.



\---



\## 13. Git Discipline



Before changes:



```text

git status

```



After changes:



```text

git status

```



Meaningful completed changes should normally be committed.



Commit messages should describe the change.



Examples:



```text

feat: add broker instrument mapping

fix: correct order validation

test: add Agah order dry-run coverage

refactor: isolate broker authentication

docs: update broker API findings

```



\---



\## 14. Do Not Rewrite Git History



Do not use destructive Git commands such as:



```text

git reset --hard

git clean -fd

git push --force

```



unless the user explicitly requests and understands the consequences.



\---



\## 15. Do Not Delete Unknown Files



Before deleting a file:



1\. Search for references.

2\. Determine whether it is used.

3\. Explain why deletion is safe.

4\. Prefer Git history as a recovery mechanism.



\---



\## 16. Architectural Changes Require Documentation



If a change affects:



\* project structure

\* broker abstraction

\* core order engine

\* domain model boundaries

\* authentication architecture

\* execution architecture



document the decision in `DECISIONS.md`.



\---



\## 17. Handoff After Significant Work



After completing a meaningful task, update:



```text

AI\\\_HANDOFF.md

```



Include:



\* what was completed

\* files changed

\* tests performed

\* known problems

\* remaining work

\* next recommended step



\---



\## 18. Report Changes Clearly



At the end of a task report:



```text

Files changed:

...



What changed:

...



Why:

...



Tests:

...



Known issues:

...



Next step:

...

```



\---



\## 19. Do Not Assume Conversation History



The coding agent must be able to work from the repository.



Do not assume that previous chat messages are available.



Project documentation is the portable context.



\---



\## 20. Ask Only When Necessary



If a task can be completed safely from the repository and existing requirements, do not repeatedly ask for confirmation.



Ask the user only when:



\* a decision materially affects the product

\* credentials or secrets are required

\* real trading could occur

\* requirements are genuinely ambiguous

\* an irreversible action is requested



\---



\## 21. Product Decisions Belong to the User



The coding agent implements.



The user makes product-level decisions.



The agent must not silently change requirements because it prefers another design.



\---



\## 22. Final Rule



\*\*Inspect first. Change minimally. Test. Document. Commit.\*\*



Never trade correctness and safety for speed.

