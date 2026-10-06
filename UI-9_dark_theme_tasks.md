# UI-9 — Dark Theme, Layout & Localization (Task Package)

> **Status:** UI-9.1, UI-9.2, UI-9.2b and UI-9.3 are **COMPLETED and Architect-verified** (2026-10-04).
> UI-9.4 (inline validation errors) and UI-9.5 (style propagation + documentation) are **NOT STARTED**
> and must not be started without explicit Product Owner approval.
> **Verified:** mandated baseline 310 passed / 2 deselected / EXIT=0; all 30 `test_ui*.py` files
> 563 passed / 2 deselected / EXIT=0.
>
> **AUTHORITY NOTE:** this document is the master record and the committed record of UI-9.
> The per-task handover files (`UI-9.2_task.md`, `UI-9.2b_task.md`, `UI-9.3_task.md`) are working
> notes and are deliberately **not** tracked in the repository.
>
> **RTL now lives in `create_app()`** (`ui/app.py`) and is complete; the target column orientation
> (RIGHT = order information, LEFT = scheduling) is measured and holds.
> **Defined by:** Architect. **Implementation:** a separate coding agent.
> **Visual reference (approved by the Product Owner):**
> `design/UI-9_mockup_full_page.png` (full page) and `design/UI-9_mockup_order_page.png` (top view).
> The mockups were rendered with the real Qt toolkit and the exact QSS proposed below, so they show the intended result.
>
> **Rule for the coding agent:** implement the tasks in order, one at a time, and report results before starting the next.
> **Do not commit and do not push** — the Architect reviews first.

---

## 0. Approved decisions (Product Owner approved all of this)

| # | Decision |
|---|---|
| 1 | The whole User Application gets a **dark, professional theme**. PySide6 is kept; no framework change. |
| 2 | The Order page is split into **two columns**: right = order information, left = scheduling settings; **the bottom is the table area**. |
| 3 | **RTL and full Persian** localization of the user-facing UI. |
| 4 | Modal dialogs for validation are replaced by **inline error messages**. |
| 5 | **No change to order-send logic** of any kind. |
| 6 | The same style is then propagated to the other pages. |

**Font decision:** primary font `IRANSansX` (verified installed on the Product Owner's machine, including the `IRANSansXFaNum` variant), with fallback chain `"IRANSansX", "Vazirmatn", "IRANSans", "Tahoma", "Segoe UI"`.
**Do NOT add any font file to the repository in UI-9** (licensing not verified). A separate follow-up decision is required if the application must ship the font for other machines. Record this as a known limitation.

**Digit policy (approved):**
- **Latin digits** for the countdown and for technical/timestamp values (e.g. `00:00:03.240`, `08:44:56.120`) — precision readability.
- **Persian digits** for money, price and quantity (e.g. `۱۲٬۴۹۵٬۰۰۰`).
- All number formatting must be centralized in **one helper**, never scattered inline.

---

## 1. Frozen constraints — violating any of these rejects the task

These were verified by reading the repository. They are not optional.

**C1 — Order-send logic must not change.**
`ui/test_runner.py`, `core/order_engine.py`, `core/dispatch_core.py`, `core/safety_gate.py`, `ui/schedule_dispatcher.py`, and the whole `Plan → Dispatch → Broker` path stay untouched. UI-9 is presentation only: colour, layout, font, text, and the channel that displays validation errors.

**C2 — Do not touch the existing uncommitted change in `ui/test_runner.py`.**
It has its own separate decision. Leave the working-tree modification exactly as it is.

**C3 — No live trading.**
`live_trading_enabled` must not be enabled. No real order, no network request, no broker credentials, no TSETMC access in any test.

**C4 — The `content_area` structure must not change.**
`test_ui1_application_foundation.py` asserts `content_area.count() == 4` and widget identity. Do not add or remove pages, and do not replace the `QStackedWidget`.

**C5 — These two parent relationships must survive.**
`test_ui4_queue_ui_integration.py:314` asserts `page.queue_list.parent().title() == "Order Queue"`
`test_ui5_task3_order_results.py:612` asserts `page.result_list.parent().title() == "Test Results"`

⇒ `queue_list` must stay a direct child of its `QGroupBox`, and `result_list` a direct child of its `QGroupBox`. **Do not insert an intermediate container between them.** Do not rename these attributes.

**C6 — Every new file in `ui/` must satisfy the import contract.**
`test_ui3_1_order_configuration.py::test_14` runs an AST scan over **every** `ui/*.py`:
- importing `main`, `brokers.*`, `core.*` is banned, except the 8 allow-listed core seams;
- `market.*` is allowed only for `market.symbol_resolver`;
- `market.symbol_resolver`, `core.timing_contracts`, `core.timed_dispatch_scheduler` must be imported **inside a function body only**, never at module level.

⇒ A new `ui/theme.py` / `ui/strings.py` is allowed **as long as it imports nothing from `market`/`brokers`/`core`/`main`**. Importing from `PySide6` is unrestricted.

**C7 — Do not change existing public attributes.**
All currently-tested attributes and slots must keep their names, e.g. `queue_list`, `result_list`, `queue_status_label`, `schedule_group`, `countdown_label`, `diagnostic_section`, `active_account_label`, `quantity_input`, `price_input`, `config`, and the existing factories/setters.

**C8 — Known pre-existing failures, not your regressions.**
At HEAD these two tests already fail:
`test_block8_task8_2.py::test_latency_does_not_add_fields_to_existing_contracts`
`test_block8_task8_3.py::test_measurement_keeps_existing_engine_and_result_contracts`
They are caused by the `broker_received_at` field added to `OrderExecutionResult` by commits `2459ece`/`3557c04`. **Report them as pre-existing; do not fix them in UI-9 and do not claim full green.**

**C9 — After changing code, do NOT run any graphify command.**
The repository's post-commit hook handles graph updates.

**C10 — No commit, no push.**

**C11 — Appearance only: no text and no test-assertion changes in UI-9.1 / UI-9.2.**
Do not rewrite any existing user-facing string and do not modify any `assert` in any test file during UI-9.1 and UI-9.2. Those two tasks are purely visual (colour, layout, font, spacing, layout direction). Persian text changes belong to UI-9.3 and validation-channel changes to UI-9.4, each of which requires **separate explicit Product Owner approval** before starting. If a change would alter behaviour, **stop and ask** — do not decide.

---

## 2. Verification environment

```
Python 3.13.15 · pytest 9.1.1 · PySide6 6.11.2 (Qt 6.11.2)
QT_QPA_PLATFORM=offscreen
```

> **Offscreen font note (important, verified):** under `QT_QPA_PLATFORM=offscreen` Qt has no system font directory and every text renders as empty boxes. To take a meaningful screenshot, register the font explicitly:
> `QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\IRANSansX-Regular.ttf")`
> Do this **only inside the screenshot helper**, never in production code.

**Step 0 — record the baseline before touching anything.** Run the bounded baseline below and write down passed/failed/deselected counts. Without a baseline, regressions cannot be attributed.

---

## 2b. Preflight — STOP conditions (do these before anything else)

The coding agent must verify these **before** running any test or editing any file. If any check fails, **STOP immediately, change nothing, and report.**

| # | Check | Required result | If it fails |
|---|---|---|---|
| P1 | `UI-9_dark_theme_tasks.md` exists at the repository root and is readable | present, non-empty | **STOP** and report the paths searched |
| P2 | `design/UI-9_mockup_full_page.png` exists | present | **STOP** and report — never invent a layout |
| P3 | `design/UI-9_mockup_order_page.png` exists | present | **STOP** and report |
| P4 | `ui/order_configuration_page.py` exists and `git rev-parse HEAD` succeeds | present | **STOP** and report |
| P5 | `git status --short` recorded | the existing `M ui/test_runner.py` is visible and must stay visible | if absent, note it; never try to recreate it |

**Report at preflight:** the resolved absolute path of each artifact, `git rev-parse HEAD`, and the recorded `git status --short`.
**Never guess or substitute** a missing reference image or a missing task file, and never proceed on a partial read.

---

## 2c. Time-bounded verification (mandatory — some UI tests hang)

**Verified environment facts:**
- `pytest-timeout` is **NOT installed**, and there is **no** `pytest.ini` / `tox.ini` / `setup.cfg` / `pyproject.toml` / root `conftest.py`. So `--timeout=…` is unavailable — **do not install it** (a new dependency is out of scope).
- Two tests **hang indefinitely** because they feed invalid input with no modal stub installed:
  `test_ui3_1_order_configuration.py::test_5_quantity_enter_and_store` and
  `test_ui3_1_order_configuration.py::test_extra_page_preserves_state_on_fractional_input`.
  **Measured:** the whole UI-3.1 file never finishes (killed at 45 s and at 60 s).
- **Therefore the UI-3.1 file must NEVER be run without deselecting those two tests.**

**Mandatory runner.** Write this helper **outside the repository** (e.g. `%TEMP%\ui9_tools\run_tests_bounded.py`). It bounds wall-clock time, writes output to a file (file redirection, never a pipe), and prints one machine-readable status line:

```python
"""Bounded pytest runner (tooling only — never project code)."""
import subprocess, sys, time

def main():
    timeout, out_path, pytest_args = int(sys.argv[1]), sys.argv[2], sys.argv[3:]
    started, status, code = time.time(), "DONE", None
    with open(out_path, "w", encoding="utf-8", errors="replace") as handle:
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", *pytest_args],
                stdout=handle, stderr=subprocess.STDOUT, timeout=timeout,
            )
            code = completed.returncode
        except subprocess.TimeoutExpired:
            status = "TIMEOUT"
    print(f"STATUS={status} EXIT={code} SECONDS={time.time()-started:.1f} OUTPUT={out_path}", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

**Every pytest invocation in UI-9 must go through this runner. Never run bare `pytest`.**
Do not rely on `$LASTEXITCODE` from `Start-Process` — it is unreliable here; the `EXIT=` field above is the authoritative value.

**Time limits (hard caps):**

| Run | Selection | Cap |
|---|---|---|
| Baseline / Tier 1 | the command below | 240 s |
| Single UI test file | one file (UI-3.1 only with both deselects) | 120 s |
| UI-3.1 file | must include both `--deselect` flags | 180 s |
| Broad UI regression | per file, never all UI files in one process | 180 s per file |
| Block 8 known failures | the two tests only | 60 s |

**If a run reports `STATUS=TIMEOUT`:** record it as **TIMEOUT**, not as a failure, and continue. Never retry the same hanging command with the same selection. Every timeout must appear in the report.

**Bounded baseline command (verified on this machine):**

```
python %TEMP%\ui9_tools\run_tests_bounded.py 240 %TEMP%\ui9_baseline.txt ^
  --deselect test_ui3_1_order_configuration.py::test_5_quantity_enter_and_store ^
  --deselect test_ui3_1_order_configuration.py::test_extra_page_preserves_state_on_fractional_input ^
  test_ui1_application_foundation.py ^
  test_ui3_1_order_configuration.py ^
  test_ui3_2a_symbol_search.py ^
  test_ui4_queue_ui_integration.py ^
  test_ui5_task3_order_results.py ^
  test_ui6_task1_diagnostic_mode.py
```

**Measured expected baseline at HEAD (verified by the Architect on 2026-10-04):**
```
STATUS=DONE EXIT=0 SECONDS=26.4
130 passed, 2 deselected
```
The agent must reproduce this **before** editing anything. If the numbers differ, **stop and report the difference** instead of proceeding.

**Pre-existing failures — measured, not a UI-9 regression:**
```
python %TEMP%\ui9_tools\run_tests_bounded.py 60 %TEMP%\ui9_block8.txt ^
  test_block8_task8_2.py::test_latency_does_not_add_fields_to_existing_contracts ^
  test_block8_task8_3.py::test_measurement_keeps_existing_engine_and_result_contracts
→ STATUS=DONE EXIT=1   2 failed in 0.49s
```
Report these as pre-existing (constraint C8). **Never claim the suite is fully green.**

**After each task**, re-run the bounded baseline and give a before/after comparison. Always report every `TIMEOUT` explicitly and never silently drop a deselected test.

**Visual verification is mandatory** for UI-9.1 and UI-9.2 (this is a visual task): grab the page in NORMAL and DIAGNOSTIC mode to PNG and report the file paths. Remember the offscreen font note above, or the screenshots will be unreadable empty boxes.

---

## Task UI-9.1 — Dark theme foundation

**Goal:** one single, dark, professional visual layer for the whole application.

> **Status: COMPLETED — delivered and independently verified by the Architect (2026-10-04).**
> Delivered: `ui/theme.py` (new), `ui/app.py` (+5), `ui/main_window.py` (+11), `test_ui9_task1_dark_theme.py` (new, 13 tests).
> Architect re-ran: bounded baseline **130 passed / 2 deselected / EXIT=0** (identical to pre-change), theme tests **13 passed**,
> `test_ui2_1` **14 passed**. Order-path files untouched, `ui/test_runner.py` diff still the pre-existing 23+/10−,
> zero `RightToLeft` calls in `ui/`. Screenshots inspected — dark theme renders correctly with readable text.
> **RTL is excluded from this task and moved to UI-9.3** (see the verified finding under the work list).
> Nothing committed, nothing pushed.

**New file:** `ui/theme.py`
**Modified file:** `ui/app.py`

**Work:**
1. In `ui/theme.py`, define all design tokens in one place:
   - **Palette:** `background #12141a`, `surface #1a1d24`, `surfaceAlt #20242d`, `border #2a2f3a`, `text #e6e9ef`, `textMuted #9aa3b2`, `accent #3b82f6`, `success #22c55e`, `warning #f59e0b`, `danger #ef4444`
   - **Spacing scale:** 4 / 8 / 12 / 16 / 24 — no magic numbers scattered in the page.
   - **Geometry:** uniform input and button height, 6–8px corner radius.
2. Build one complete QSS string covering at least:
   `QWidget`, `QMainWindow`, `QGroupBox` + `QGroupBox::title`, `QLabel`, `QPushButton` (default / `:hover` / `:pressed` / `:disabled` / `:checked` / `[variant="primary"]` / `[variant="danger"]`), `QLineEdit` (+`:focus`, `:read-only`, `[variant="invalid"]`), `QComboBox` + `::drop-down`, `QListWidget`, `QTableWidget` + `::item` + `:selected`, `QHeaderView::section`, `QStatusBar`, `QScrollArea`, `QScrollBar` (vertical), `QCheckBox`.
3. Provide `apply_theme(app_or_widget)` and a way to get the tokens, so the theme can be applied from `ui/app.py` **and** from `MainWindow` / the Order page root. This matters because several tests construct a page directly without `create_app()`.
4. In `ui/app.py`, `create_app()` must set the stylesheet and the font chain on the `QApplication`.
   **RTL is NOT part of UI-9.1.** Do **not** call `setLayoutDirection` or use `Qt.RightToLeft` in this task — RTL moved to UI-9.3 (see the verified finding there).
5. In `MainWindow`, apply the theme to the window so a directly-constructed window is themed too.

> **RTL moved out of UI-9.1 — verified finding (Architect, 2026-10-04).**
> The original step 4 also required `Qt.RightToLeft` on the `QApplication`. The implementing agent found that this breaks
> `test_ui2_1_account_management.py::test_12` and stopped to ask instead of deciding (correct behaviour).
> The Architect reproduced it independently on the **real** `AccountsPage`:
> ```
> no RTL            → currentRow=0  selectedItems=3   (works)
> app-level RTL     → currentRow=-1 selectedItems=0   (selectRow becomes a no-op)
> no theme + RTL    → currentRow=-1 selectedItems=0   (so it is NOT the QSS)
> RTL on the table widget only, applied AFTER rows were populated → currentRow=0 selectedItems=3  (works)
> ```
> So the breakage is real and is caused by the **layout direction, not the theme**, and it interacts with
> `setSelectionBehavior(SelectRows)` on a table that was **created while RTL was already active**.
> A minimal isolated `QTableWidget` with default `SelectItems` does **not** reproduce it.
> **Conclusion:** RTL is deferred to UI-9.3, and it is *not* proven impossible — the widget-level route still works
> and must be investigated properly there. UI-9.1 therefore ships without any RTL call.

**Constraints:** no string changes, no logic changes, no structural changes in this task.

**Acceptance:** `python -m ui` starts under `QT_QPA_PLATFORM=offscreen` without error; the dark style is uniform across widget types; no existing test broke.

**Tests:** add `test_ui9_task1_dark_theme.py` verifying: the module exists; `apply_theme` is callable; the QSS is non-empty and contains each palette colour; the token/spacing API is present and import-safe (importing `ui.theme` must not import `market`/`brokers`/`core`/`main` — assert this by AST or by inspecting `sys.modules`). Then run the full UI regression and report exact counts.

---

## Task UI-9.2 — Order page layout: two columns + bottom tables

**Modified file:** `ui/order_configuration_page.py` (currently 3355 lines; the root is a plain `QVBoxLayout` at line 610 with no scroll area).

> **Status: COMPLETED — delivered and independently verified by the Architect (2026-10-04).**
> Delivered by `UI-9.2_task.md`: inner `QScrollArea`, two-column top row, `Order Queue | Test Results`
> row, full-width `Order Log`, Diagnostic last, token-driven table row heights, prominent
> countdown/state, `CORE_REGISTERED_ROW_COLOR` changed from `#d9f2d9` (1.02:1 contrast — unreadable) to
> `#123524` (11.07:1). Architect re-ran the bounded baseline: **169 passed / 2 deselected / EXIT=0**,
> identical to pre-change; confirmed `content_area.count()==4`, both C5 parents intact, 9 group boxes,
> one scroll area, zero RTL calls, and inspected the screenshots.
> **Follow-up `UI-9.2b_task.md`** added the separate «وضعیت صف» group box (group count 9 → 10) — also
> delivered and verified. The two columns currently render mirrored relative to the Product Owner's
> target (right = order information); this is expected and is corrected by RTL in UI-9.3.
> Nothing committed, nothing pushed.

**Work:**
1. **Scroll — mandatory.** Wrap the page content in a `QScrollArea`. The page currently overflows at the real window height (proven by the mockup: the bottom table fell outside the frame). ⚠️ The object added to `content_area` must remain **the same page widget** (constraint C4). Safest approach: keep `OrderConfigurationPage` a `QWidget` and put an **inner** `QScrollArea` inside it.
2. **Top row — two equal columns:**
   - **Right column (order information):** «حساب فعال» → «مشخصات سفارش» → «اطلاعات نماد» → «مبالغ»
   - **Left column (scheduling):** «زمانبندی» together with the countdown, the Apply/Stop buttons and the clock/sync status, plus «وضعیت صف»
3. **Bottom area — the table:**
   - «صف سفارشها» and «نتیجهٔ اجرا» side by side;
   - «لاگ سفارشها» **full width beneath them**;
   - the Diagnostic section last (still visible only in DIAGNOSTIC mode).
4. All margins, spacing, sizes and radii come from `ui/theme.py` tokens.
5. Tables: uniform row height, readable headers, sensible column widths, clear selection, and make `CORE_REGISTERED_ROW_COLOR` (line 317) readable on the dark theme.
6. Make the countdown and the scheduling status visually prominent (larger size, accent colour).
7. Do **not** add tabs or extra pages. Everything stays on the one page.

**Constraints:** C1, C4, C5, C7. All 9 existing groups must still exist and be reachable. No attribute or slot renamed. No logic change.

**Acceptance:** the two columns and the bottom tables are visible and reachable; the page scrolls instead of clipping; `queue_list.parent().title()` and `result_list.parent().title()` still hold.

**Tests:** run the full UI regression; UI-4 (queue) and UI-5 (results) must stay green. **Also produce visual proof:** a small helper that grabs the page in NORMAL and DIAGNOSTIC mode to PNG (remember the offscreen font note above) and report the file paths so the result can be reviewed visually.

---

## Task UI-9.3 — RTL and full Persian localization

**Goal:** a fully Persian, right-to-left interface.

> **Status: COMPLETED — delivered and independently verified by the Architect (2026-10-04).**
> Delivered: `ui/strings.py` (new Persian catalogue), RTL in `create_app()` only, Persian
> localization of every user-facing string, the approved digit policy, and the glyph fixes.
> Architect re-ran: mandated baseline **310 passed / 2 deselected / EXIT=0** (identical to
> pre-edit) and **all 30 `test_ui*.py` files → 563 passed / 2 deselected / EXIT=0** (full UI
> suite green). Independent `QRawFont` audit: **0 missing-glyph characters** in NORMAL and
> DIAGNOSTIC. Measured column orientation: **RIGHT = order information, LEFT = scheduling**.
> `core/` order path untouched; `ui/test_runner.py` still only its pre-existing 23+/10− change.
>
> **RTL finding (measured):** with app-level `RightToLeft`, a `QTableWidget` using
> `setSelectionBehavior(SelectRows)` that was **created while RTL was already active** turns
> `selectRow()` into a no-op (`currentRow()` → −1). Real mouse clicks are **not** affected —
> verified on the real `AccountsPage` — and `setCurrentCell(row, 0)` works under RTL. Only the
> test `test_ui2_1_account_management.py::test_12` used the broken call; it now uses
> `setCurrentCell`. **No product behaviour in `accounts_page.py` was changed.**
>
> **Glyph finding (measured):** IRANSansX cannot draw U+2014 (`—`), U+2013, U+2010, U+2015,
> U+00B7, U+2022, U+2192 (`→`), tatweel or ZWNJ — they render as empty boxes; only U+002D
> (`-`) renders. All user-facing `—` and `→` were replaced with `-`. One U+2014 remains on
> purpose in `ui/order_config_state.py`, inside a developer-facing exception message that
> never reaches a widget.
>
> **Also corrected:** the trading-state label's empty value is the Persian `STATUS_LABEL_UNKNOWN`
> («نامشخص»), not a dash.
>
> **Limitations:** a font file is not bundled, so a machine without IRANSansX falls back
> through the chain; the two Block 8 `broker_received_at` failures are pre-existing; the two
> UI-3.1 tests that hang on modal dialogs stay deselected until UI-9.4.
> Nothing committed by the implementing agent — the checkpoint is completed by the Architect.

**New file:** `ui/strings.py` — all user-facing strings in one place.
**Modified files:** `ui/order_configuration_page.py`, `ui/schedule_settings.py`, `ui/accounts_page.py`, `ui/user_log.py`, `ui/main_window.py`, plus the test files listed below.

**Work:**
1. **RTL — mandatory investigation first, then apply.** Do **not** simply call `app.setLayoutDirection(Qt.RightToLeft)`; it is already known to break a test (see the verified finding under Task UI-9.1). Required sequence:
   a. **Investigate and document** the real interaction: app-level RTL + `QTableWidget.setSelectionBehavior(SelectRows)` + a table **created while RTL is already active** makes `selectRow()` a no-op (`currentRow()` returns `-1`). Confirm the exact trigger (is it creation-time direction? the `SelectRows` behavior? the `refresh()` repopulation order?).
   b. Choose a route that keeps **every** existing test green, and state the evidence. A **widget/page-level** direction was measured to work when applied after the rows are populated — investigate whether that route is sufficient for a proper RTL application, and whether `accounts_page` needs a small adaptation.
   c. Only then apply RTL, so that RTL also holds when a test constructs a page standalone without `create_app()`.
   d. **If no route keeps the suite green without changing product behaviour, STOP and report** — that would be a critical decision for the Product Owner.
   **Record the finding** (trigger + chosen route + evidence) in `DECISIONS.md` as part of UI-9.3.
2. Move every user-facing string into `ui/strings.py` and translate it to Persian. Mandatory items:
   - **Group titles:** `Active Account` → «حساب فعال»، `Order Configuration` → «مشخصات سفارش»، `Symbol Information` → «اطلاعات نماد»، `Amounts` → «مبالغ»، `Order Queue` → «صف سفارشها»، `Test Results` → «نتیجهٔ اجرا»، `Schedule` (`ui/schedule_settings.py:63`) → «زمانبندی»، `Order Log` (line 310) → «لاگ سفارشها»، `Diagnostic — Execution Details (Test Pass)` (line 332) → «عیبیابی — جزئیات اجرا»
   - **Form labels:** `Symbol:` → «نماد:»، `Side:` → «نوع معامله:»، `Price:` → «قیمت:»، `Quantity:` → «تعداد:»
   - **Queue status messages** `QUEUE_STATUS_*` (lines 264–270) and the search states (lines 234–235)
   - **Modal dialog titles** (English today) — relevant to Task UI-9.4
   - `QMessageBox` button texts and the account page titles (`Invalid account`, line 137/156)
   - **Navigation entries** and the mode label in `ui/main_window.py:77` (`Home/Accounts/Order Configuration/Settings`, `Mode: NORMAL`)
3. **Do not touch** `SIDE_LABELS`, `STATUS_LABEL_*`, `RESULT_STATUS_*` values that come from the Core — only the UI-side text.
4. **Apply the approved digit policy** through one centralized formatter (Latin for countdown and log timestamps, Persian for money/price/quantity).
5. Persian text must not be truncated or clipped; check the RTL alignment of numbers and of the queue/results tables.

**Test-contract updates — authorized and required in this task.**
Ten test files assert English UI strings as literals. They must be updated to import from `ui/strings.py` instead of hardcoding. Involved files:
`test_ui1_application_foundation.py`, `test_ui3_1_order_configuration.py`, `test_ui3_2a_symbol_search.py`, `test_ui4_queue_ui_integration.py`, `test_ui5_task2_dry_run_execution.py`, `test_ui5_task3_order_results.py`, `test_ui5_task4_stage3_task3_core_registration.py`, `test_ui6_task1_diagnostic_mode.py`, `test_ui7_task2_countdown_state.py`, `test_ui7_task3_periodic_dispatch.py`, `test_ui8_task1_single_broker_e2e.py`, `test_ui8_task2_multi_account_multi_broker_e2e.py`
Also these three structural assertions must be updated to the new values:
`test_ui4_queue_ui_integration.py:314`, `test_ui5_task3_order_results.py:612`, `test_ui6_task1_diagnostic_mode.py:330`.

**Acceptance:** no English user-facing text remains; RTL is correct; no test is left red because an assertion was forgotten.

---

## Task UI-9.4 — Inline validation errors instead of modal dialogs

**Goal:** replace `QMessageBox` with an inline error message on the form.

**Modified files:** `ui/order_configuration_page.py`, `ui/accounts_page.py`

**Work:**
1. Replace these three calls with an inline error label styled `danger`:
   - line **2693** `QMessageBox.warning(self, "Invalid side", str(exc))`
   - line **2707** `QMessageBox.warning(self, "Invalid price", str(exc))`
   - line **2722** `QMessageBox.warning(self, "Invalid quantity", str(exc))`
2. Same treatment for `ui/accounts_page.py` lines **137**, **147**, **156** (two `warning`s and one `information`).
3. **The validation logic must not change** — the same conditions, in the same order, accepting and rejecting exactly the same values. Only the display channel changes. The inline message text must carry the same information as the previous dialog message.
4. Remove the `QMessageBox` import where it becomes unused.

**Why this task also fixes a real bug (verified):**
Two tests currently **hang** in this environment because they feed invalid input and no modal stub is installed, so the blocking dialog waits forever:
`test_ui3_1_order_configuration.py::test_5_quantity_enter_and_store` (line 229) and `test_extra_page_preserves_state_on_fractional_input` (line 683).
Other tests in the same files already work around this by monkeypatching a non-modal stub (`test_ui3_1` lines 179–190; `test_ui2_1_account_management.py` lines 232–242).
After this task, `pytest test_ui3_1_order_configuration.py -q` must run **completely, without any timeout and without deselection**.

**Test-contract updates — authorized and required.**
The tests that currently patch `QMessageBox` and assert the dialog title must be updated to assert the **inline error text** instead:
- `test_ui3_1_order_configuration.py` — the price test (around lines 179–210, asserts `"Invalid price"` twice) and the quantity test; remove the now-unnecessary non-modal stub where it exists.
- `test_ui2_1_account_management.py` — Test 9 (around lines 232–266, asserts `"Invalid account"`).
The assertions must become stronger, not weaker: they must still prove that the invalid value was **rejected**, that the previous valid state was **preserved**, and now additionally that the user sees an inline message — with no modal involved.

**Acceptance:** no modal dialog remains on a form error path; the whole UI-3.1 file runs without hanging and without deselection; behaviour semantics of validation are unchanged.

---

## Task UI-9.5 — Propagate the style, regression, documentation

**Goal:** the same look on the remaining pages, plus closing the work.

**Work:**
1. Apply the theme tokens and the Persian/RTL treatment to: `ui/accounts_page.py`, the Home and Settings placeholder pages (`ui/main_window.py`), the navigation bar, the status bar, and the Diagnostic section.
2. Navigation bar: the active entry must be clearly distinguished and widths uniform. **Constraint:** `navigation_area` and the existing `select_page` mechanism must not change.
3. **Documentation:** record the UI-9 decision in `DECISIONS.md` (a new Decision entry: dark theme, two-column layout, RTL/Persian, inline validation errors, font and digit policy including the font-distribution limitation), and add a UI-9 status section to `AI_HANDOFF.md`. Mark each task's status truthfully.
4. **Final report must be exact:** the command run, passed/failed/deselected counts, and an explicit mention of the two pre-existing Block 8 failures (C8) and whether the two UI-3.1 hangs are now resolved.

---

## Execution order

```
Task UI-9.1  (theme foundation)
      ↓
Task UI-9.2  (two-column layout + bottom tables + scroll)
      ↓
Task UI-9.3  (RTL + Persian localization + digit policy)
      ↓
Task UI-9.4  (inline validation errors)
      ↓
Task UI-9.5  (propagate + regression + documentation)
```

**One task per delivery, with a report after each** so the Architect can review before the next starts.
UI-9.1 and UI-9.2 are dependent. UI-9.3 and UI-9.4 both touch strings and tests, so they must stay **two separate tasks** — if a test breaks, the responsible task must be identifiable.

**Report template (per task):**
```
Task:            UI-9.x
Preflight:       P1–P5 result, resolved paths, git rev-parse HEAD
Files changed:   …
Commands run:    … (every pytest run via the bounded runner, with its time cap)
Results:         N passed, M failed, K deselected   (EXIT=…)
Timeouts:        any STATUS=TIMEOUT run, with the selection and cap used
Baseline diff:   before → after  (baseline was 130 passed, 2 deselected, EXIT=0)
Constraints:     C1–C11 — confirm each one individually
Screenshots:     paths (mandatory for UI-9.1 and UI-9.2)
Known issues:    … (including the two pre-existing Block 8 failures)
Commit/push:     NOT DONE (awaiting Architect review)
```

---

## Explicitly out of scope for UI-9

- Any change to the order-send behaviour, dispatch path, Core, M6-A…M6-E gates, SafetyGate, or `TestRunner` (C1).
- Enabling `live_trading_enabled`, or any real order/credential/network use (C3).
- Bundling a font file into the repository (separate decision).
- The two pre-existing Block 8 `broker_received_at` failures (C8) — they need their own scoped repair task.
- The uncommitted `ui/test_runner.py` SafetyGate change (C2) — separate decision.
- M6-F / order splitting, Central Server, Admin Panel, License/Activation — later phases.
- Any new dependency or framework change; PySide6 is kept.
