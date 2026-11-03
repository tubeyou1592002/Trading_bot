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

## Order range hint presentation follow-up — 2026-11-03

- Fixed malformed QSS emitted by `_setup_limit_hint`: the closing brace in the ordinary string segment is now a single brace, so Qt receives a valid `QLabel#priceRangeHint` / `QLabel#quantityRangeHint` selector.
- Range labels are positioned at the left visual edge of the line edit, use explicit left-to-right layout, and reserve the matching left text margin. Label width follows the rendered numeric range; minimum line-edit width reserves the hint and typing area so long ranges remain visible when the containing window narrows (the scrollable page can scroll horizontally).
- Offline tests: focused hints `6 passed, 32 deselected`; order form suite excluding AST guard `37 passed, 1 deselected`. The AST guard `test_ui3_1_order_configuration.py::test_14_ui_does_not_use_legacy_main` was run independently and still fails at `ui/live_order_gate.py` importing `core.live_order_authorization`, absent from that guard's `allowed_core`; guard/test untouched. This independently reproduces the same existing failure and the presentation diff does not touch `live_order_gate.py`.
- Owner-reported `OrderFeedbackService` error was not investigated; it is outside this presentation change and remains unverified.
- Preview uses synthetic values and the installed project-approved `IRANSansX` font family. No bundled font asset exists in the repository. Although Qt reports Persian glyph coverage, the captured offscreen preview renders glyphs as squares in this environment; readable Persian preview remains a limitation and must not be claimed as achieved.
- No network, login/refresh, order, Dry Run, Live, schedule, commit or push was performed.
## Inline order limit hint runtime diagnosis — 2026-11-03

- Confirmed selection flow: `_on_resolve_succeeded()` stores the selected `Instrument`, invalidates and clears old hints, then starts the price and quantity range workers.
- Proven quantity cause: `_start_range_hint_requests()` only consulted injected quantity/order-identity factories; when neither was injected its `provider_factory()` returned `None`. The worker then failed before `get_instrument(ins_code)`, unlike the quantity-arrow path's intended default active-account provider path.
- Fixed automatic quantity provider resolution through `_default_order_identity_resolver()` and the parent window's existing shared `BrokerManager`, scoped to the captured account and broker. No additional request/retry was added.
- Added allowlisted `limit_hint` trace events using the existing trace ID field as attempt ID. Events record fixed stage/reason codes for request start, source readiness/unavailability, response/failure, bounds validity, stale response, and shown/hidden result. Trace extras permit only hint kind, validity/visibility booleans, and fixed hide reasons; exception strings and account/symbol data are never logged.
- Offline end-to-end test starts at symbol resolve success and runs both real QThreads against synthetic price/provider sources, with no network. Both labels rendered (`4501/5510`, `10/9000`) and entered price/quantity (`4875`, `125`) stayed unchanged. Automated quantity provider factory is intentionally uninjected and resolves through a synthetic shared manager.
- Verification: focused hint/trace tests **6 passed**; order UI suite excluding the pre-existing AST guard **39 passed, 1 deselected**; `py_compile` passed.

## Inline order hint source and stale-response correction — 2026-11-03

- Runtime source correction: the previous range worker requested quantity limits from `TSETMC.get_order_quantity_limits`; that API has no verified per-order quantity bounds. Quantity hints now resolve `BrokerInstrument` through the active account's account-scoped provider and display `minimum_order_quantity` with the side-specific `maximum_order_quantity_for_buy` / `maximum_order_quantity_for_sell`. No TSETMC trading volume or inferred quantity is used.
- Account scope `(account_id, broker_name)` is captured with each quantity request. Active-account change and page account refresh restart the current-symbol lookup; late results are discarded on request, symbol, or account mismatch. Price hints remain TSETMC-only and can render without an active account.
- Trace review of `traces/manual_live_trace.jsonl` showed repeated `LIMIT_RESPONSE_STALE` events for both hint types. Code inspection found that `_on_price_range_succeeded` handled a `None` response before validating the scope, allowing an obsolete empty response to clear a current label. Scope validation now precedes all response content handling.
- Both labels are updated independently; missing quantity/account/provider does not suppress successful price data. The offline widget test starts at `_on_resolve_succeeded` on a shown Qt page, waits for the real price QThread, verifies `isVisible()` and left-side LTR geometry, then activates a synthetic account-scoped provider and verifies the quantity worker and label. It also verifies preserved typed values and account-stale response rejection.
- Verification: focused hint tests **7 passed, 36 deselected**; order configuration suite excluding the known AST guard **42 passed, 1 deselected**; `py_compile` and `git diff --check` passed (only LF/CRLF warnings).
- Follow-up invalid-bounds proof: the missing/inverted quantity-bounds test now uses active `ACC-1` / `Broker`, matching selected symbol and request scope. It confirms a response-received trace with no stale-response trace, invalid-bounds classification, hidden quantity label, and still-visible price label. Offline command `python -m pytest -q test_ui3_1_order_configuration.py -k "quantity_hint_stays_hidden_only_for_missing_or_invalid_active_account_bounds"` -> **1 passed, 42 deselected**.

## Hint invalidation versus identity cleanup — 2026-11-03

- Confirmed coupling bug: `_on_resolve_succeeded()` starts range-hint workers and then `_start_order_identity_resolution()` calls `_clear_order_identity()`, which previously called `_invalidate_limit_requests()` and cleared both scopes. Identity cleanup now only clears identity state; it no longer invalidates price/quantity hint requests.
- Symbol typing/selection and active-account changes still explicitly invalidate old hint requests before starting current-symbol/current-account requests. `refresh_active_account()` keeps its account-bound invalidation as well.
- Acceptance test uses the real `_start_order_identity_resolution()` and `_OrderIdentityWorker` with an injected synthetic `get_nsc_id` provider; the method is not stubbed. After identity success, both the TSETMC price and account-bound BrokerInstrument quantity labels remain visible. The test also proves no-account price visibility and stale prior-symbol response rejection.
- Offline verification: identity/hint/account-stale acceptance selection **3 passed, 41 deselected**; order UI suite excluding known AST guard **43 passed, 1 deselected**; `py_compile` passed. `git diff --check` passed with existing LF/CRLF warnings only. No network, order, commit, or push.
- No network, login/refresh, broker session, order, Dry Run, Live, schedule, commit, or push was used.

## Clear order inputs on actual symbol change — 2026-11-03

- `_on_resolve_succeeded()` compares old/new instrument `ins_code`; only a different code clears price/quantity input widgets and `OrderConfiguration.price` / `.quantity`. Resolving the same `ins_code` preserves user-entered values.
- Clear also invalidates auto-amount requests, resets calculated base/fee/final display and validation feedback. Existing queue records are not read or modified by this path.
- Added offline Qt acceptance coverage for changing symbols, same-symbol selection, stale calculator callback rejection, and current-symbol price range visibility. Existing selection/hint coverage still verifies independent current-symbol limit workers.
- Verification: `python -m pytest -q test_ui3_1_order_configuration.py -k "changing_symbol_clears_form_values_but_same_symbol_keeps_them or symbol_selection_runs_price_without_account_and_quantity_for_active_account or hint_responses_from_previous_symbol_are_invalidated"` -> **3 passed, 42 deselected**.
- No network, login/refresh, order, Dry Run, Live, schedule, commit, or push was used.

## Owner acceptance and publication — 2026-11-03

- Owner confirmed that the inline price/quantity hints now appear after separating identity cleanup from hint invalidation. Price uses TSETMC daily allowed limits; quantity uses active-account BrokerInstrument order limits.
- Owner accepted clearing price/quantity and calculated form results when changing symbols. Same-ins_code resolution preserves form values; queued orders are unchanged.
- Publication scope: order configuration UI, its offline tests, allowlisted hint trace metadata and this checkpoint. Unrelated ins_code/dispatch/simulation/TSETMC worktree changes and raw logs/previews are excluded.
- Known AST import guard remains excluded; full-suite success is not claimed. No reviewer network, login/refresh, real order, Dry Run/Live or scheduling was executed.

- Independent publication check on an isolated HEAD snapshot plus only publication files, with socket connections blocked: **44 passed, 1 deselected** (`test_ui3_1_order_configuration.py`, excluding `test_14_ui_does_not_use_legacy_main`).
