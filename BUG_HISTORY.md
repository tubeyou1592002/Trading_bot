\# Trading Bot — Bug History



This file records important bugs, failures, root causes, and fixes.



The purpose is to prevent future AI agents from repeating known mistakes.



\---



\## BUG-001 — Git not installed / not available



\*\*Status:\*\* Fixed



\*\*Symptom:\*\*



```text

git : The term 'git' is not recognized...

```



\*\*Cause:\*\*



Git for Windows was not installed or was not available in PATH.



\*\*Resolution:\*\*



Git for Windows was installed successfully.



\*\*Result:\*\*



```text

git --version

```



works correctly.



\---



\## BUG-002 — Git author identity unknown



\*\*Status:\*\* Fixed



\*\*Symptom:\*\*



Git could not create the initial commit and reported:



```text

Author identity unknown

```



\*\*Cause:\*\*



Git user name and email were not configured.



\*\*Resolution:\*\*



A local repository-specific Git identity was configured.



\*\*Result:\*\*



Initial commit was successfully created.



\---



\## BUG-003 — Repository had no Git history



\*\*Status:\*\* Fixed



\*\*Symptom:\*\*



```text

fatal: not a git repository

```



\*\*Cause:\*\*



The `Trading\_bot` folder had not yet been initialized as a Git repository.



\*\*Resolution:\*\*



```text

git init

```



\*\*Result:\*\*



The repository was initialized successfully.



\---



\## BUG-004 — Sensitive/local files appeared as untracked files



\*\*Status:\*\* Resolved



\*\*Symptom:\*\*



The initial repository status showed files such as:



```text

captcha.png

client\_id.txt

```



as untracked.



\*\*Risk:\*\*



These files should not be committed to the repository.



\*\*Resolution:\*\*



`.gitignore` was created and updated to exclude:



```text

captcha.png

client\_id.txt

.env

.env.\*

```



\*\*Result:\*\*



These files no longer appear as files to be committed.



\---



\## BUG-005 — \*\*pycache\*\* files exist in working tree



\*\*Status:\*\* Mitigated



\*\*Observation:\*\*



Python generated `\_\_pycache\_\_` directories and `.pyc` files.



\*\*Resolution:\*\*



Python cache patterns are excluded through `.gitignore`.



\*\*Important:\*\*



Existing local cache files are not project source code and should not be committed.



\---



\# Historical Development Notes



This file should also contain important bugs discovered during future development.



Every meaningful bug should record:



```text

ID

Date

Status

Symptom

Cause

Resolution

Files affected

Tests

Notes

```



\---



\# Bug Management Rule



AI agents must not merely record the visible error message.



They should attempt to identify the root cause.



Preferred workflow:



```text

Error

&#x20;↓

Reproduce

&#x20;↓

Inspect

&#x20;↓

Find root cause

&#x20;↓

Fix

&#x20;↓

Test

&#x20;↓

Document

```



Do not hide errors to make tests appear successful.



\---



\# Future Entries



Add new bugs below this section.



Do not delete historical entries unless they are incorrect or duplicated.



