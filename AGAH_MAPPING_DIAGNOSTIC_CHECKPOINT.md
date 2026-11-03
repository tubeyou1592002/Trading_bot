# Agah Mapping Intermittent Failure Checkpoint - 2026-11-01

## وضعیت ابزارهای عیب‌یابی UI - 2026-11-02

**وضعیت: پیاده‌شده؛ در انتظار بررسی معماری**

- ابزارهای موقت از نمای عادی حذف شدند: پنجرهٔ `Symbol Selection Diagnostic` بعد از انتخاب نماد، دکمه/خروجی `Check Agah Mapping` در فرم سفارش، و دکمهٔ `تشخیص آگاه (شستا)` در پنجرهٔ قدیمی `main.py`.
- handlerها، worker و state مختص دو مسیر mapping دستی حذف شدند. متدهای provider یعنی `diagnostic_search_once` و `diagnostic_mapping` نیز که فقط برای مسیر دستی/تست مصرف می‌شدند حذف شدند؛ جست‌وجوی خودکار از مسیر account-scoped و `_authed_get_with_recovery` دست‌نخورده است.
- helperهای ساخت متن/پنجرهٔ Symbol Selection Diagnostic و تست‌های وابسته حذف و با تست نبود UI ابزار جایگزین شدند. پیام failure این مسیر اکنون فارسی و عمومی است.
- بخش Diagnostic اجرای موجود همچنان logger health و مسیر فایل را از `diagnostic_status()` نشان می‌دهد. رویدادهای lookup پشت‌صحنه، request correlation و reason codeهای امن حفظ شده‌اند؛ مسیر و سلامت logger دیگر در metadata هر lookup عادی تکرار نمی‌شوند.
- normalization حروف نماد، تطبیق دقیق `tse_id == ins_code`، factory حساب‌محور، stale-request guard، ماشین‌حساب و مسیر دستی سفارش تغییر داده نشده‌اند.
- تست‌ها آفلاین و مبتنی بر fake/mock هستند. شبکه، login/refresh واقعی، سفارش، Dry Run، Live و زمان‌بندی اجرا نشده‌اند.

تست‌های متمرکز آفلاین:

- `python -m pytest -q test_agah_mapping_diagnostic_ui.py test_ui3_2a_symbol_search.py test_buy_preview_calculator.py test_manual_live_trace_reliability.py test_manual_live_trace_instrumentation.py` → **99 passed**.
- `python -m pytest -q test_ui4_queue_ui_integration.py test_ui5_task3_order_results.py test_ui6_task1_diagnostic_mode.py` → **60 passed, 1 failed**؛ بررسی متمرکز در 2026-11-03 نشان داد `test_7_runner_issues_exactly_one_dispatch_per_run` ورودی `make_simulation_order()` با `ins_code="INS-SIM-1"` می‌سازد، اما helper در `core/simulation_harness.py` فقط `nsc_id` را مقدار می‌دهد و `Order.ins_code` را خالی می‌گذارد. در تغییر موجود `core/dispatch_core.py` مسیر lookup از `order.nsc_id` به `order.ins_code` تغییر کرده است؛ در نتیجه provider با `ins_code=""` صدا زده می‌شود و simulation catalog آن را رد می‌کند. شکست دقیق با اجرای آفلاین و socket مسدود بازتولید شد (`success=False`, `mode='BLOCKED'`, پیام `Simulation catalog has no instrument for ins_code=`). این علت مستقیماً از تغییرات قبلی worktree در dispatch/order/harness می‌آید، نه پاک‌سازی UI: فایل‌های حذف ابزار (`ui/order_configuration_page.py`, `main.py`, `brokers/agaah/instrument_provider.py`) مسیر `TestRunner -> DispatchCore -> InstrumentProvider` را تغییر نمی‌دهند. بنابراین این شکست regression تسک پاک‌سازی نیست و در محدودهٔ محدود این تسک اصلاح production/test آن انجام نشد.
- `python -m py_compile main.py brokers/agaah/instrument_provider.py ui/order_configuration_page.py test_agah_mapping_diagnostic_ui.py test_ui3_2a_symbol_search.py test_manual_live_trace_reliability.py` → موفق.

## Scope

Offline investigation and safe instrumentation only. No login, refresh, broker request, order, Dry Run, Live execution, or scheduling was performed. Search/authentication behavior was not changed to retry or otherwise recover differently.

## Proven source path

- Symbol suggestion selection uses `SymbolSearchWorker`, then `SymbolResolveWorker`. On successful resolve, `_on_resolve_succeeded` commits the real `Instrument`, requests trading state, and calls `_start_order_identity_resolution`.
- Automatic identity uses `_default_order_identity_resolver(store, account_id, broker_name)`, which calls `BrokerManager.get_instrument_provider_for_account`. It resolves the broker instance keyed by `(account_id, broker_name)` and passes that exact broker instance into the account provider. It calls `get_nsc_id(ins_code)`.
- Explicit `Check Agah Mapping` captures the active `(account_id, broker_name, ins_code)` and uses the same account-scoped provider factory. The provider API is nevertheless a different method/path: `diagnostic_mapping` -> `diagnostic_search_once` -> `broker.session.get`; automatic lookup uses `_search_candidates` -> `_authed_get_with_recovery`. Thus both use the account-owned broker object, but not the same authenticated request helper. The direct diagnostic path is preserved; no extra request/retry was introduced.
- UI applies an identity only if the captured account/broker/instrument identity and current selection still match. Existing stale-result rejection was retained and is now traceable with account/symbol/turn changed flags.
- Buy calculator preview needs active account, selected instrument/ins_code, resolved `nsc_id`, Agah broker, buy side, and valid price/quantity. Entry before account activation is supported by `refresh_active_account` -> `_restart_order_identity_if_stale`.
- A diagnostic HTTP 401 response was previously returned as an empty candidate collection and interpreted as “No matching Agah instrument.” The UI now reports access not accepted separately from genuine mismatch and connection failure.

## Instrumentation

Trace path uses the existing logger: `C:\Users\hp\Documents\Trading_bot\traces\manual_live_trace.jsonl` by default (`TRADING_BOT_TRACE_DIR` can override). Each attempt records request ID, timestamp/stage, selected symbol identifier and query, local account alias, local session/connection generations, local readiness flags, cache/lookup source, HTTP status where available, candidate count, UI application/discard reason, and fixed calculator readiness reason. Logger path and writable state are included. No raw account ID, tokens, cookies, headers, response body, exception text, or credentials are logged. Logging calls are best-effort and swallowed on failure.

Connection generation is a local UI attempt counter, not proof of a broker connection generation. Session readiness/generation are local SessionManager state only. They do not establish server-side session validity.

## Test Evidence

Network-blocked command:

```text
python -c "import socket, pytest; socket.create_connection=lambda *a,**k: (_ for _ in ()).throw(AssertionError('network blocked')); socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('network blocked')); raise SystemExit(pytest.main(['-q','test_agah_mapping_diagnostic_ui.py','test_buy_preview_calculator.py','test_manual_live_trace_reliability.py','test_manual_live_trace_instrumentation.py']))"
```

Result: 58 passed (focused Agah mapping, calculator, and shared trace logger contracts; fakes only).

Additional validation: `python -m py_compile brokers/agaah/instrument_provider.py ui/order_configuration_page.py ui/manual_live_trace.py test_agah_mapping_diagnostic_ui.py` passed; `git diff --check` passed with only LF/CRLF conversion warnings.

## Cause Status

Intermittent original cause remains unproven. Offline evidence confirms the 401/misleading no-match classification path and confirms that page entry before account readiness can later trigger resolution after account activation. It does not prove session expiry, cache corruption, query-text issues, or the exact cause of an owner-run failure. Awaiting an owner-run trace from the failing attempt.

## Owner Reproduction and Trace Collection

Start the app normally, reproduce one failure without repeating the Check action, then read the `request_id` from the visible result/last matching event in `traces\manual_live_trace.jsonl` and collect all JSONL records whose `trace_id` equals that request ID. Preserve the complete attempt records from `lookup_dispatch` through `lookup_response`/`ui_apply` and `calculator_readiness`. Do not collect screenshots or logs containing credentials, headers, cookies, or raw broker response bodies. If the UI does not display the ID, use the latest `lookup_dispatch` entry matching the local alias and symbol identifier, then collect only that trace ID's records.

No commit or push was made. Existing unrelated worktree changes were preserved.

## Follow-up — per-attempt identity correlation - 2026-11-01

- Automatic identity workers now carry their originating request ID and symbol in both success/failure signals. UI response/apply traces use those source values rather than the latest worker or currently selected symbol.
- Repeated requests for the same account and symbol receive distinct IDs. Scope checks require the current request ID as well as account/broker/instrument, so an older same-symbol response is logged as stale and cannot replace the newer selection state.
- The automatic 401 callback now assigns HTTP 401 on the local worker after selecting that worker; no login/refresh/retry behavior changed.
- Network-blocked tests: `test_agah_mapping_diagnostic_ui.py test_block9_task9_account_bound_read_paths.py test_ui3_2a_symbol_search.py test_buy_preview_calculator.py` => **73 passed**. Compile and diff checks passed.

## Current acceptance — 2026-11-02
This section supersedes the older awaiting-owner-trace notes above for the observed Shepoli/Shepdis failures.

Owner reported that both symbols now work. Independent inspection of the latest local traces confirms fresh lookups (source=lookup), IDENTITY_READY and ui_apply for Shepoli (`mlt-f2a765c48bb845038bd8d5a606aac056`) and Shepdis (`mlt-a5b4a42453fb4cd2a5dd37f0726ba09e`). Account/symbol/turn changed flags were false. Final calculator readiness was PRICE_INVALID, not IDENTITY_PENDING; symbol identity acquisition succeeded but calculator success with valid inputs is not asserted by these records.

Earlier owner-run traces for both symbols showed SEARCH_NO_CANDIDATES in instruments_all. Provider identity lookup now applies the existing SymbolResolver normalization (Arabic ya/alef-maqsura/kaf to Persian equivalents) before constructing the query, without adding a fallback request or retry. Candidate parsing rejects non-string/empty nscId safely; API failure, invalid JSON/structure, empty candidates and invalid identifiers have distinct classifications. Exact tse_id == ins_code validation remains mandatory.

The diagnostic button now explicitly sends current broker auth headers on its single GET; no new refresh/retry was added. Structured provider stage/status/reasons travel with the originating worker request to JSONL; stale results cannot replace newer request state. Raw credentials, headers, response bodies and exception text are excluded.

Independent network-blocked execution of `test_agah_mapping_diagnostic_ui.py test_diagnostic_search.py test_instrument_provider.py` passed **68 tests in 3.49s**. This establishes offline regression coverage. Successful owner lookups after normalization support the correction's effectiveness; no controlled real-service A/B comparison proves normalization was the sole cause of every earlier failure or 401.

Open limitation: an earlier independent broader run found `test_auto_amount_debounces_typing_to_one_commission_request` failing with an already-deleted Qt worker (62 passed / 1 failed in that selection). No fix or baseline attribution for that separate test is claimed here. General suite success is not asserted.

Related changes are committed with this checkpoint update; unrelated worktree changes and raw trace files are excluded. The reviewer executed no real lookup, login/refresh, order or schedule; real lookup actions were performed by the owner.

Pre-commit isolation check: the selected indexed implementation passed **68 tests in 3.64s** with network blocked and a workspace-local short temporary path. An initial run under a deeply nested review directory failed 11 trace-metadata assertions: logger_path exceeded the sanitizer's 160-character limit and the sanitizer dropped the complete extra block. This is a remaining diagnostic limitation for long configured paths, not a broker lookup failure; it is recorded rather than silently treated as passing. No production code was changed during documentation/staging.

## Temporary diagnostic UI cleanup accepted — 2026-11-03
Status: COMPLETE / accepted by architectural source review. The temporary Symbol Selection Diagnostic popup, Check Agah Mapping button/output, their workers/callbacks/state and unused direct provider diagnostic helpers are removed. The owner-requested cleanup also removes the uncommitted legacy fixed-symbol diagnostic; that widget had never been part of the committed baseline. Ordinary selection, normalization, account-scoped lookup, stale-response rejection, calculator and manual order behavior remain. Background safe JSONL events and the existing Diagnostic logger path/health display are retained. Logger path/health are no longer copied into each normal lookup event, removing the previously observed long logger-path metadata limitation for those events.

Independent offline review with socket connections blocked: the eight-file selection (`test_agah_mapping_diagnostic_ui.py test_ui3_2a_symbol_search.py test_buy_preview_calculator.py test_manual_live_trace_reliability.py test_manual_live_trace_instrumentation.py test_ui4_queue_ui_integration.py test_ui5_task3_order_results.py test_ui6_task1_diagnostic_mode.py`) returned **159 passed, 1 failed in 57.97s**.

Separate OPEN issue: `test_ui5_task3_order_results.py::test_7_runner_issues_exactly_one_dispatch_per_run` fails because the current worktree's dispatch reads order.ins_code while make_simulation_order populates only nsc_id. Source/data-flow inspection supports this cause. The agent's direct before/after snapshot test was not completed (archive extraction failed), so independence from cleanup is not proven by an A/B run; it must not be described as a verified baseline failure. No fix to dispatch or simulation data is included in this cleanup commit.

The cleanup is accepted with this explicit unrelated-test limitation. No reviewer/agent broker lookup, login/refresh, real order or scheduling was performed. Raw trace files, temporary test outputs and unrelated worktree changes are excluded from the commit. Full-suite success is not claimed.
