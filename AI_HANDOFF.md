# PROJECT STATE

## 1. Project Goal

هدف اصلی پروژه، ساخت یک ربات معاملاتی پایتونی برای بازار سرمایه ایران است که بتواند:

- به چند کارگزاری (Broker) متصل شود.
- اطلاعات نمادها را از TSETMC دریافت کند.
- نگاشت صحیح بین شناسه‌های TSETMC و کارگزاری‌ها (به‌ویژه آگاه) را انجام دهد.
- سفارش‌ها را با دقت بالا (زمان‌بندی دقیق) و به‌صورت ایمن (با تأکید بر `dry-run`) ثبت کند.
- وضعیت معاملاتی نمادها را بررسی و از ثبت سفارش در شرایط نامطمئن جلوگیری کند.

---

## 2. Current Architecture

معماری فعلی بر اساس لایه‌های زیر طراحی شده است:

```text
UI / Application (main.py)
    ↓
Symbol Resolver (market/symbol_resolver.py)
    ↓
Instrument (models/instrument.py)
    ↓
Order Engine (core/order_engine.py)
    ↓
Broker Interface (brokers/base.py)
    ↓
Broker Adapter (brokers/agaah/broker.py)
    ↓
Broker API (Agah API)
اجزای اصلی
brokers/: شامل پیاده‌سازی بروکرها. برای آگاه، یک پکیج جداگانه (agaah/) با فایل‌های broker.py (کلاس AgaahBroker) و instrument_provider.py (کلاس AgaahInstrumentProvider) ایجاد شده است.

core/: شامل منطق اصلی معاملات (order_engine.py).

market/: شامل ارتباط با TSETMC (tsetmc.py) و resolver نمادها (symbol_resolver.py).

models/: مدل‌های داده‌ای (Instrument, BrokerInstrument, Order, ...).

input/: مدیریت ورودی کیبورد فارسی.

3. Completed Work
الف) زیرساخت و کنترل نسخه
Git راه‌اندازی شد و baseline اولیه (f600a6c) ثبت شد.

.gitignore برای排除 فایل‌های حساس و موقتی به‌روز شد.

ب) مستندسازی
تمام فایل‌های مستندات پروژه (AI_PROJECT_MEMORY.md, PROJECT_CONTEXT.md, ARCHITECTURE.md, DECISIONS.md, AGENT_RULES.md, AI_HANDOFF.md, BUG_HISTORY.md) ایجاد و تکمیل شدند.

ج) پیاده‌سازی اولیه
کلاس TSETMC برای جستجو و دریافت اطلاعات نمادها.

کلاس AgaahBroker برای ارتباط با API آگاه (احراز هویت، دریافت کپچا، موجودی، ثبت سفارش).

مدل‌های داده (Instrument, BrokerInstrument, Order و ...).

OrderEngine اولیه.

د) حل مسئله‌ی نگاشت TSETMC insCode → Agah nscId
چندین اسکریپت تشخیصی (investigate_mapping_v*.py) برای بررسی روش‌های مختلف نگاشت نوشته شد.

روش‌های cIsin → nscId و symbol → nscId (بدون تأیید) رد شدند.

روش نهایی تأیید شد: جستجوی symbol در آگاه و سپس تأیید با tseId.

کلاس AgaahInstrumentProvider با منطق فوق پیاده‌سازی و تست شد.

ساختار brokers/agaah.py به پکیج brokers/agaah/ تبدیل شد و فایل‌ها به‌درستی سازماندهی شدند.

تمام تست‌های واحد و رگرسیون پاس شدند.

Commit نهایی با شناسه 2020f92 انجام شد.

4. Architecture Decisions
Decision 001 — Use Git
تصمیم: استفاده از Git برای کنترل نسخه.

دلیل: قابلیت برگشت، ردیابی تغییرات و همکاری با AIهای مختلف.

گزینه‌های ردشده: عدم استفاده از کنترل نسخه.

پیامد: مخزن محلی با baseline مشخص.

Decision 002 — Repository is the Source of Truth
تصمیم: مخزن و مستندات آن منبع اصلی حقیقت هستند، نه مکالمات AI.

دلیل: پروژه باید بین AIهای مختلف قابل انتقال باشد.

گزینه‌های ردشده: وابستگی به تاریخچه‌ی چت.

پیامد: مستندات جامع در مخزن نگهداری می‌شوند.

Decision 003 — Broker Independence
تصمیم: هسته‌ی معاملات باید مستقل از بروکر باشد.

دلیل: پشتیبانی از چند بروکر در آینده.

گزینه‌های ردشده: وابستگی مستقیم به API آگاه در هسته.

پیامد: لایه‌ی Broker Interface و Broker Adapter ایجاد شد.

Decision 004 — Explicit Instrument Mapping
تصمیم: نگاشت بین TSETMC و بروکر باید صریح و قابل‌تأیید باشد.

دلیل: شناسه‌ها در سیستم‌های مختلف متفاوت هستند.

گزینه‌های ردشده: فرض یکسان بودن شناسه‌ها.

پیامد: تحقیق گسترده برای پیدا کردن روش درست.

Decision 005 — Dry Run Before Real Trading
تصمیم: قبل از سفارش واقعی، dry-run انجام شود.

دلیل: جلوگیری از اشتباهات مالی.

گزینه‌های ردشده: تست مستقیم با سفارش واقعی.

پیامد: قفل ایمنی در AgaahBroker (live_trading_enabled = False).

Decision 006 — No Secrets in Git
تصمیم: هیچ‌گونه رمز، توکن یا اطلاعات حساسی در Git ذخیره نشود.

دلیل: امنیت.

گزینه‌های ردشده: ذخیره‌ی secrets در فایل‌های کد.

پیامد: استفاده از .env و getpass برای اعتبارنامه‌ها.

Decision 007 — Do Not Guess Undocumented APIs
تصمیم: هیچ رفتار API ناشناخته‌ای حدس زده نشود.

دلیل: APIهای کارگزاری‌ها مستند نیستند و حدس زدن خطرناک است.

گزینه‌های ردشده: فرض کردن ساختار پاسخ‌ها.

پیامد: استفاده از DevTools و بررسی ترافیک مرورگر برای کشف API.

Decision 008 — Incremental Development
تصمیم: توسعه‌ی تدریجی و گام‌به‌گام.

دلیل: کاهش ریسک و افزایش قابلیت بازگشت.

گزینه‌های ردشده: توسعه‌ی یکپارچه و بزرگ.

پیامد: هر تغییر در یک commit جداگانه ثبت می‌شود.

Decision 009 — Preserve Working Code
تصمیم: کد کارکرده بدون دلیل فنی بازنویسی نشود.

دلیل: جلوگیری از ورود باگ‌های جدید.

گزینه‌های ردشده: Refactor صرفاً برای زیبایی.

پیامد: تغییرات فقط در صورت نیاز فنی انجام می‌شوند.

Decision 010 — AI Agents Are Replaceable
تصمیم: هیچ AI خاصی برای پروژه ضروری نیست.

دلیل: پروژه باید با هر AI دیگری قابل ادامه باشد.

گزینه‌های ردشده: وابستگی به یک AI خاص.

پیامد: مستندات جامع برای انتقال آسان.

Decision 011 — Real Trading Is a Separate Risk Level
تصمیم: سفارش واقعی با سطح ریسک مجزا و نیاز به تأیید اضافی.

دلیل: عواقب مالی اشتباهات.

گزینه‌های ردشده: فعال‌سازی خودکار سفارش واقعی.

پیامد: dry-run پیش‌فرض است.

Decision 012 — Documentation Is Part of the Project
تصمیم: مستندات مهم در مخزن نگهداری شوند.

دلیل: بقای دانش فراتر از یک مکالمه.

گزینه‌های ردشده: مستندات خارج از مخزن.

پیامد: فایل‌های *.md در مخزن.

Decision 013 — Use TSETMC cIsin as Primary Key for TSETMC ↔ Agah Mapping (REJECTED)
تصمیم: (رد شد) استفاده از cIsin به‌عنوان کلید اصلی نگاشت.

دلیل: آزمایش‌ها نشان داد که cIsin برای همه‌ی نمادها با nscId آگاه یکی نیست.

گزینه‌های ردشده: این روش برای اکثر نمادها شکست خورد.

پیامد: روش جدید با symbol و tseId جایگزین شد.

Decision 014 — Resolve Agah nscId by Symbol Search + tseId Verification
تصمیم: از symbol (نام فارسی) برای جستجو در آگاه و سپس تأیید با tseId استفاده شود.

دلیل: تنها روشی که برای همه‌ی ۷ نماد آزمایشی کار کرد.

گزینه‌های ردشده: روش cIsin، روش symbol → nscId بدون تأیید.

پیامد: پیاده‌سازی AgaahInstrumentProvider با این منطق.

5. Verified Facts
TSETMC insCode با Agah tseId برابر است (برای نمادهای آزمایشی).

Agah nscId یک شناسه‌ی جداگانه است که برای ثبت سفارش استفاده می‌شود.

Agah tseId در پاسخ /instruments (با nscId) قابل دریافت است.

Agah /instruments/all?query=<symbol> لیستی از نمادهای مرتبط را برمی‌گرداند.

تأیید tseId == insCode برای انتخاب nscId صحیح، ضروری است.

cIsin از TSETMC همیشه با nscId آگاه یکی نیست.

AgaahBroker با احراز هویت (Authorization: Bearer و UserIdentifier) کار می‌کند.

base-data/csv در آگاه شامل tseId نیست و برای نگاشت مستقیم قابل‌استفاده نیست.

6. Current Implementation
فایل‌های مهم و مسئولیت‌ها
فایل	مسئولیت
brokers/base.py	کلاس‌های انتزاعی Broker، InstrumentProvider و InstrumentLookupError (طبق Decision 019)
brokers/agaah/__init__.py	صادرات AgaahBroker, AgaahInstrumentProvider, InstrumentLookupError
brokers/agaah/broker.py	کلاس AgaahBroker برای ارتباط با API آگاه
brokers/agaah/instrument_provider.py	کلاس AgaahInstrumentProvider برای نگاشت insCode → nscId
market/tsetmc.py	کلاس TSETMC برای دریافت اطلاعات نمادها
market/symbol_resolver.py	حل‌کننده‌ی نماد با نرمال‌سازی فارسی
models/instrument.py	مدل Instrument
models/broker_instrument.py	مدل BrokerInstrument
core/order_engine.py	هسته‌ی ثبت سفارش؛ شامل `execute_by_ins_code(...)` که insCode را از طریق InstrumentProvider به nscId تبدیل می‌کند و سپس به `execute(...)` موجود delegate می‌کند
test_instrument_provider.py	تست‌های واحد AgaahInstrumentProvider
test_engine_provider_integration.py	تست‌های واحد end-to-end: AgaahInstrumentProvider → OrderEngine.execute_by_ins_code
منطق AgaahInstrumentProvider.get_nsc_id(ins_code)
اگر ins_code در _nsc_cache موجود است، برگردان.

instrument = TSETMC.get_info(ins_code).

اگر instrument وجود نداشت، InstrumentLookupError پرتاب کن.

symbol = instrument.symbol.

جستجو در آگاه: GET /instruments/all?query={symbol}&count=50.

برای هر نتیجه، broker.get_instrument(nscId) را صدا بزن تا tseId دریافت شود.

نتیجه‌ای که tseId == ins_code دارد را انتخاب کن.

اگر پیدا شد، در _nsc_cache ذخیره کن و nscId را برگردان.

اگر پیدا نشد، InstrumentLookupError پرتاب کن.

7. Tests & Verification
تست	نتیجه
test_instrument_provider.py	۱۱/۱۱ پاس
test_engine_interface.py	۱۷/۱۷ پاس
test_engine_provider_integration.py	۴/۴ پاس
test_broker_manager.py	۶/۶ پاس
test_order_build.py	پاس
test_broker_dry_run.py	پاس
Smoke test (main.py import)	پاس
جمع تست‌های واحد آفلاین	۳۸/۳۸ پاس (M1–M4-A)
موارد تأییدشده
منطق tseId == insCode به‌درستی کار می‌کند.

AgaahInstrumentProvider اولین نتیجه را انتخاب نمی‌کند (تأیید tseId اجباری است).

از cIsin یا پسوندهای 0001/0003 به‌عنوان کلید استفاده نمی‌شود.

insCode هرگز مستقیماً به broker.get_instrument() داده نمی‌شود.

کش در حافظه به‌درستی کار می‌کند.

خطاهای شبکه به InstrumentLookupError تبدیل می‌شوند.

OrderEngine.execute_by_ins_code می‌تواند insCode را از طریق AgaahInstrumentProvider به BrokerInstrument معتبر resolve کند.

عدم تطابق nscId بین Order و provider-resolved، بدون overwrite، به‌صورت BLOCKED بلاک می‌شود.

خطای InstrumentLookupError در provider، به‌صورت BLOCKED با پیام «Instrument lookup failed: ...» منتشر می‌شود.

مسیر legacy broker.get_instrument_by_instrument_id(...) در flow جدید فراخوانی نمی‌شود.

BrokerManager.get_instrument_provider نمونه‌ی صحیح AgaahInstrumentProvider برمی‌گرداند.

provider در BrokerManager به‌صورت lazy ساخته و cache می‌شود (فراخوانی دوم همان instance را برمی‌گرداند).

provider دقیقاً همان AgaahBroker instance مدیریت‌شده توسط BrokerManager را استفاده می‌کند (broker جدید ساخته نمی‌شود).

get_instrument_provider برای broker ناشناس ValueError پرتاب می‌کند.

8. Known Issues / Risks
get_trading_state(): از TSETMC دریافت می‌شود — M5 پیاده‌سازی شده است.

سفارش واقعی: فعلاً live_trading_enabled = False است و باید با تأیید شما فعال شود.

پشتیبانی از بروکرهای دیگر: فقط آگاه پیاده‌سازی شده است.

زمان‌بندی دقیق: هنوز پیاده‌سازی نشده است.

خطاهای API آگاه: ممکن است در سناریوهای خاص (مثل نمادهای جدید) خطاهای پیش‌بینی‌نشده رخ دهد.

وابستگی به احراز هویت: اسکریپت‌های تشخیصی و تست‌ها نیاز به لاگین دستی دارند.

9. Do Not Change
موارد زیر بدون دلیل فنی و تأیید شما نباید تغییر کنند:

معماری لایه‌ها: هسته (core/) نباید به بروکر خاصی وابسته شود.

منطق AgaahInstrumentProvider: استفاده از symbol و تأیید tseId برای نگاشت insCode → nscId نباید تغییر کند، مگر اینکه روش بهتری با شواهد قطعی پیدا شود.

قفل ایمنی live_trading_enabled: نباید به‌طور پیش‌فرض فعال شود.

عدم استفاده از cIsin: cIsin نباید به‌عنوان کلید اصلی برای نگاشت استفاده شود.

ساختار brokers/agaah/: فایل‌ها و ایمپورت‌های این پکیج نباید بدون دلیل تغییر کنند.

Decision 018 در DECISIONS.md: این تصمیم نباید بدون شواهد جدید حذف یا تغییر کند.

10. Current Task / Milestone
Milestone 3 completed — integration of OrderEngine with InstrumentProvider and migration of interactive scripts.

جزئیات:
* Milestone 1: پیاده‌سازی و تأیید AgaahInstrumentProvider (commit 2020f92).
* Milestone 2: افزودن OrderEngine.execute_by_ins_code و رسمی‌سازی InstrumentLookupError (Decision 019، commit 91bd2b4).
* Milestone 3: مهاجرت اسکریپت‌های تعاملی (test_order_engine.py، test_order_dry_run.py، test_tsetmc_to_agah.py) به مسیر InstrumentProvider (commit 1a0d2d4).
* Documentation checkpoint: هم‌ترازی مستندات با Milestoneهای 2 و 3 (commit fb33d94).

Milestone 4 وضعیت:
* M4-A (BrokerManager → InstrumentProvider): IMPLEMENTED — committed as `bdd5a1d`. متد `BrokerManager.get_instrument_provider(name)` اضافه شد؛ provider به‌صورت lazy ساخته و per-broker cache می‌شود؛ provider از همان `AgaahBroker` instance موجود در `self.brokers[name]` استفاده می‌کند (broker جدید ساخته نمی‌شود). تست واحد جدید `test_broker_manager.py` 6/6 PASS. regression: 38/38 PASS (32 قبلی + 6 جدید). `main.py`، `core/`، `brokers/base.py`، `brokers/agaah/`، `models/`، `market/` در M4-A تغییر نکرده‌اند.
* M4-B (main.py / Order Workflow): IMPLEMENTED — COMMITTED as `9713360`. `current_provider` در `on_broker_changed` parallel به `current_broker` وصل شد؛ `OrderEngine` instance ساخته شد؛ `selected_instrument` در `select_symbol` ذخیره می‌شود؛ متد `send_order()` اضافه شد که از طریق `OrderEngine.execute_by_ins_code(live=False)` سفارش dry-run را اجرا می‌کند. تست واحد جدید `test_main_order_workflow.py` 7/7 PASS. regression: 45/45 PASS (38 قبلی + 7 جدید). فقط `main.py` تغییر کرده است؛ `core/`، `brokers/base.py`، `brokers/agaah/`، `models/`، `market/`، `input/` تغییر نکرده‌اند. هیچ real order ارسال نشده.

11. Next Step
M4-B committed as `9713360` — تمام تست‌ها 45/45 PASS. Milestone بعدی با دستور مستقل تعریف می‌شود:
* پیاده‌سازی واقعی `get_trading_state` برای آگاه (Decision 017) پس از شناسایی منبع معتبر.
* افزودن scheduling/timer برای ارسال زمان‌بندی‌شده سفارش.
* مدیریت چندحسابی و session lifecycle.

**Block 4 — Continuation Plan** (documented for future AI agents):

**Block 4 — Task 1** — `core/trading_state_event_trigger.py`
- Responsible for validating a Trading State Event.
- Output determines whether the event conditions are met to proceed to the next stage.
- Evaluates whether `is_order_entry_allowed is True` and `is_verified is True` on the TradingState.
- Pure, deterministic function; no broker, clock, or API dependencies.
- Fail-closed: any state that is blocked, unverified, or invalid returns False.

**Block 4 — Task 2** — Connect a valid Event to the existing Planner
- Responsible for connecting a validated TradingStateEvent to the existing Execution Planner (Block 1) so that the request to build an `ExecutionPlan` follows the standard project path.
- Task 2 MUST NOT redesign or modify the Planner.
- Task 2 MUST NOT execute or modify Dispatch Core.
- The trigger output (boolean) is used as a gate: only when the event trigger returns True does the planner proceed to build the ExecutionPlan via its standard `build_plan()` method.

**Block 4 — Task 3** — Connect `ExecutionPlan` result to Dispatch path (IMPLEMENTED)
- `core/block4_task3.py` — `connect_plan_to_dispatch(execution_plan, dispatch_core)` passes the Task 2 `ExecutionPlan` through the existing Block 2 entry point `DispatchCore.dispatch(plan)` unchanged, and returns the resulting `DispatchResult`.
- Task 3 MUST NOT redesign or modify the Planner or the Dispatch Core; both remain untouched.
- Fail-closed: when the Task 2 gate did not fire (`execution_plan is None`), the Dispatch Core is NOT called and the connector reports a skipped dispatch.
- Block 4 depends only on the existing `ExecutionPlan` / `DispatchResult` contracts (Block 0) and the existing `DispatchCore.dispatch` entry point (Block 2); no new architectural layer.
- Tests: `test_block4_task3.py` — 5 tests (exact Task 2 plan reaches dispatch by identity, DispatchResult propagation, gate-false / None fail-closed no-dispatch, full chain EventTrigger -> Planner -> ExecutionPlan -> real DispatchCore). Regression: 228/228 PASS.

**Block 4 — Task 3 — Architect Verification Status**
- Task 3 = IMPLEMENTED
- Tests = PASS (5/5)
- Architect Verification = APPROVED
- Commit/Push = pending — تا همین مرحله؛ پیش از Commit/Push نهایی هیچ تغییر کد یا معماری اضافه نشده است.

**Block Boundaries**
- Block 3 (Timed / Burst Dispatch) remains independent of Block 4; no new dependency from Block 4 on Block 3 is permitted.
- Block 5 (Execution Tracking) does not enter Block 4 at this time.
- Completion of Block 4 must not push responsibilities onto future Blocks beyond their defined scope.

**Block 3 — Task Verification Status**
- Task 1 = IMPLEMENTED / ARCHITECT APPROVED
- Task 2 = IMPLEMENTED / ARCHITECT APPROVED
- Task 3 = IMPLEMENTED / ARCHITECT APPROVED
- Tests = 32/32 PASS
- Full Regression = 228/228 PASS
- Commit/Push documentation update = pending — تا همین مرحله؛ پیش از Commit/Push نهایی هیچ تغییر کد یا معماری اضافه نشده است.

**M5 — IMPLEMENTED: TSETMC Trading State Integration**

تغییرات:
* `market/tsetmc.py`: متد `get_trading_state(ins_code)` اضافه شد — از endpoint `https://cdn.tsetmc.com/api/MarketData/GetInstrumentStateAll/{ins_code}` استفاده می‌کند.
* `brokers/agaah/broker.py`: `get_trading_state(nsc_id)` از TSETMC دریافت می‌کند؛ ابتدا `nsc_id` از طریق `broker.get_instrument(nsc_id)` به `tse_id` (که برابر TSETMC `insCode` است) تبدیل می‌شود؛ سپس identity بررسی می‌شود؛ و آخرین وضعیت (بیشترین `dEven`/`hEven`) انتخاب می‌شود؛ `cEtaval` را مطابق Decision 020 می‌نگاشت و `TradingState` مناسب برمی‌گرداند.
* `test_trading_state.py`: 16 تست جدید برای تمامی وضعیت‌ها (A, AR → allow؛ I, AG, AS, IG, IS, IR → block؛ unknown/missing/error → block؛ identity mismatch → block؛ نبود tse_id → UNVERIFIED). 16/16 PASS.
* `test_engine_interface.py`: 1 تست به‌روزرسانی‌شده برای mocking TSETMC در حالت network failure.

سیاست اجازه:
* `A ` و `AR` → Order submission ALLOWED
* تمام وضعیت‌های دیگر → BLOCKED
* unknown/missing/error/timeout/network → BLOCKED / UNVERIFIED
* identity mismatch (insCode در پاسخ با درخواست یکسان نیست) → UNVERIFIED / BLOCK

تست واحد جدید `test_trading_state.py` 16/16 PASS. Regression: 60/60 PASS (45 قبلی + 16 جدید + 1 به‌روزرسانی test_engine_interface.py).

Real CLI Verification:
* نماد آکو (insCode: 60235881999727383) — cEtaval='A ' (مجاز) → Order entry ALLOWED
* همین نماد در تاریخ 20260906 hEven=104633 — cEtaval='I ' (ممنوع) → Order entry BLOCKED
* هویت (insCode) در هر دو مورد تطبیق یافت: requested == returned

فایل‌های تغییر یافته:
* `market/tsetmc.py` — افزودن `get_trading_state` با استفاده از `GetInstrumentStateAll`
* `brokers/agaah/broker.py` — به‌روزرسانی `get_trading_state` برای nsc_id→tse_id resolution + TSETMC lookup + identity verification
* `test_trading_state.py` — تست جدید
* `test_engine_interface.py` — بروزرسانی test برای network failure mocking

هیچ real order ارسال نشده است.

## Architect AI Responsibilities & Lessons Learned

This section defines the **permanent responsibilities** of the Architect AI for the remainder of this project and for every future AI that assumes the Architect role. It applies regardless of model, provider, or session.

### Source of Truth
- The current repository and its documentation are the single source of truth. Memory or assumptions from prior conversations do not override what is in the code, tests, contracts, or Git history.
- Before any architectural decision, inspect the existing contracts, code, tests, and actual Git status.

### Evidence-Based Review
- Distinguish between a **proven, evidence-backed blocker** and a **possible concern / optional improvement**.
- Only raise issues that are real blockers as mandatory corrections for the Agent.
- Do not introduce scope creep, unnecessary refactoring, or redesign of components outside the current task.

### Contract and Implementation Separation
- Specify the architectural contract clearly.
- Preserve Agent freedom on implementation details that do not violate the contract.

### Task Discipline
- Define tasks that are as small, precise, and verifiable as possible.
- Avoid unnecessary back-and-forth; each task should be self-contained and testable.

### Safety and Fail-Closed
- Verify fail-closed behavior end-to-end, not only in a single layer.
- Confirm that safety invariants hold across the full execution path.

### Test on the Real Path
- Where possible, validate against the real system path, not only isolated mocks.
- After implementation, verify the result independently with code, tests, and Git state — not only by trusting the Agent's report.

### Git and Review Gate
- No Commit or Push occurs before Architect review and approval.
- After approval, the checkpoint is completed with documentation + commit + push.

### Out-of-Scope Handling
- If a topic is outside the current scope, record it only as a deferred / known concern. Do not pull it into the current correction loop.

### Primary Objective
- The Architect's primary objective is to preserve correctness, safety, scope discipline, and project continuity across different AIs.

### Lessons Learned from Block 2
- Initial iterations involved multiple back-and-forth cycles caused by incorrect assumptions about existing contracts.
- The breakthrough came after verifying the actual repository state and the real Planner -> ExecutionPlan -> DispatchCore path.
- **Result:** Contract-first, evidence-based review and minimal corrective tasks are mandatory from this point forward.

12. Important Context for Future AI
تاریخچه‌ی تصمیمات حیاتی
رد cIsin: در investigate_mapping_v3.py مشخص شد که cIsin از TSETMC برای اکثر نمادها با nscId آگاه یکی نیست.

تأیید symbol + tseId: در investigate_mapping_v6.py برای ۷ نماد تأیید شد که این روش کار می‌کند.

ساختار پکیج agaah: فایل brokers/agaah.py به پکیج brokers/agaah/ تبدیل شد تا امکان افزودن instrument_provider.py فراهم شود.

روش‌های کشف API آگاه
از DevTools مرورگر (online.agah.com) برای مشاهده‌ی درخواست‌ها استفاده شد.

endpointهای کلیدی:

/api/v1/instruments/all?query=<symbol>&count=50

/api/v1/instruments?nscIds=<nscId>

/api/v1/instruments/base-data/csv (فاقد tseId)

احراز هویت با Authorization: Bearer و UserIdentifier انجام می‌شود.

فایل‌های تشخیصی
فایل‌های investigate_mapping_v*.py و mapping_v*_results.json برای آزمایش و تأیید روش‌های مختلف استفاده شدند و اکنون حذف شده‌اند (به .gitignore اضافه شده‌اند).

13. Checkpoint Metadata
Date: 1405/06/14 (2026-09-07)

Project State: M5 completed (ca3e2cbf, pushed) + M6-A completed (Architect approved, pushed as 7ce09e3) + M6-B completed (Architect approved, pushed as 84f9130) + M6-C Account Cash + BUY Capacity completed (Architect approved, pushed as 03ede4e) + M6-D Portfolio Quantity / SELL Gate completed (Architect approved, pushed as f3bdf1d) + M6-E Unified BUY/SELL Capacity Preflight completed (Architect approved, pushed as be0d0b7) + Block 6 Multi-Account Execution COMPLETED (Tasks 6.1–6.7, 366 tests passing).

Last Completed Milestone: Block 6 — Multi-Account Execution (all Tasks 6.1–6.7 implemented, tested, and committed).

Next Action: None (awaiting architect definition of next milestone).

---

## 14. M6 — Order Preflight & Constraints

### M6-A — Instrument Identity + Trading-State Gate (COMPLETED / Architect Approved)

#### Implementation Summary
- **File modified:** `core/order_engine.py`
  - Added explicit identity check in `prepare()`: if `order.nsc_id != instrument.nsc_id` → `BLOCKED` (no overwrite).
  - Enforced fail-closed policy: `UNVERIFIED` (Unknown / Missing / Error / Unverified) → `BLOCKED` in `OrderEngine.prepare()`.
- **Tests added:** `test_m6a_preflight.py` — 8 tests covering:
  - valid identity + allowed state → READY
  - identity mismatch → BLOCKED
  - `A ` / `AR` → ALLOWED (via VERIFIED_TRADABLE)
  - unsupported state → BLOCKED
  - missing/unknown/error state → BLOCKED
- **Tests updated:** `test_engine_interface.py` (2 tests), `test_main_order_workflow.py` (1 test) — expectations updated for new `BLOCKED` behavior.
- **M5 contract:** Unchanged. `brokers/agaah/broker.py`, `market/tsetmc.py`, `models/trading_state.py` were not modified.

#### Test Results (M6-A)
- `test_m6a_preflight.py`: 8/8 PASS
- `test_engine_interface.py`: 17/17 PASS
- `test_main_order_workflow.py`: 7/7 PASS
- `test_trading_state.py` (M5 regression): 16/16 PASS
- `test_engine_provider_integration.py`: 4/4 PASS
- `test_broker_manager.py`: 6/6 PASS
- `test_instrument_provider.py`: 11/11 PASS
- **Total related regression: 69/69 PASS**

#### Behavioral Contract (M6-A)
```
Broker returns UNVERIFIED
    └─> OrderEngine.prepare()
            └─> RETURN BLOCKED (mode="BLOCKED")

Broker returns valid TradingState (verified + order_entry_allowed)
    └─> OrderEngine.prepare()
            └─> RETURN READY (after OrderValidator)
```

#### Out-of-Scope for M6-A
The following are explicitly **not** part of M6-A and remain for M6-B or later:
- Account Cash Availability (`tradableBalanceT1`)
- Buy Capacity via Agah (`calculatedquantity`)
- Portfolio Quantity for Sell (`numberOfShares`)
- Instrument Constraints (price thresholds, tick, min/max qty)
- Order Splitting
- Scheduler / Retry / Recovery

---

### M6-B — Instrument Price / Quantity Preflight Constraints (COMPLETED / Architect Approved)

#### Implementation Summary
- **Files modified:**
  - `models/order_validator.py` — Added fail-closed checks for required price/quantity constraints:
    - `lower_price_threshold`, `upper_price_threshold`, `fixed_price_tick`, `minimum_order_quantity`, `lot_size`, `maximum_order_quantity_for_buy`, `maximum_order_quantity_for_sell` — all now BLOCK if `None`/missing.
    - Added `lotSize` validation: `order.quantity % lot_size == 0`.
  - `core/order_engine.py` — `OrderValidationError` now maps to `mode="BLOCKED"` (fail-closed).
- **Tests added:** `test_m6b_preflight.py` — 21 tests covering:
  - price below/above thresholds → BLOCKED
  - valid price → READY
  - invalid tick → BLOCKED
  - zero/negative quantity → BLOCKED
  - below minimum quantity → BLOCKED
  - invalid lot size → BLOCKED
  - BUY above max buy → BLOCKED
  - SELL above max sell → BLOCKED
  - valid BUY/SELL quantity → READY
  - missing/None constraints → BLOCKED (7 tests)
- **Tests updated:** `test_engine_interface.py` (1 test) — expectation updated for `BLOCKED` behavior.
- **M5/M6-A contract:** Unchanged.

#### Test Results (M6-B)
- `test_m6b_preflight.py`: 21/21 PASS
- `test_engine_interface.py`: 17/17 PASS
- `test_m6a_preflight.py`: 8/8 PASS
- `test_trading_state.py` (M5 regression): 16/16 PASS
- `test_engine_provider_integration.py`: 4/4 PASS
- `test_broker_manager.py`: 6/6 PASS
- `test_instrument_provider.py`: 11/11 PASS
- `test_main_order_workflow.py`: 7/7 PASS
- **Total related regression: 91/91 PASS**

#### Behavioral Contract (M6-B)
```
Missing/Unknown required constraint (lower/upper threshold, tick, min qty, lot size, max buy/sell)
    └─> OrderValidator raises OrderValidationError
            └─> OrderEngine.prepare()
                    └─> RETURN BLOCKED (mode="BLOCKED")

Invalid value (price out of range, bad tick, qty below min, above max, not multiple of lot)
    └─> OrderValidator raises OrderValidationError
            └─> OrderEngine.prepare()
                    └─> RETURN BLOCKED (mode="BLOCKED")

Valid + Known constraints
    └─> OrderValidator passes
            └─> OrderEngine.prepare()
                    └─> RETURN READY (after trading-state gate)
```

#### Out-of-Scope for M6-B
The following are explicitly **not** part of M6-B and remain for M6-C or later:
- Account Cash Availability (`tradableBalanceT1`)
- Buy Capacity via Agah (`calculatedquantity`)
- Portfolio Quantity for Sell (`numberOfShares`)
- Order Splitting
- Scheduler / Retry / Recovery

#### Note on `baseQuantity`
- `baseQuantity` does not exist in the repository (`BrokerInstrument`, API mappings, or documentation).
- Only `lot_size` exists and was validated in M6-B.
- No new field or API was added for `baseQuantity`.

---

### M6-C — Account Cash + BUY Capacity Validation (COMPLETED / Architect Approved)

#### Implementation Summary
- **Files modified:**
  - `models/order_validator.py` — Added fail-closed checks for Account Cash in BUY path:
    - `tradable_balance_t1` must be numeric (`int`/`float`), not `bool`, not `None`, not negative.
    - `required_cash = order.price * order.quantity` must be `<= tradable_balance_t1`.
  - `brokers/base.py` — Added concrete `get_buy_capacity()` method to `Broker` ABC (default: `NotImplementedError` → fail-closed for brokers that don't override).
  - `brokers/agaah/broker.py` — Implemented `get_buy_capacity()` calling `GET /api/v1/trades/calculatedquantity` with params `nscId`, `sideCode`, `fund`, `price`; validates `isSuccess`, `data` presence/numeric/non-negative; raises on any API/HTTP/network failure.
  - `core/order_engine.py` — Added `BUY` import and BUY capacity gate in `prepare()`:
    - `fund = account.tradable_balance_t1`.
    - Missing/invalid/negative `fund` → `BLOCKED`.
    - API call failure → `BLOCKED` (fail-closed).
    - `order.quantity > capacity` → `BLOCKED`.
- **Tests added:** `test_m6c_preflight.py` — 16 tests covering:
  - Account Cash (6 tests):
    - valid sufficient cash → READY
    - insufficient cash → BLOCKED
    - missing `tradableBalanceT1` → BLOCKED
    - malformed/string balance → BLOCKED
    - negative balance → BLOCKED
    - `bool` balance → BLOCKED
  - BUY Capacity (10 tests):
    - valid sufficient capacity → READY
    - insufficient capacity → BLOCKED
    - `data` == None → BLOCKED
    - missing `data` → BLOCKED
    - `isSuccess == false` → BLOCKED
    - non-numeric `data` → BLOCKED
    - API/HTTP failure → BLOCKED
    - timeout/network failure → BLOCKED
    - connection error → BLOCKED
    - SELL order skips capacity gate → READY
- **Tests updated:** `test_m6a_preflight.py`, `test_m6b_preflight.py`, `test_engine_interface.py`, `test_engine_provider_integration.py`, `test_main_order_workflow.py` — added `get_buy_capacity` to FakeBroker implementations.
- **BUY Capacity via Agah (`calculatedquantity`):** IMPLEMENTED
  - endpoint: `GET /api/v1/trades/calculatedquantity`
  - params: `nscId`, `sideCode`, `fund` (= `tradable_balance_t1`), `price`
  - response field: `data` = Agah-calculated BUY capacity
  - Architect-approved response contract (verified via Chrome DevTools)
  - No new fields added to `Account`/`Order`/`BrokerInstrument`

#### Test Results (M6-C Account Cash + BUY Capacity)
- `test_m6c_preflight.py`: 16/16 PASS
- `test_m6b_preflight.py`: 21/21 PASS
- `test_m6a_preflight.py`: 8/8 PASS
- `test_trading_state.py` (M5 regression): 16/16 PASS
- `test_engine_interface.py`: 17/17 PASS
- `test_engine_provider_integration.py`: 4/4 PASS
- `test_broker_manager.py`: 6/6 PASS
- `test_instrument_provider.py`: 11/11 PASS
- `test_main_order_workflow.py`: 7/7 PASS
- **Total related regression: 106/106 PASS**

#### Behavioral Contract (M6-C Account Cash + BUY Capacity)
```
BUY path:
    tradable_balance_t1 is None/missing
        └─> OrderValidator raises OrderValidationError
                └─> OrderEngine.prepare()
                        └─> RETURN BLOCKED (mode="BLOCKED")

    tradable_balance_t1 is bool or non-numeric
        └─> OrderValidator raises OrderValidationError
                └─> OrderEngine.prepare()
                        └─> RETURN BLOCKED (mode="BLOCKED")

    tradable_balance_t1 is negative
        └─> OrderValidator raises OrderValidationError
                └─> OrderEngine.prepare()
                        └─> RETURN BLOCKED (mode="BLOCKED")

    required_cash > tradable_balance_t1
        └─> OrderValidator raises OrderValidationError
                └─> OrderEngine.prepare()
                        └─> RETURN BLOCKED (mode="BLOCKED")

    tradable_balance_t1 valid + cash sufficient
        └─> OrderValidator passes
                └─> OrderEngine.prepare()
                        └─> BUY Capacity gate:
                            fund = tradable_balance_t1
                            broker.get_buy_capacity(nscId, sideCode, fund, price)
                                ├─ any API/HTTP/network error → BLOCKED
                                ├─ isSuccess != true → BLOCKED
                                ├─ data missing/None → BLOCKED
                                ├─ data non-numeric → BLOCKED
                                ├─ data < 0 → BLOCKED
                                └─ capacity >= 0 → compare quantity:
                                    order.quantity > capacity → BLOCKED
                                    order.quantity <= capacity → continue
                                        └─> RETURN READY
```

#### Out-of-Scope for M6-C
The following are explicitly **not** part of M6-C and remain blocked/pending:
- Portfolio Quantity for Sell (`numberOfShares`)
- Unified BUY/SELL Preflight
- Order Splitting
- Scheduler / Retry / Recovery

---

### M6-D — Portfolio Quantity / SELL Gate (COMPLETED / Architect Approved)

#### Implementation Summary
- **Files modified:**
  - `brokers/base.py` — Added `get_sell_capacity()` to `Broker` ABC (default: `NotImplementedError` → fail-closed).
  - `brokers/agaah/broker.py` — Implemented `get_sell_capacity()` calling `GET /api/v1/portfolio`, parsing `portfolio.numberOfShares`, with full validation (isSuccess, portfolio presence, numeric, non-negative) and fail-closed behavior on any API/HTTP/network failure.
  - `core/order_engine.py` — Added `SELL` import and SELL capacity gate in `prepare()` after the BUY gate: calls `broker.get_sell_capacity()`, `BLOCKED` on any exception or insufficient capacity (`order.quantity > capacity`).
- **Tests added:** `test_m6d_preflight.py` — 15 tests covering:
  - sufficient capacity → READY
  - exact quantity → READY
  - insufficient capacity → BLOCKED
  - zero quantity → BLOCKED (by existing OrderValidator)
  - API failure → BLOCKED
  - missing numberOfShares → BLOCKED
  - missing portfolio → BLOCKED
  - non-numeric → BLOCKED
  - timeout → BLOCKED
  - connection error → BLOCKED
  - negative → BLOCKED
  - BUY order skips SELL capacity gate → READY
  - SELL gate does not break BUY path → READY
  - correct arguments verification
  - M6-B max_sell check fires before SELL capacity gate → BLOCKED
- **Tests updated:** `test_engine_interface.py`, `test_m6a_preflight.py`, `test_m6b_preflight.py`, `test_m6c_preflight.py`, `test_engine_provider_integration.py`, `test_main_order_workflow.py` — added `get_sell_capacity` to FakeBroker implementations.

#### Test Results (M6-D)
- `test_m6d_preflight.py`: 15/15 PASS
- `test_m6c_preflight.py`: 16/16 PASS
- `test_m6b_preflight.py`: 21/21 PASS
- `test_m6a_preflight.py`: 8/8 PASS
- `test_trading_state.py` (M5 regression): 16/16 PASS
- `test_engine_interface.py`: 17/17 PASS
- `test_engine_provider_integration.py`: 4/4 PASS
- `test_broker_manager.py`: 6/6 PASS
- `test_instrument_provider.py`: 11/11 PASS
- `test_main_order_workflow.py`: 7/7 PASS
- **Total related regression: 123/123 PASS** (106 previous + 15 new M6-D + 2 updated interface tests)

#### Behavioral Contract (M6-D)
```
SELL path (after M6-A identity/trading-state gate, after M6-B price/quantity constraints):
    order.quantity > 0 and side == SELL
        └─> OrderEngine.prepare()
                └─> SELL Capacity gate:
                    broker.get_sell_capacity(nsc_id, side_code, fund=None, price)
                        ├─ any API/HTTP/network error → BLOCKED
                        ├─ isSuccess != true → BLOCKED
                        ├─ portfolio missing → BLOCKED
                        ├─ portfolio.numberOfShares missing/None → BLOCKED
                        ├─ portfolio.numberOfShares non-numeric → BLOCKED
                        ├─ portfolio.numberOfShares < 0 → BLOCKED
                        └─ capacity >= 0 → compare quantity:
                            order.quantity > capacity → BLOCKED
                            order.quantity <= capacity → continue
                                └─> RETURN READY

BUY path:
    get_sell_capacity is NEVER called (BUY gate uses get_buy_capacity only)
```

#### M6-D Contract Details
- **Endpoint:** `GET /api/v1/portfolio` (Architect-verified)
- **Quantity field:** `portfolio.numberOfShares`
- **Rule:** SELL allowed when `quantity <= numberOfShares`
- **Missing/invalid/API failure → BLOCKED** (fail-closed)
- `numberOfShares` is used only as the SELL gate bound; it is NOT an independent sellable quantity claim.

#### Out-of-Scope for M6-D
The following are explicitly **not** part of M6-D and remain blocked/pending:
- Unified BUY/SELL Preflight
- Order Splitting
- Scheduler / Retry / Recovery

---

### M6-E — Unified BUY/SELL Capacity Preflight (COMPLETED / Architect Approved)

#### Implementation Summary
- **Files modified:**
  - `core/order_engine.py` — Refactored the two separate `if order.side == BUY` / `if order.side == SELL` capacity blocks in `prepare()` into a single unified capacity gate:
    - Both BUY and SELL capacity calls now route through a shared `_check_capacity()` static method.
    - `_check_capacity()` encapsulates the common exception handling (`Exception → BLOCKED`, fail-closed) and quantity comparison (`order.quantity > capacity → BLOCKED`).
    - BUY path: pre-validates `fund = account.tradable_balance_t1` (None/bool/non-numeric/negative checks), then calls `broker.get_buy_capacity(nsc_id, side_code, fund, price)`.
    - SELL path: calls `broker.get_sell_capacity(nsc_id, side_code, fund=None, price)` directly.
    - Side selection uses `capacity_label` ("خرید" / "فروش") to preserve exact error messages.
- **Tests added:** None (refactor only — no new behavior).
- **Tests updated:** None (all 123 existing tests continue to pass without modification).
- **No architectural decisions added.**

#### Unified Structure
```
OrderEngine.prepare() capacity gate:
    if order.side == BUY:
        fund = account.tradable_balance_t1
        validate fund (None / bool / negative / non-numeric → BLOCKED)
        capacity_fn = lambda: broker.get_buy_capacity(nsc_id, side, fund, price)
        capacity_label = "خرید"
    else:  # SELL (guaranteed by OrderValidator: side ∈ {BUY, SELL})
        capacity_fn = lambda: broker.get_sell_capacity(nsc_id, side, fund=None, price)
        capacity_label = "فروش"

    → _check_capacity(order, broker_name, capacity_fn, capacity_label)
        ├─ capacity_fn() raises Exception → BLOCKED (fail-closed)
        ├─ order.quantity > capacity → BLOCKED
        └─ order.quantity <= capacity → fall through to Ready
```

#### Behavior Preserved
- **Gate ordering:** Identity (M6-A) → Trading State (M5/M6-A) → OrderValidator (M6-B) → Capacity (M6-C/M6-D unified) → Ready.
- **Fail-closed policy:** Any exception from `get_buy_capacity` or `get_sell_capacity` → `BLOCKED`.
- **Fund parameter:** BUY passes `fund = account.tradable_balance_t1`; SELL passes `fund = None`.
- **Error messages:** Identical to pre-refactor (verified string-for-string).
- **BUY/SELL separation:** BUY orders never call `get_sell_capacity`; SELL orders never call `get_buy_capacity`.
- **Validation-before-capacity:** All `OrderValidator` checks (including `maximum_order_quantity_for_buy`/`maximum_order_quantity_for_sell`) fire BEFORE the capacity API call.

#### Test Results (M6-E)
- `test_m6a_preflight.py`: 8/8 PASS
- `test_m6b_preflight.py`: 21/21 PASS
- `test_m6c_preflight.py`: 16/16 PASS
- `test_m6d_preflight.py`: 15/15 PASS
- `test_engine_interface.py`: 17/17 PASS
- `test_trading_state.py` (M5 regression): 16/16 PASS
- `test_engine_provider_integration.py`: 4/4 PASS
- `test_broker_manager.py`: 6/6 PASS
- `test_instrument_provider.py`: 11/11 PASS
- `test_main_order_workflow.py`: 7/7 PASS
- `test_order_build.py`: PASS
- `test_broker_dry_run.py`: PASS
- `test_smoke_import`: PASS
- **Total regression: 123/123 PASS** (all tests, no new tests added, no existing tests modified)

#### Out-of-Scope for M6-E
The following are explicitly **not** part of M6-E:
- `Broker.get_capacity()` unified method on `Broker` ABC — not implemented (Phase 2 optional, not part of this commit)
- Changes to `brokers/base.py` — unchanged
- Changes to `brokers/agaah/broker.py` — unchanged
- Changes to `OrderValidator` (`models/order_validator.py`) — unchanged
- M6-F / Order Splitting — Deferred / Future Development (out of scope per Architect decision)
- Any new endpoint or contract changes — none introduced

### M6 Overall Status
- M6 Discovery: **COMPLETE**
- M6 Architectural Scope: **DEFINED**
- M6-A Implementation: **COMPLETED** (Architect approved, pushed as `7ce09e3`)
- M6-B Implementation: **COMPLETED** (Architect approved, pushed as `84f9130`)
- M6-C Account Cash + BUY Capacity Validation: **COMPLETED** (Architect approved, pushed as `03ede4e`)
- M6-D Portfolio Quantity / SELL Gate: **COMPLETED** (Architect approved, pushed as `f3bdf1d`)
- M6-E Unified BUY/SELL Capacity Preflight: **COMPLETED** (Architect approved, pushed as `be0d0b7`)
- **M6 preflight core complete: M6-A through M6-E all implemented.**
- **M6-F / Order Splitting: Deferred / Future Development** — out of scope per Architect decision; no implementation planned at this stage.

---

## 3. Dispatch Engine Execution Roadmap

This roadmap defines the future execution of the project as a sequence of **independent, contract-based blocks**. Each block is a deliverable with defined inputs, outputs, dependencies, and acceptance criteria. Blocks are executed one at a time, each requiring Architect review and approval.

### Governing Rules

1. **The primary project goal is fixed:** Low-Latency, Configurable Order Dispatch.
2. **No block may bypass M6-A through M6-E.** Validation/preflight gates must always be preserved.
3. Every block must define: **Status → Goal → Dependencies → Contract → Acceptance Criteria → Tests → Architect Approval → Commit**.
4. Every block must be independent and deliverable on its own.
5. A new Architect must not change the contracts of prior blocks without explicit Architect approval and a recorded decision in `DECISIONS.md`.
6. No milestone outside this roadmap may be added without Architect decision.
7. **M6-F — Order Splitting** remains **Deferred / Future Development** and is not part of this execution roadmap.
8. **Real Trading remains disabled** until the final block and explicit human approval.

### Block 0 — Dispatch Architecture Foundation

**Goal:** Establish the boundaries and base contracts of the Dispatch Engine.

**Scope:**
- Define the Dispatch Engine boundary.
- Define the end-to-end order flow from Trigger to Dispatch.
- Define time-based and event-based triggers.
- Define the Account / Broker / Core boundaries.
- Define the base contracts that all later blocks depend on.

**Output:** Base architectural contract for the Dispatch Engine.

**Status:** IMPLEMENTED — committed as `7b29897` (Architect approved)

**Files added:**
- `core/dispatch_contracts.py` — Block 0 contracts: `Trigger` ABC, `TimeTrigger`/`EventTrigger` (contract-only), `ExecutionPlan`, `BrokerDispatchRequest`/`BrokerDispatchResponse`, `DispatchResult`.
- `test_block0_dispatch_contracts.py` — 11 direct contract tests (11/11 PASS).

**Constraints honored:**
- No scheduler, event bus, polling, timer, or broker implementation.
- `core/order_engine.py` NOT modified — M6-A…M6-E behavior unchanged.
- No new security abstraction, proof, token, capability, secret, guard, or wrapper.
- No new dependencies.
- `live_trading_enabled` unchanged.

**Dispatch boundary (Block 0):**
`Trigger → Planner (Block 1) → Dispatch Core (Block 2) → existing M6-A…M6-E → Broker`

**Regression:** 134/134 PASS (123 existing + 11 new Block 0 tests).

---

### Block 1 — Execution Planner

**Goal:** Convert a logical order instruction into an explicit execution plan.

**Scope:**
- Determine which orders.
- For which Accounts.
- Through which Brokers.
- With what execution order and conditions.

**Output:** Execution Plan, independent of Broker implementation.

**Dependencies:** Block 0

**Status:** COMPLETE — IMPLEMENTED, committed as `2c4e857`, pushed to `origin/master` (Architect approved)

**Commit:** `2c4e857` — `feat: implement Block 1 execution planner`

**Push:** Successful to `origin/master` (remote advanced `924475d..2c4e857`)

**Files added:**
- `core/execution_planner.py` — Block 1 planner:
  - `LogicalOrderInstruction` (frozen dataclass): plan_id, orders, conditions.
  - `PlannedOrder` (frozen dataclass): order, account_id, broker_name, sequence, conditions.
  - `ExecutionPlanner.build_plan(instruction) -> ExecutionPlan`.
  - `PlannerValidationError` for fail-closed validation.
- `test_execution_planner.py` — 26 direct tests (26/26 PASS).

**Behavior:**
- Validates the instruction; rejects empty orders, missing/blank plan_id, duplicate/negative/non-integer sequences, blank account_id/broker_name, non-dict conditions.
- Sorts planned orders by ascending `sequence` and preserves the explicit order/account/broker mapping.
- Preserves plan-level conditions and per-order conditions under `conditions["orders"][sequence]`.
- Returns the existing Block 0 `ExecutionPlan` (created_at left `None` for the Dispatch Core to stamp).
- Deterministic: same input produces equivalent plans; no wall-clock, no randomness.
- Broker-independent: references brokers by name only; never imports `brokers`, never calls any Broker API, never submits an order, never enables live trading.
- M6-A..M6-E untouched: no reference to `OrderEngine`, `prepare`, `execute`, `place_order`, `get_buy_capacity`, or `get_sell_capacity` in executable code.

**Constraints honored:**
- `core/dispatch_contracts.py` NOT modified.
- M6-A through M6-E NOT modified.
- Broker implementations NOT modified.
- No scheduler, timer, polling, async dispatch, execution tracking, latency measurement, multi-account execution, multi-broker execution, or M6-F order splitting.
- No Broker API call; no order submission; live trading remains disabled.
- No new dependencies.

**Regression:** 158/158 PASS (132 existing + 26 new Block 1 tests).

**Dispatch boundary (Block 0/1):**
`Trigger → Planner (Block 1) → Dispatch Core (Block 2) → existing M6-A…M6-E → Broker`

---

### Block 2 — Dispatch Core / Low-Latency Engine

**Goal:** Build the shared execution core of the Dispatch Engine.

**Scope:**
- Receive the Execution Plan.
- Manage the dispatch routing path.
- Perform minimal final preparation.
- Low-latency dispatch.
- Manage internal timing required by the core.
- Record base timestamps for latency measurement.
- No dependency on Timed/Burst or Event-Driven as a specific feature.

This block is the common base for Blocks 3 and 4.

**Output:** Shared low-latency dispatch core.

**Dependencies:** Block 1

**Status:** IMPLEMENTED

**Files:**
- core/dispatch_core.py â Dispatch Core + LowLatencyDispatchCore alias: dispatch(plan) routes each sequence through BrokerManager -> InstrumentProvider -> BrokerDispatchRequest envelope -> OrderEngine.execute_by_ins_code (M6-A..M6-E intact). Binding from plan.conditions['binding']; live always False; all failures fail-closed mode=BLOCKED.
- core/execution_planner.py â records per-order binding under plan.conditions['binding'][sequence] = {account_id, broker_name}.
- `test_dispatch_core.py` — 17 tests / 49 assertions.

**Test results:** Block 2: 17 passed. Full suite: 175 passed.

---

#### Block 2 Contract Details

**Contract Alignment:**
Block 2 aligns with the complete Dispatch Core contract defined in Block 0 (`core/dispatch_contracts.py`). The contract is unchanged; Block 2 is responsible for implementing the execution path that uses these contracts.

**Input (from Block 1 Planner):**
- `ExecutionPlan` — pure data contract containing:
  - `orders`: List[Order]
  - `accounts`: List[Account]
  - `broker_names`: List[str]
  - `execution_order`: List[int]
  - `conditions`: dict (plan-level + per-order under `conditions["orders"][sequence]`)
  - `plan_id`: Optional[str]
  - `created_at`: Optional[datetime] — the plan creation timestamp, set by the Planner; distinct from any dispatch-level timestamp

**Input Binding Note:**
The direct pairing of each Order → Account → Broker is carried by `PlannedOrder` (Block 1) during planning. In the current repository state, `ExecutionPlan` stores `orders`, `accounts`, and `broker_names` as separate lists; the per-order account/broker binding is not yet re-expressed as a direct field on `ExecutionPlan`. Block 2 must not assume the binding is directly available on the plan; it must derive or preserve the binding from the planning stage.

**Output:**
- `DispatchResult` — dispatch-level status (success, sent, mode, message, broker_name, order_count, trace_id)
- `BrokerDispatchRequest` / `BrokerDispatchResponse` — normalized envelopes between Dispatch Core and Broker

**Account Binding:**
- Accounts must be pre-identified for execution before dispatch.
- The Dispatch Core must NOT re-select, re-resolve, filter, or rebalance accounts during dispatch.
- The Dispatch Core does NOT call `broker.get_account()` or any account discovery API.
- Multi-Account lifecycle coordination is out of scope for Block 2 and remains for Block 6.

**Broker Binding:**
- Brokers must be pre-identified for execution before dispatch.
- The Dispatch Core must NOT re-select or invent broker instances, create new sessions, or modify broker lifecycle during dispatch.
- Broker resolution from names to instances uses the existing `BrokerManager` (no new broker abstraction).

**BrokerDispatchRequest Boundary:**
- `BrokerDispatchRequest` is the defined normalized contract envelope between Dispatch Core and Broker.
- The Dispatch Core must establish the real dispatch path that uses this contract.
- The actual Broker Adapter consuming `BrokerDispatchRequest` is NOT yet implemented; Block 2 must define how the real path will use this contract.
- The Dispatch Core must NOT construct broker-specific HTTP payloads, headers, or auth tokens.

**M6 Preservation:**
- Block 2 MUST NOT bypass M6-A through M6-E.
- Block 2 must use the existing `OrderEngine` execution path.
- All preflight gates (M6-A identity/trading-state, M6-B price/quantity constraints, M6-C BUY capacity, M6-D SELL capacity, M6-E unified capacity) remain intact.
- The specific method calls (`prepare()`, `execute()`, `execute_by_ins_code()`) that Block 2 uses to enter the `OrderEngine` path are not yet decided and are not recorded here.

**Sequence:**
```
ExecutionPlan (from Block 1)
    │
    ▼
Dispatch Core:
    1. For each sequence in plan.execution_order (ascending):
       a. Resolve broker instance via BrokerManager
       b. Resolve instrument via existing InstrumentProvider path
       c. Build BrokerDispatchRequest (normalized envelope)
       d. Delegate through the existing OrderEngine execution path — which runs:
          - M6-A: identity + trading-state gate
          - M6-B: price/quantity constraints
          - M6-C/D/E: capacity gates
          - Broker.place_order() (dry-run if live=False)
       e. Collect BrokerDispatchResponse
    2. Build DispatchResult
    3. Return DispatchResult
```

**Failure Handling:**
- Any exception during dispatch → fail-closed: `DispatchResult.success=False`, `mode="BLOCKED"`.
- `OrderEngine` execution results with `mode="BLOCKED"` on preflight failure are propagated by the Dispatch Core.
- Network errors, timeouts, API failures → caught at Broker Adapter level, normalized, and reported via `BrokerDispatchResponse.success=False`.
- The Dispatch Core does NOT swallow errors; it records them in `DispatchResult.message`.

**Traceability:**
- `trace_id` is generated by the Dispatch Core for each dispatch attempt.
- `trace_id` is propagated in `BrokerDispatchRequest.trace_id`.
- All logs, error messages, and `DispatchResult` include `trace_id`.
- `BrokerDispatchResponse` may carry `broker_order_id` for downstream tracking.

**Dry-Run:**
- `live` in `BrokerDispatchRequest` is always False during development.
- The Dispatch Core does NOT enable live trading.
- Dry-run is the only mode until Block 10 (Controlled Live Execution) and explicit human approval.

**Out of Scope for Block 2:**
- Scheduler, timer, polling, or event bus — Block 3/4 handle these.
- Multi-account execution coordination — Block 6.
- Multi-broker routing logic — Block 7.
- Latency measurement and optimization — Block 8 (base timestamps recorded in Block 2, analysis in Block 8).
- Order splitting (M6-F) — Deferred.
- Real trading — Block 10.
- Any new broker abstraction, security mechanism, token, proof, or guard.
- Any modification to M6-A through M6-E.
- Any change to `core/dispatch_contracts.py`.

---

### Block 3 — Timed / Burst Dispatch

**Goal:** Implement dispatch within a configurable time window.

**Scope:**
- Configurable Start Time.
- Configurable End Time.
- Configurable interval / gap between orders.

Note: Example values such as `50ms` and `10 seconds` are illustrative only and must not be hard-coded.

**Output:** Configurable dispatch within a time window.

**Dependencies:** Block 2

**Status:** NOT STARTED

---

### Block 4 — Event-Driven Dispatch

**Goal:** Enable dispatch triggered by confirmed events.

**Scope:**
- `Permitted`
- `Permitted-Reserved`
- Other verified triggers accepted in the future.

This block must use the Dispatch Core and must not depend on Timed/Burst.

**Output:** Event-driven dispatch, independent of fixed time scheduling.

**Dependencies:** Block 2

**Status:** NOT STARTED

---

### Block 5 — Execution Tracking + Feedback

**Goal:**

Block 5 مسئول دریافت و ثبت مستقل نتیجه هر سفارش و تولید Stop Signal اختیاری است؛ بدون انتظار synchronous برای نتیجه هر سفارش.

**Architecture Principles:**

- سفارش‌ها باید بتوانند به‌صورت رگباری و مستقل ارسال شوند.
- دریافت نتیجه یک سفارش نباید به‌صورت پیش‌فرض ارسال سفارش‌های بعدی را متوقف کند.
- نتیجه هر سفارش باید مستقل ثبت و قابل پیگیری باشد.
- در حالت شرطی، با دریافت اولین نتیجه موفق «ثبت در هسته معاملات»، Stop Signal فعال می‌شود.
- Stop Signal فقط جلوی ارسال سفارش‌های جدید بعدی را می‌گیرد.
- سفارش‌هایی که قبل از رسیدن Stop Signal ارسال شده‌اند لغو یا متوقف نمی‌شوند.
- Block 5 نباید Scheduler، Timer، Polling Loop یا مکانیزم جدید ارسال رگباری ایجاد کند.
- مسئولیت سرعت و زمان‌بندی ارسال در Block 3/4 باقی می‌ماند.
- `getorderposition` و `cancel` فعلاً خارج از هسته Block 5 هستند و فقط با Task مستقل آینده اضافه می‌شوند.

**Task 1 — Order Result Tracking**

**Status:** COMPLETED

هدف:
ثبت و تشخیص مستقل نتیجه هر سفارش پس از ارسال، با تمرکز فعلی روی تشخیص «ثبت موفق در هسته معاملات».

پیاده‌سازی (Execution Tracker Core):
- `ExecutionStatus`: `PENDING`, `SUBMITTED`, `REGISTERED`, `FAILED`, `CANCELLED`
- `ExecutionTracker.register(execution_id)` — ثبت execution جدید با وضعیت `PENDING`
- `ExecutionTracker.update_status(execution_id, status)` — تغییر وضعیت execution موجود
- `ExecutionTracker.get_status(execution_id)` — دریافت وضعیت فعلی execution
- بدون اتصال به Broker/Exchange، بدون تغییر Dispatch/Strategy، بدون UI

**Files added:**
- `core/execution_tracker.py`
- `test_execution_tracker.py`

**Tests:**
- Task tests: 9/9 passed
- Regression: 54/54 passed (`test_execution_planner.py`, `test_dispatch_core.py`, `test_block0_dispatch_contracts.py`)

خارج از Scope:
- Fill
- average fill price
- execution ID
- مدیریت کامل lifecycle سفارش

**Task 2 — Result Collection**

Status: COMPLETED

هدف:
اتصال یک connector کوچک به `ExecutionTracker` (Task 1) برای ثبت نتیجه‌ی موجود Dispatch در Tracker — بدون Broker/API/IO/clock/persistence.

پیاده‌سازی (`core/block5_task2.py`):
- `collect_result(tracker, execution_id, result) -> ExecutionStatus`
- `collect_result_safe(...)` — fail-closed variant returning `None` on error.
- Mapping: `DispatchResult.success=True` → `ExecutionStatus.REGISTERED`;
  `DispatchResult.success=False` → `ExecutionStatus.FAILED`.
- Fail-closed: unknown/blank `execution_id` and non-`DispatchResult` input raise
  `ExecutionTrackerError` (delegated to `ExecutionTracker.update_status`).
- Uses no broker, API, IO, clock, or persistence.

**Files added:**
- `core/block5_task2.py`
- `test_block5_task2.py`

**Tests:**
- Task tests: 9/9 passed
- Regression: 23/23 offline suites passed (0 failures)

 خارج از Scope:
- Fill / Partial Fill
- scheduler/timer/polling
- persistence
- تغییر `ExecutionTracker`، `DispatchCore`، `DispatchResult`، یا Brokerها

**Task 3 — Conditional Stop Signal**

Status: COMPLETED

هدف:
پشتیبانی از شرط اختیاری مانند «تا اولین ثبت موفق ادامه بده».

پیاده‌سازی (`core/block5_task3.py`):
- `StopSignal(enabled: bool = False)` — حالت پیش‌فرض `enabled=False` (ادامه ارسال؛ Stop Signal هرگز فعال نمی‌شود).
- `observe(result: DispatchResult) -> bool` — فقط در حالت `enabled=True` و روی اولین `success=True`، Stop Signal فعال می‌شود و latches می‌کند.
- `is_active` / `should_continue()` — قابل تشخیص بودن وضعیت پس از فعال‌شدن.
- `activation_count` — تعداد دفعات فعال‌شدن Stop Signal (رویداد فعال‌سازی)، نه تعداد successهای مشاهده‌شده.
- `reset()` — غیرعال‌سازی بدون تغییر `enabled`.
- رفتار fail-closed: ورودی غیر-`DispatchResult` → `StopSignalError`؛ `enabled` غیر-bool → `StopSignalError`.
- بدون Broker/API/IO/clock/persistence/scheduler.

رفتار:
- شرط خاموش → نتیجه موفق باعث Stop Signal نمی‌شود؛ جریان ارسال طبق Timing/Burst موجود ادامه پیدا می‌کند.
- شرط روشن + نتیجه موفق → Stop Signal روی اولین success فعال می‌شود.
- شرط روشن + نتیجه ناموفق → Stop Signal فعال نمی‌شود.
- فقط ارسال‌های جدید بعد از فعال‌شدن Stop Signal متوقف می‌شوند.
- سفارش‌هایی که قبل از Stop Signal ارسال شده‌اند ل Moff نمی‌شوند و تحت تأثیر قرار نمی‌گیرند.
- نتیجه هر سفارش همچنان مستقل است.

اتصال به Dispatch واقعی:
- اتصال Stop Signal به مسیر واقعی Dispatch (Block 2/3/4) در **Task 4** انجام می‌شود.
- Task 3 صرفاً هسته/گیت را فراهم می‌کند؛ هیچ اتصالی به Dispatch Core، Block 3، Block 4، Scheduler یا UI ایجاد نشده است.

**Files added:**
- `core/block5_task3.py`
- `test_block5_task3.py`

**Tests:**
- Task tests: 13/13 passed
- Regression: 24/24 offline suites passed (0 failures)

 خارج از Scope:
- اتصال به Dispatch واقعی (Task 4)
- Fill / Partial Fill
- scheduler/timer/polling
- persistence
- تغییر `ExecutionTracker`، `DispatchCore`، `DispatchResult`، یا Brokerها

**Task 4 — Integration with Dispatch Flow**

هدف:
اتصال Tracking و Stop Signal به مسیر واقعی ارسال موجود، بدون تغییر مسئولیت‌های Block 3، Block 4 یا Dispatch Core.

الزام:
هیچ لایه موازی یا مکانیزم ارسال جدید خارج از معماری فعلی ایجاد نشود.

This block must integrate with both Timed/Burst and Event-Driven dispatch paths without owning dispatch responsibility.

| Task | هدف | مسئولیت | خارج از Scope |
|---|---|---|---|
| Task 1 | ثبت و تشخیص مستقل نتیجه هر سفارش پس از ارسال | تشخیص نتیجه ثبت سفارش | Fill، average fill price، execution ID، lifecycle کامل |
| Task 2 | جمع‌آوری نتایج سفارش‌های ارسال‌شده | نگهداری نتایج بدون توقف جریان ارسال | توقف ارسال بعدی |
| Task 3 | فعال‌سازی Stop Signal شرطی | توقف فقط ارسال‌های جدید بعد از اولین موفقیت | لغو سفارش‌های قبلیٕاتصال به Dispatch واقعی (Task 4)  |
| Task 4 | اتصال Tracking به مسیر Dispatch موجود | اتصال بدون تغییر معماری | ایجاد Scheduler یا Dispatch جدید |

**Task 4 — Implementation (IMPLEMENTED — tests PASS; Architect verification pending)**

پیاده‌سازی (`core/block5_task4.py`):
- `DispatchIntegration(dispatch_core, tracker=None, stop_signal=None)` — یک boundary **اختیاری** که با Dispatch Core سازگار است (`dispatch(plan)` دارد)، پس همان connector موجود Block 4 بدون هیچ تغییری می‌تواند آن را بهکار بگیرد.
- `stop_guard(stop_signal) -> GuardDecision` — تنها شرط Send Path: `ALLOW` وقتی Stop Signal فعال نیست، `STOP` وقتی فعال است.
- `DispatchIntegration.dispatch(plan, execution_id=None) -> DispatchResult` — **SEND PATH**:
  1. Guard (فقط بررسی Stop Signal)
  2. ثبت execution جدید با وضعیت `PENDING` در `ExecutionTracker`
  3. واگذاری بدون تغییر به `DispatchCore.dispatch(plan)`
- `DispatchIntegration.record_result(execution_id, result) -> ExecutionStatus` — **RESULT PATH** مستقل:
  `DispatchResult → collect_result(...) → ExecutionTracker → StopSignal.observe(...)`
- در حالت STOP: `DispatchCore.dispatch` اصلاً اجرا نمی‌شود، هیچ executionی ثبت نمی‌شود، هیچ سفارش قبلی cancel یا تغییر نمی‌شود، و `DispatchResult(mode="STOPPED", success=False, sent=False)` برگردانده می‌شود.
- Result Path داخل Send Path نیست: ارسال هیچ‌وقت منتظر نتیجه سفارش قبلی نمیماند. نتیجه‌ها می‌توانند خارج از ترتیب برسند (۳، ۱، ۴، ۲) و نتیجه‌های دیررس پس از فعال‌شدن Stop همچنان ثبت می‌شوند.
- Fail-closed: plan نامعتبر، `execution_id` نامعتبر/تکراری، و `execution_id` ناشناخته در Result Path → استثنا قبل از هر ارسال (بدون تغییر در tracker / Stop Signal).
- نتیجهی synthetic با `mode="STOPPED"` هرگز در Result Path قابل ثبت نیست (استثنا، بدون هیچ تغییری در tracker و Stop Signal): dispatch bypass‌شده execution ندارد، پس نمی‌تواند به یک execution قبلی (مثلاً از طریق `last_execution_id`) نسبت داده شود. مسیر Result فقط برای dispatchهای واقعاً صادرشده معتبر است.
- بدون Scheduler/Timer/Polling/Clock/IO/Broker و بدون هیچ تغییری در `DispatchCore`، `core/block4_task3.py`، `ExecutionTracker`، `collect_result`، `StopSignal`، یا M6-A…M6-E.

الگوی اتصال:
```text
Block 4 → connect_plan_to_dispatch(...) → DispatchIntegration → guard → DispatchCore.dispatch(plan)
```

بدون Integration رفتار قبلی حفظ شده است: callerهای فعلی همان `DispatchCore` را به `connect_plan_to_dispatch` می‌دهند و رفتار (بدون gating و بدون tracking) دقیقاً مثل قبل است.

**Files added:**
- `core/block5_task4.py`
- `test_block5_task4.py`

**Tests:**
- Task tests: 23/23 PASS (`python test_block5_task4.py`) — شامل تست ممنوعیت ثبت نتیجه‌ی `STOPPED` روی یک execution قبلی.
- Regression: Block 0/1/2/3/4/5 + M6 offline suites → 282/282 PASS (161 + 121)

نکات نیازمند تأیید معمار (Architect review points):
- mode جدید `STOPPED` برای dispatch bypass‌شده (متمایز از `ALL_PROCESSED` / `NO_ORDERS` / `BLOCKED`).
- تخصیص `execution_id` در Integration (تولید uuid وقتی caller مقداری نمی‌دهد) و یک execution record به‌ازای هر dispatch call.
- خروجی connector همچنان `dispatch_called=True` را برای dispatch متوقف‌شده برمی‌گرداند («رسیدن به entry point»)؛ توقف واقعی از `mode="STOPPED"` یا `integration.is_stopped` قابل تشخیص است.

**Dependencies:** Block 2, Block 3, Block 4

**Status:** IN PROGRESS (Task 1 COMPLETED; Task 2 COMPLETED; Task 3 COMPLETED; Task 4 IMPLEMENTED — tests PASS 23/23; Architect verification pending)

---

### Block 6 — Multi-Account Execution

**Goal:** Execute one Execution Plan across multiple Accounts.

**Scope:**
- Multiple Accounts from one Broker.
- Coordinated yet independent execution per Account.
- Preserve Account isolation and Account contracts.

**Output:** Execution of one order plan across multiple accounts.

**Dependencies:** Block 5

**Status:** COMPLETED — all Tasks 6.1–6.7 implemented, tested, and committed.

#### هدف معماری

Block 6 باید امکان اجرای مستقل سفارش‌ها برای چند حساب را فراهم کند.

اصل اصلی:

> هر سفارش از لحظه ایجاد تا Dispatch و Execution Tracking باید هویت حساب مشخص و مستقل خود را حفظ کند.

مثال مرجع:

* Account 1 → Symbol A
* Account 2 → Symbol B

این دو سفارش باید کاملاً مستقل باشند و اطلاعات، مسیر اجرا و وضعیت آن‌ها با یکدیگر اشتباه نشود.

#### Final Architecture (Block 6)

**Account-aware routing:**
- `ExecutionPlanner.build_plan()` binds each `PlannedOrder` to an explicit `account_id` and `broker_name`.
- `plan.conditions["binding"][sequence]["account_id"]` is the single source of truth for account identity; no fallback to `accounts[0]`, symbol, broker, index, or default.
- `plan.account_routes` maps `account_id → broker_name` for the routing stage.
- `DispatchCore.dispatch()` resolves broker instances via `BrokerManager.get(broker_name)` using the route from `account_routes`; it never re-selects or invents accounts/brokers.
- `DispatchIntegration.dispatch()` resolves account bindings for every sequence before registering anything, then delegates to `DispatchCore.dispatch(plan)` unchanged.

**Per-order tracking with `(execution_id, sequence)`:**
- One execution record per dispatch call, registered as `PENDING` before the order is sent.
- One order record per sequence, keyed by `(execution_id, sequence)`, carrying the bound `account_id` as the higher-level identity.
- No parallel execution id is created; the existing dispatch `execution_id` is reused.
- `record_order_result(execution_id, sequence, result)` updates only that single order's status; other orders (same account, same broker, same symbol) are untouched.
- Results may arrive in any order; final state is deterministic.

**StopPolicy: `NONE / ACCOUNT / GLOBAL`:**
- `StopBrakePolicy` (`core/block6_task6.py`) reuses the existing `StopSignal` gates.
- `NONE` — no brake is ever activated by a per-order result.
- `ACCOUNT` — the first successful `REGISTERED` result of an account brakes THAT account only; other accounts keep dispatching. A single plan mixing a braked account with a non-braked one is not sent at all (atomic dispatch unit).
- `GLOBAL` — the first successful `REGISTERED` result of ANY account brakes the whole run.
- Only a successful `REGISTERED` result activates a brake; a `FAILED` result never stops anything.
- A brake only gates FUTURE dispatches; already-sent orders are never cancelled or modified.
- `account_id` passed to the policy comes ONLY from the binding of that same sequence.

**Preservation of Account / Order / Broker / Symbol independence:**
- Account identity is never a symbol, broker, or order field.
- Each order's symbol, quantity, and price are preserved independently.
- Broker isolation: each call uses the correct broker for its account.
- Symbol isolation: each order's `nsc_id` stays intact.
- Order isolation: per-order quantities and prices are preserved; records are not replaced.

#### Task 6.1 — Account Model
**Status:** COMPLETED — committed as `62137a8` (`feat: add account identity model for Block 6`).

#### Task 6.2 — Account Context
**Status:** COMPLETED — committed as `e0abe3f` (`test: verify account context propagation in Block 6`).

#### Task 6.3 — Account-Aware Dispatch
**Status:** COMPLETED — committed as `88d6115` (`feat: add account-aware dispatch routing`).

#### Task 6.4 — Multi-Account Execution
**Status:** COMPLETED — committed as `de10718` (`test: verify multi-account execution in Block 6`).

#### Task 6.5 — Account-Aware Tracking
**Status:** COMPLETED — committed as `9bd2dfb` (`feat: add account-aware execution tracking`).

#### Task 6.6 — Stop/Brake Policy
**Status:** COMPLETED — committed as `aa0d322` (`feat: add multi-account stop brake policy`).

#### Task 6.7 — Integration & Regression
**Status:** COMPLETED — tests fixed and verified (10/10 scenarios PASS).

#### مرز Block 6

Block 6 فلانی فقط مسئول **Account-aware Execution** است.

موارد زیر خارج از محدوده Block 6 هستند:

* Strategy
* Portfolio Management
* Risk Management
* مدیریت سرمایه
* UI کامل حساب‌ها
* گزارش‌گیری پیشرفته

#### قواعد اجرای این Roadmap

هر Task باید به‌صورت مستقل، کوچک و قابل‌تست پیاده‌سازی شود.

معماری Taskها از همین سند مشخص است و Agent نباید معماری جایگزین یا abstraction جدیدی ایجاد کند مگر اینکه در مستندات موجود پروژه برای سازگاری با معماری فعلی لازم باشد.

#### Block 6 Commit History

| Task | Commit | Description |
|------|--------|-------------|
| 6.1 | `62137a8` | feat: add account identity model for Block 6 |
| 6.2 | `e0abe3f` | test: verify account context propagation in Block 6 |
| 6.3 | `88d6115` | feat: add account-aware dispatch routing |
| 6.4 | `de10718` | test: verify multi-account execution in Block 6 |
| 6.5 | `9bd2dfb` | feat: add account-aware execution tracking |
| 6.6 | `aa0d322` | feat: add multi-account stop brake policy |
| 6.7 | (uncommitted) | test fixes: S3/S8/S9/S10 assertions corrected |

#### Final Regression Result

**366 passed** — full test suite green after Block 6 completion.

---

### Block 7 — Multi-Broker Execution

**Goal:** Support multiple Brokers simultaneously, so that different Accounts can execute orders on different Brokers and the core remains independent of any single Broker implementation.

**Scope:**
- Multiple Brokers.
- Multiple Accounts across multiple Brokers.
- Preserve Broker abstraction.
- Dispatch Core must not depend on any single Broker implementation.
- Multi-Broker Execution only.

**Out of Scope (for Block 7):**
- Live Trading.
- Strategy.
- Risk Management.
- Latency Optimization.
- Stress Testing.

**Output:** Multi-Account / Multi-Broker Dispatch.

**Dependencies:** Block 6

**Status:** NOT STARTED

#### Task 7.1 — Broker Infrastructure Audit & Contract
**Status:** COMPLETED — Audit approved; documentation pending commit

Audit of the current broker infrastructure has been completed and approved. Findings:

- **Broker contract** (`brokers/base.py`): Reviewed. Abstract methods: `name`, `login()`, `get_account()`, `place_order()`, `cancel_order()`. Non-abstract method `get_trading_state(nsc_id) → TradingState` with behavioral guidance in docstring (broker should return `UNVERIFIED` or raise `TradingStateUnavailable` when no reliable source). `get_buy_capacity()` / `get_sell_capacity()` raise `NotImplementedError` by default (fail-closed).
- **InstrumentProvider contract** (`brokers/base.py`): Reviewed. Abstract methods: `get_instrument(ins_code) → Tuple[Instrument, BrokerInstrument]` (raises `InstrumentLookupError` on failure). `get_nsc_id(ins_code) → Optional[str]` — can return `None` or raise `InstrumentLookupError` depending on implementation policy per docstring. `refresh_cache() → None`.
- **DispatchCore → BrokerManager → Broker/InstrumentProvider path** (`core/dispatch_core.py`): Reviewed end-to-end. `DispatchCore.dispatch()` pre-resolves brokers via `BrokerManager.get()`, resolves providers lazily via `BrokerManager.get_instrument_provider()`, builds `BrokerDispatchRequest`, and delegates to `OrderEngine.execute_by_ins_code()`.
- **Agah dependencies** identified and documented: `brokers/manager.py` hardcodes `AgaahBroker` registration and `AgaahInstrumentProvider` creation; `brokers/agaah/broker.py` and `brokers/agaah/instrument_provider.py` contain Agah-specific API details and mapping logic.
- **Multi-Broker Compatibility:** Base contracts (`Broker`, `InstrumentProvider`) are structurally compatible with a second Broker (generic ABCs, dict-based storage, name-based resolution). Limitation: `BrokerManager` currently hardcodes only `AgaahBroker` / `AgaahInstrumentProvider`.
- **No new architecture** was created in this task.
- **No code changed.**

#### Task 7.2 — Generic Multi-Broker Manager
Prepare BrokerManager to manage multiple independent Brokers without coupling to any single Broker implementation. Broker selection must come from an explicit route, never from a hardcoded default.

#### Task 7.3 — Broker-Specific Instrument Provider
**Status:** COMPLETED — Architect approved; tests verified; committed.

InstrumentProviderها از نظر Broker instance مستقل هستند. Mapping هر Provider مستقل است.

برای `ins_code = TEST-001` با موفقیت اثبات شده:
```
Provider A → A-TEST-001
Provider B → B-TEST-001
```

- تغییر Mapping A روی B اثر نمی‌گذارد.
- تغییر Mapping B روی A اثر نمی‌گذارد.
- Cache Providerها مستقل است.
- تست‌های قبلی `AgaahInstrumentProvider` همچنان PASS شده‌اند.
- هیچ production code تغییر نکرده است.
- Fake Provider فقط در تست و کاملاً offline استفاده شده است.
- این Task Broker دوم واقعی اضافه نمی‌کند؛ Broker دوم واقعی متعلق به Task 7.4 است.

#### Task 7.4 — Second Broker Stub
**Status:** COMPLETED — Architect approved; tests verified.

Second Broker Stub با نام `"فیک"` ایجاد و تست شد. این Stub کاملاً offline و deterministic است.

- Stub کاملاً offline است: هیچ Network/API/Login/Credential/Live Trading ندارد.
- `FakeInstrumentProviderB(broker)` قرارداد سازنده مشخص دارد — فقط `broker` آرگومان اجباری است.
- `InstrumentLookupError` مستقیماً از `brokers.base` استفاده می‌شود. هیچ import از `brokers.agaah.*` مجاز نیست.
- Mapping:
  `TEST-001 → B-TEST-001`
- `tse_id == TEST-001`
- Broker و Provider دوم از طریق `BrokerManager.register()` قابل ثبت و resolve هستند.
- Provider B به همان `FakeBrokerB` instance وصل است (`provider._broker is fake_broker`).
- Cache Provider B مستقل از Provider A است (`_cache` و `_nsc_cache` جداگانه).
- `place_order(..., live=False)` فقط DRY_RUN است (`sent == False`).
- 12 تست اختصاصی Task 7.4 PASS شده‌اند.
- regression تست‌های 7.2 و 7.3 نیز PASS شده‌اند.
- در مجموع: `60 passed, 0 failed`
- هیچ production code تغییر نکرده است.
- Task 7.4 فقط Second Broker Stub را اثبات می‌کند.
- Multi-Broker Dispatch متعلق به Task 7.5 است و هنوز شروع نشده.

#### Task 7.5 — Multi-Broker Dispatch Routing Proof (COMPLETED — Architect Approved)

Proved that each Order is sent through the correct Broker based on its own Broker binding. An Order bound to Broker A is never sent through Broker B, regardless of dispatch order or account count.

**Routing proof (A/B/A):**
```text
Sequence 1 → BrokerA (instance verified) → TEST-A
Sequence 2 → BrokerB (instance verified) → TEST-B
Sequence 3 → BrokerA (instance verified) → TEST-C
```

**Routing path verified:**
```text
ExecutionPlan
    → conditions["binding"]
    → account_routes
    → DispatchCore.dispatch()
    → BrokerManager.get(broker_name)
    → correct Broker instance
    → OrderEngine.execute_by_ins_code(...)
```

**Key verifications:**
- Broker instance identity (not just name) confirmed for each order.
- Order independence proven: A→B→A pattern, not A→A→A or A→B→B.
- Same symbol / different brokers: two orders with same nsc_id routed to different brokers correctly.
- Unknown Broker → BLOCKED (fail-closed, no fallback).
- Route mismatch (binding ≠ account_routes) → BLOCKED (execute_by_ins_code NOT called).
- Missing account route → BLOCKED (execute_by_ins_code NOT called).
- Broker instance isolation: FakeBrokerA and FakeBrokerB are distinct instances.
- `live=False` preserved; no Live Trading executed.

**Tests:**
- Dedicated Task 7.5 tests: `9 passed`
- Regression tests (7.2, 7.3, 7.4): `60 passed`
- Total: `69 passed, 0 failed`

No production code changed. Task 7.5 only proves correct Broker routing. Multi-Account + Multi-Broker integration belongs to Task 7.6 (NOT STARTED).

#### Task 7.6 — N Account / N Broker Integration Proof

**وضعیت:**
```text
7.6-L1 = COMPLETED
7.6-L2 = COMPLETED
7.7   = COMPLETED
Block 7 = COMPLETED
```

##### 7.6-L1 — Layer 1: N Account / N Broker Foundation

* Layer 1 با موفقیت تکمیل و توسط Architect تأیید شده است.
* هدف Layer 1: اثبات Foundation برای `N Account / N Broker`.
* Accountها فقط به‌صورت `models.account.Account` object در تست ساخته شدند.
* هیچ `AccountRegistry` یا `AccountManager` جدید ایجاد نشد.
* Account → Broker binding از طریق قرارداد فعلی `ExecutionPlan` بررسی شد:
  * `account_routes`
  * `conditions["binding"]`
* سناریوهای `N=1`, `N=2`, `N=10` اجرا شدند.
* سناریوی اصلی `10 Broker / 20 Account` اجرا شد.
* چند Account با یک Broker مشترک تست شد.
* Account identity مستقل و Broker instance identity مستقل اثبات شد.
* Unknown Broker → fail-closed / BLOCKED بدون fallback.
* Missing Account route → fail-closed / BLOCKED بدون fallback.
* Conflicting binding → fail-closed مطابق قرارداد موجود.
* هیچ production code تغییر نکرد.
* فقط `test_block7_task6_layer1.py` اضافه شد.
* تعداد تست‌های Layer 1: `10`
* Regression تست‌های قبلی نیز PASS شدند.
* مجموع واقعی: `79 passed, 0 failed`

##### 7.6-L2 — Layer 2: Account + Broker + Order + Instrument Integration Proof

**Commit:** `a6a3a12`

**Task tests:** `23 passed`

**Full regression:** `456 passed`

**Production changes:** none

**نتایج اثبات:**
* اثبات ترکیب Account + Broker + Order + Instrument
* اثبات استقلال بین حساب‌ها و بروکرها
* اثبات mapping مستقل Instrument برای بروکرهای مختلف
* اثبات fail-closed و نبود cross-routing / fallback
* بدون تغییر production code
* بدون Real Trading

### مرز Block 7
* Block 7 = COMPLETED
* All tasks 7.1 through 7.7 are COMPLETED. Block 7 is ready for closing.

#### Task 7.7 — Integration, Regression & Documentation

**وضعیت:** COMPLETED

**End-to-End test:** `test_block7_task7.py` — 5 tests, all PASSED

**Full regression:** `456 passed`

**Production code changes:** none

**Real Trading:** none (live=False throughout, Fake brokers/providers only)

**Multi-Account / Multi-Broker:** COMPLETED — N Account / N Broker with independent instrument mapping verified end-to-end

**Layer 1:** COMPLETED (`test_block7_task6_layer1.py`)

**Layer 2:** COMPLETED (`test_block7_task6_layer2.py`)

**Block 7:** COMPLETED — ready for closing. All Block 1 through Block 6 behavior remains intact.

#### Block 7 Commit History

| Task | Commit | Description |
|------|--------|-------------|
| 7.1 | 70ccda3 | COMPLETED — Broker infrastructure audit approved and documented |
| 7.2 | 7974894 | COMPLETED — Generic Multi-Broker Manager implemented |
| 7.3 | 39f7594 | COMPLETED — Broker-specific InstrumentProvider isolation verified |
| 7.4 | 8c2a047 | COMPLETED — Second Broker offline stub verified |
| 7.5 | cf84494 | COMPLETED — Multi-Broker Dispatch routing verified |
| 7.6-L1 | a9e3b9a | COMPLETED — Layer 1 N Account / N Broker foundation verified |
| 7.6-L2 | a6a3a12 | COMPLETED — Layer 2 Account+Broker+Order+Instrument integration proof |
| 7.7 | 3b9502d | COMPLETED — End-to-End integration, regression, and documentation |

---

### Block 8 — Latency Measurement & Optimization

**Goal:** Analyze recorded timestamps and optimize based on real data.

**Scope:**
- This block does **not** start instrumentation from scratch; base instrumentation must already exist in Block 2.
- Analyze recorded timestamps.
- Measure end-to-end latency.
- Identify bottlenecks.
- Investigate VPS / hosting location, network, connection method, and other factors affecting latency.
- Data-driven optimization, not guessing.

**Dependencies:** Block 7

**Status:** COMPLETED — Task 8.1, 8.2, 8.3, 8.4, and 8.5 completed. Tasks 8.3 Phase B read-only tool implemented but **not executed** with real broker credentials/network; no real latency values were reported.

---

**Task 8.1 Audit:** Complete. See `audit_block8_task8_1.md` for full findings. Key facts: only DispatchTrace.start_time/end_time via datetime.now() exists as base instrumentation; no per-order timing, no latency computation, no high-res timers, no timing propagation to DispatchResult, and dead timestamp fields in ExecutionRecord.

**Task 8.2 — Internal Dispatch Latency Measurement:** COMPLETE.

Measurement only. No optimization was performed, no execution behavior was changed, and Broker / API / network latency separation was **not** implemented (that remains Task 8.3).

**What was measured (per dispatch and per order):**

- Dispatch level: `dispatch_start`, `dispatch_end`, total elapsed `dispatch_duration`, plus the existing `trace_id`.
- Per order, independently: `sequence`, `account_id`, `broker_name`, `ins_code`, the internal stage timings, and the existing `OrderExecutionResult` (held by reference).
- Only the four existing `DispatchCore` internal stages:
  1. `plan_item` — existing `_plan_item(...)`
  2. `plan_account` — existing `_plan_account(...)`
  3. `instrument_resolution` — existing `_resolve_instrument(...)`
  4. `order_engine_path` — existing `_execute_single_order(...)`

`order_engine_path` includes everything downstream of `_execute_single_order()`, including any broker call currently hidden behind the `OrderEngine`. It is therefore **NOT** pure application time; Broker / API / network separation is intentionally deferred to Task 8.3.

**Clock:**

- Elapsed durations use `time.perf_counter_ns()` (monotonic, high-resolution).
- The existing wall-clock `DispatchTrace.start_time` / `end_time` (`datetime.now()`) timestamps are unchanged, and the two clocks are never mixed.

**Architecture (one execution implementation only):**

- The existing `DispatchCore.dispatch()` body was minimally extracted into the single private `DispatchCore._dispatch(plan, collector=None)`. There is no second dispatch path and no duplicated business logic.
- `dispatch(plan)` -> `_dispatch(plan, collector=None)`: public behavior, result semantics, and signature unchanged; no latency object is created or consumed and no clock is read.
- `dispatch_with_latency(plan)` -> the same `_dispatch` with an opt-in `LatencyCollector`; returns `(DispatchResult, DispatchLatencyReport)`.
- No fields were added to `DispatchResult`, `OrderExecutionResult`, or any Broker contract.
- Per-order identity and stage timings are stored per `sequence` in the collector; there is no shared mutable `current_account` / `current_broker` / `current_ins_code` context.
- Measurement never changes execution semantics: dry-run / `live=False`, fail-closed behavior, M6-A, M6-B, M6-C, M6-D, M6-E, account binding, broker routing, instrument identity, order sequence, and existing exception handling are all preserved.

**Files changed:**

- `core/latency_instrumentation.py` — new: `StageTiming`, `OrderLatency`, `DispatchLatencyReport`, `LatencyCollector` (injectable/patchable clock).
- `core/dispatch_core.py` — single `_dispatch` implementation, `dispatch_with_latency`, and the `_measure` stage wrapper; existing `DispatchTrace` wall-clock timestamps untouched.
- `test_block8_task8_2.py` — new: 14 Task 8.2 tests.

**Tests executed:**

- `test_block8_task8_2.py`: 14/14 PASS.
- Full existing regression suite: 470/470 PASS (456 pre-existing + 14 new); no pre-existing test was modified.

**Intentionally outside Task 8.2 (not implemented / not attempted):** Broker, API and network latency separation (Task 8.3); VPS / hosting / connection investigation; multi-broker performance conclusions; any optimization, caching, concurrency, or async execution; any refactoring for speed.

---

### Task 8.3 — Broker/API/Network Latency Analysis

**Status:** COMPLETE (Phase A implemented + tested; Phase B read-only tool implemented but **not executed** with real broker credentials/network; no real latency values were reported).

Measurement and analysis only. No optimization was performed, and no ordering/state-changing operation was introduced or called.

#### Phase A — Offline Broker/API-boundary measurement (IMPLEMENTED + TESTED)

Extends the Task 8.2 monotonic instrumentation (`time.perf_counter_ns`) with a second layer that items, per order, the round trip of every **existing** broker/provider method call in the dispatch execution path:

| Operation | Existing call site | What it is |
|---|---|---|
| `get_instrument` | `DispatchCore._resolve_instrument` (Task 8.2 stage `instrument_resolution`) | InstrumentProvider → Broker instrument read |
| `get_instrument` | `OrderEngine.execute_by_ins_code` step 1 | InstrumentProvider → Broker instrument read (second lookup, in the measured run typically a provider **cache hit**) |
| `get_trading_state` | `OrderEngine.prepare` (M6-A trading-state gate) | Broker trading-state read |
| `get_buy_capacity` / `get_sell_capacity` | `OrderEngine.prepare` (M6-C / M6-D capacity gate) | Broker capacity read |
| `place_order` | `OrderEngine.execute` | Broker submission call (dry-run today, `live=False`) |

Per-order report additions (`core/latency_instrumentation.py`):

* `broker_api_calls[]` — `BrokerApiCallTiming(operation, start, end, duration_ns, ok)` for each measured call, in call order, stored on that sequence's own `OrderLatency` (no shared mutable "current order" context).
* `broker_api_round_trip_ns` — total measured round trip for the order; plus `broker_api_round_trip_for(operation)`, `broker_api_totals_by_operation()`, `broker_api_failures()`.
* `application_side_ns` — `order_engine_path` minus the measured broker calls nested inside that same stage (never negative).
* `application_before_broker_ns` / `application_after_broker_ns` — the two application windows around the existing submission call, computed only from boundaries the code already exposes (the `order_engine_path` stage window and the measured `place_order` round trip). Both are `None` when the order never reached submission.

Architecture: **ONE execution implementation still** — `DispatchCore.dispatch()` and `dispatch_with_latency()` both remain on the single `_dispatch()`. Exactly one per-`sequence` `BrokerCallRecorder` is created; measurement wraps existing calls through a single `measure_broker_call()` call-through (calls once, re-raises exceptions unchanged, records in `finally`) so every M6-A … M6-E gate, dry-run / `live=False`, fail-closed behavior, account binding, broker routing and instrument identity are untouched. When no collector is supplied the ordinary path passes **no** measurement keyword to the engine and reads **no** clock.

**Two clocks, never mixed (important design point):** the Task 8.2 stage layer keeps its clock (`latency_clock`) and the Task 8.3 broker/API layer uses its own clock (`broker_clock`); both default to `time.perf_counter_ns`. Broker/API measurement therefore never spends a read of the stage clock, which is why the four Task 8.2 stage windows and the dispatch window are exactly the ones Task 8.2 defined (the original `test_block8_task8_2.py` determinism test passes unchanged). The derived application accounting (`application_before_broker_ns`, `application_after_broker_ns`, `application_side_ns`) is only computed when both layers are on the same clock source — true in the normal/default configuration — and is reported as `None` rather than fabricated when they are not. Each `broker_api_round_trip` stays valid either way, since it is measured entirely on the broker clock.

**Accuracy limitation (important):** `broker_api_round_trip` is the duration of the whole existing broker method call — it includes local request preparation, network transfer, remote processing, response transfer and local response handling inside that method. It is **NOT** pure network latency. No DNS/TCP/TLS or packet-level instrumentation was added, and no VPS/hosting investigation was performed.

**Files changed (Task 8.3 Phase A):**

* `core/latency_instrumentation.py` — broker/API boundary model (`BrokerApiCallTiming`, `BrokerCallRecorder`, `measure_broker_call`, per-order accessors, `finalize_broker_boundary`).
* `core/order_engine.py` — optional trailing `broker_timing=None` on `execute_by_ins_code` / `prepare` / `execute`, and measurement around the five existing broker/provider call sites. No gate, ordering, payload, or return value changed.
* `core/dispatch_core.py` — one recorder per sequence, threaded into `_resolve_instrument` / `_execute_single_order`, plus `finalize_broker_boundary` after each order.
* `test_block8_task8_3.py` — new: 16 Phase A tests.
* No pre-existing test was modified. `test_block8_task8_2.py` is byte-for-byte identical to commit `5194f1d`.

**Tests executed (Phase A):**

* `test_block8_task8_3.py`: 16/16 PASS (all fully offline, deterministic fake clocks, no `sleep()`).
* Full regression: **486/486 PASS** (470 pre-existing + 16 new).

**Phase A evidence:**

* A single dry-run BUY order measures exactly 5 broker/API round trips (`get_instrument` ×2, `get_trading_state`, `get_buy_capacity`, `place_order`), each nested inside the stage that actually contains it, with the order's own identity.
* With the Task 8.2 stage clock injected alone, the stage windows still read exactly `[20,40,60,80] → [30,50,70,90]` and the dispatch window `10 → 100`, while the broker/API round trips are still measured and the cross-clock derived values stay `None` (pinned by a dedicated test).
* Separation proven deterministically in both directions: a synthetic 5 ms delay injected inside the broker `get_buy_capacity` call appears as 5,000,005 ns in `broker_api_round_trip_for("get_buy_capacity")` and only 5 ns in `application_side_ns`; the same delay injected into application-side validation appears as 5,000,005 ns in `application_side_ns` and only 5 ns in `broker_api_round_trip_ns`.
* A raising broker call (`TradingStateUnavailable`, capacity error) is recorded with `ok=False` and a valid duration; a raising `place_order` keeps the existing `mode="ERROR"` engine semantics while the dispatch verdict stays fail-closed `BLOCKED`, and no broker response is fabricated.
* Three cross-aligned orders (different sequence / account / broker / instrument) keep their measurements on their own sequence, and the broker that actually executed each order matches that order's measured operations.
* Normal `dispatch(plan)` performs zero clock reads and produces the identical broker interaction log and identical result semantics.
* All Phase A tests pass with `socket.socket` patched to raise → no network, no credentials.

#### Phase B — Real read-only measurement (IMPLEMENTED, NOT EXECUTED)

A safe read-only operation **does** exist in the repository, so Phase B was implementable without guessing an endpoint or blocker.

* **Mechanism:** `measure_broker_latency.py` — a standalone, explicitly-invoked operator tool (`python measure_broker_latency.py --operation get_account --samples 3`).
* **Read-only only:** `--operation` is restricted to `READ_ONLY_OPERATIONS` (`get_account`, `get_instrument`, `get_trading_state`, `get_buy_capacity`, `get_sell_capacity`). `place_order` and `cancel_order` are unreachable from the tool; no order/cancel code path exists in it.
* **No state change:** no order sent, nothing cancelled, no account/position modification, `live_trading_enabled` never touched.
* **Credentials:** the existing interactive mechanism (`get_captcha` + captcha image + `input` username + `getpass` password + captcha text, mirroring `test_agah_login.py`). Nothing is hard-coded, and no credential or token is ever printed.
* **Isolation:** the tool is not imported by `DispatchCore` and is never invoked automatically; importing it performs no I/O, and it is not collected or run by the test suite.
* **Sampling:** sequential single-request samples, default 3, hard-capped at 10 (diagnostic, not a benchmark; no bursts, no polling loop).
* **Output:** local timestamp, broker name, operation, per-sample round trip + ok/failed, sample count, and min / median / mean / max of the successful samples, plus the round-trip-vs-network-latency caveat. It deliberately does not rank brokers.
* **Executed?** **NO.** No real credentials or broker session were available in this environment, and no real network call was made. No real measurement values are reported here.
* **How to run it (operator, on a machine with the existing credentials):**

```bash
python measure_broker_latency.py --operation get_account --samples 3
python measure_broker_latency.py --operation get_instrument --nsc-id <nscId>
python measure_broker_latency.py --operation get_trading_state --nsc-id <nscId>
```

#### Integration note

On the measured path the optional `broker_timing` keyword is passed to `OrderEngine.execute_by_ins_code`, which is supplied **only** when measurement is requested. A caller that replaces `execute_by_ins_code` with a narrower fake and then calls `dispatch_with_latency()` must accept that optional keyword; the ordinary `dispatch()` path invokes the engine with exactly the pre-Task-8.3 arguments.

#### Intentionally outside Task 8.3 (not implemented / not attempted)

DNS / TCP / TLS or packet-level latency, VPS / hosting / connection-method investigation, broker ranking or multi-broker performance conclusions, optimization of any kind, caching, batching, concurrency, async execution, order reordering, and any change to Broker contracts, `ExecutionTracker`, `OrderExecutionResult`, account binding, instrument mapping, M6-A … M6-E, or `live=False`. Task 8.4 / 8.5 remain outstanding.

### Task 8.4 — Latency Report & Attribution

**Status:** COMPLETE (incl. review fix: clock-safe stage containment + explicit attribution boundary). Task 8.4 completed and committed.

Read-only reporting and attribution ONLY, built on top of the existing Task 8.2/8.3 infrastructure (`DispatchLatencyReport`, `OrderLatency`, `BrokerApiCallTiming`, `LatencyCollector`). No new timing infrastructure, no new measurement, no change to dispatch behavior, ordering, concurrency, retries, polling, timeouts, or any Broker method. No real order was sent and `live_trading_enabled` / dry-run behavior were not touched.

**What was added (all appended to `core/latency_instrumentation.py`):**

* `LatencyDistribution` — frozen dataclass: `count` / `min_ns` / `median_ns` / `mean_ns` / `max_ns`. Empty data reports `count=0` with `None` values — never fabricated (e.g. as 0).
* `BrokerApiFailureInfo` — one recorded Broker/API call failure exactly as Task 8.3 kept it (`sequence`, `operation`, real measured `duration_ns`). Failed-call timing is preserved, not dropped.
* `OrderLatencyAttribution` — per-execution attribution for one `sequence`:

```text
total execution latency      = the record's own measured order_engine_path window
    ├── Broker/API time      = round trips nested IN that window (shared clock only)
    └── application-side     = the record's own derived remainder (None when clocks differ)
```

  plus `order_success` (the existing `OrderExecutionResult.success` flag, `None` when no result was produced) and `engine_stage_failed` (three-valued: `True` / `False` / `None` on different clocks — see review fix below). A raising Broker/API call is NOT folded into `order_success`: the engine already turns broker exceptions into fail-closed BLOCKED results, and the raw call failures stay separately visible. No broker ranking / scoring — the report stays factual.
* `LatencyAnalysis` + `analyze_latency_report(report)` — the factual aggregate: order counts (total / successful / failed), dispatch duration, per-stage distributions (Task 8.2 stages), execution latency distribution, Broker/API total + per-order distribution + per-operation detail + failure list/count, application-side distribution (only from values that exist), and one attribution entry per execution in report order.
* Tiny supporting accessors `OrderLatency.stage_failed(stage_name)` and `OrderLatency.broker_api_calls_within(stage_name)` — read-only checks over already-recorded data. Added so failure attribution and the attribution boundary do not depend on operation names; the only caller is Task 8.4 analysis.

**Review fix (clock safety + attribution boundary):**

* **Clock safety in stage containment:** `OrderLatency` now carries `clocks_shared`, stamped by the collector from its own configuration (hand-built records default to `True`). Containment by timestamp comparison is computed ONLY on a shared clock: `broker_api_calls_within()` returns `[]` and `stage_failed()` returns `None` when the two layers used different clock sources (no cross-clock claim is fabricated); an absent stage is `False`, and raw failures stay visible via `broker_api_failures()` in every case. Task 8.2/8.3 measurement behavior is untouched.
* **Explicit attribution boundary:** `total_execution_latency_ns`, `broker_api_time_ns` and `application_side_ns` decompose ONE window — the measured `order_engine_path` stage. `broker_api_time_ns` is ENGINE-SCOPED: it counts only calls nested in that window when containment is inferable; the pre-engine `get_instrument` round trip (recorded by `DispatchCore._resolve_instrument` in `instrument_resolution`, before the engine stage) is never silently folded into it. The sequence-wide sum is kept under its own explicit name — `broker_api_time_sequence_wide_ns` (ALL measured round trips of the record, inside the window or not) — alongside `broker_api_calls_within_engine`; `broker_api_failure_count` and every aggregate keep ALL measured round trips (including outside the window). Cross-clock records leave the engine-scoped `broker_api_time_ns` at 0 rather than fabricating containment. No measurement was changed or lost.

**Attribution rules enforced (no guessing, no clock mixing):** the attribution boundary is the record's own measured `order_engine_path` window; Broker/API time inside that decomposition comes only from calls actually nested in it (shared clock), while the sequence-wide and aggregate Broker/API values still cover every measured call of the record, including the pre-engine instrument resolution; application-side time is the value the record itself carries and stays `None` when the stage clock and broker clock are not the same source (never derived across clocks); the total execution latency is `None` when the engine stage was never recorded (e.g. blocked before the engine path) instead of being synthesized from other windows; nothing can go negative (windows are monotonic-validated at creation, the application remainder is clamped at 0 by the collector, and the analysis is a pure read).

**Files changed (Task 8.4):**

* `core/latency_instrumentation.py` — Task 8.4 reporting/attribution layer appended at the end of the module (`LatencyDistribution`, `BrokerApiFailureInfo`, `OrderLatencyAttribution`, `LatencyAnalysis`, `analyze_latency_report`) plus the small `OrderLatency.stage_failed` accessor. The Task 8.2/8.3 classes, fields, semantics, and docstrings are unchanged; `test_block8_task8_2.py` / `test_block8_task8_3.py` pass byte-identical in behavior.
* `test_block8_task8_4.py` — new: 32 Task 8.4 tests (fully offline: deterministic fake clocks, no `sleep()`, `socket.socket` patched to raise, no credentials).
* `AI_HANDOFF.md` — this section.
* No other file was touched. `core/dispatch_core.py`, `core/order_engine.py`, and every Broker contract are byte-identical to commit `616782f`.

**Tests executed:**

* `python -m pytest test_block8_task8_4.py -q`: 32/32 PASS.
* Full regression: `python -m pytest -q`: **518/518 PASS** (486 pre-existing + 32 new). No pre-existing test was modified. `git diff --check`: clean.

**Focused coverage (mapped to the 12 mandated scenarios):** single execution report; multi-execution per-sequence reporting (no cross-order leak); min/median/mean/max (incl. hand-computed aggregates and even-count median); Broker/API aggregates (total, per-order, per-operation); application-side attribution (delay lands broker-side or application-side, never both); different-clock attribution → `None` (unit-level mixed report AND end-to-end stage-clock-only injection); zero/one-tick latencies stay non-negative and intact; failed execution stays visible; Broker/API failure keeps its timing and existing ERROR/BLOCKED semantics; missing data (empty report, engine stage absent) → `None`/count=0, never invented; sequence identity preserved into the analysis; ordinary `dispatch()` regression (identical broker interaction, zero clock reads).

**Measurement limitations (unchanged from Task 8.3):** `broker_api_time_ns` is a Broker/API **round trip** (local preparation + transfer + remote processing + local response handling inside the existing method), NOT network-only latency; no DNS/TCP/TLS or packet-level data exists and none was synthesized. `application_side_ns` remains an accounting remainder of the engine stage, not a hard bound. The analysis adds no new measurement and re-measures nothing.

**Intentionally outside Task 8.4 (not implemented / not attempted):** broker ranking/scoring, benchmark/load/stress/burst testing, persistence/dashboards/new metrics frameworks, any optimization, and any change to dispatch, Broker methods, or `live` behavior.

### Block 8.5 — Latency Optimization Insight

**Goal:** Create a read-only analysis layer that converts the existing `LatencyAnalysis` from Task 8.4 into a structured optimization insight. The architecture and rules below are fixed; do not redesign them.

**Required files:**

* `core/block8_task8_5.py` — new: `LatencyOptimizationInsight` immutable dataclass and `build_latency_insight(analysis)` pure function.
* `test_block8_task8_5.py` — new: comprehensive tests covering 13 scenarios (normal, one order, multiple orders, missing data, unavailable states, zero totals, percentage accuracy, input integrity, etc.).

**Update only:**

* `AI_HANDOFF.md` — this section, documenting Task 8.5 completion.

**Do not modify:** dispatch, order-engine, broker, or existing Task 8.2/8.3 timing infrastructure.

**Required API in `core/block8_task8_5.py`:**

```python
@dataclass(frozen=True)
class LatencyOptimizationInsight:
    status: str
    analyzed_orders: int
    execution_total_ns: int
    broker_api_total_ns: int
    application_side_total_ns: int
    broker_api_share_pct: Optional[float]
    application_side_share_pct: Optional[float]
    reason: str

def build_latency_insight(analysis: LatencyAnalysis) -> LatencyOptimizationInsight
```

**Calculation rules:**

* Use only `analysis.attributions`.
* For each attribution, use `total_execution_latency_ns`, `broker_api_time_ns`, `application_side_ns`.
* Do NOT use `broker_api_time_sequence_wide_ns` for component split.
* An attribution is analyzable only when all three fields are present and non-negative.
* Aggregate only analyzable attributions.
* Calculate percentages as `broker_api_total_ns / execution_total_ns * 100` and `application_side_total_ns / execution_total_ns * 100`.
* If `execution_total_ns == 0`, return `status = "UNAVAILABLE"` with `None` percentages and reason.
* If no analyzable attributions, return `status = "UNAVAILABLE"` with totals = `0`, `None` percentages and reason.
* If analyzable data exists and execution total > 0, return `status = "AVAILABLE"` with totals, percentages, and empty reason.

**Clock rule:** Do not independently infer clock compatibility. Task 8.4 already carries attribution values safely. If attribution does not contain usable `application_side_ns`, treat as non-analyzable.

**Data integrity:** Never create negative latency values, invent missing values, use sequence-wide Broker/API time in engine decomposition, alter sequence identity, modify original `LatencyAnalysis` or its attributions.

**Tests executed:**

* `python -m pytest test_block8_task8_5.py -q`: **15/15 PASS**.
* Full regression: `python -m pytest -q`: **533/533 PASS** (486 pre-existing + 32 Task 8.4 + 15 Task 8.5 new). No pre-existing test was modified.
* `git diff --check`: clean.

**Focused coverage (implemented by 15 tests):**

The 13 mandated scenarios are covered by the 15 tests:

1. normal multi-order calculation
2. one order
3. multiple orders
4. missing `application_side_ns`
5. missing Broker/API attribution
6. no analyzable orders
7. zero execution total
8. non-negative percentage results
9. percentage calculation accuracy
10. sequence-wide Broker/API time is not used
11. input object remains unchanged
12. existing Task 8.4 attribution fields remain unchanged
13. mixed/unavailable data does not produce a guessed result

*Additional tests cover: zero execution with non-zero totals (covers the special case when execution_total_ns == 0 but broker/application sides are non-zero), input immutability validation, field consistency validation, and insight immutability checks.*

**DispatchCore/OrderEngine/Broker behavior unchanged:** No modifications to dispatch path, Broker interfaces, order-engine timing logic, or any measurement infrastructure.

**Confirmation:** Task 8.5 completed successfully.

**Note:** Task 8.5 completed as part of Block 8, which now provides end-to-end latency measurement (8.2/8.3 instrumentation + 8.4 analysis + 8.5 insight).

### Block 9 — Stress / Simulation

**Goal:** Test the system under heavy load.

**Scope:**
- High order volume
- Severe bursts
- Multiple Accounts
- Multiple Brokers
- Network / Broker response disruption
- Correct preservation of M6-A through M6-E

Real Trading must remain disabled during this block.

**Output:** Proof of stability and correct behavior under load.

**Dependencies:** Block 8

**Status:** COMPLETED

### Block 9 Task Roadmap

**Task 9.1 — Simulation Harness**

* Build a small offline, deterministic simulation harness.
* It must exercise the existing dispatch path without real network access, real broker credentials, or real orders.
* Use fake/mock broker behavior only where required for simulation.
* Do not modify production dispatch behavior.
* This task establishes the foundation for all later Block 9 stress scenarios.

**Task 9.1 — Status: COMPLETED**

* Status: `COMPLETED`
* Commit: `19fbe50`
* Files added:
  * `core/simulation_harness.py` — offline `SimulationBroker` + `SimulationInstrumentProvider` + `SimulationHarness` (the only substituted components; registered in a private `BrokerManager`).
  * `test_block9_task9_1.py` — Task 9.1 offline tests.
* Execution mode: fully offline and deterministic (no sleeps, no randomness, no network, no credentials).
* Real path exercised: `ExecutionPlan → DispatchCore.dispatch() → BrokerManager → OrderEngine → Simulation Broker → DispatchResult`.
* Real `DispatchCore` and real `OrderEngine` used (no re-implementation, no subclass, no parallel dispatch path).
* M6-A through M6-E remain intact and active on the real path.
* No production dispatch behavior changed; no production file modified.
* No real broker, no credentials, no real order, no network used (proven via mock/patch of `AgaahBroker`/`AgaahInstrumentProvider` and socket blocking; the real network was never touched).
* `live_trading_enabled` never enabled.
* Task 9.1 tests: `14/14 PASS`.
* Full regression after Task 9.1: `547/547 PASS`.
* `git diff --check`: clean.
* Commit/Push: completed (`19fbe50`).

**Task 9.1 boundary (explicitly NOT included):** Task 9.1 only establishes the Simulation Harness foundation. It did NOT implement High Volume, Severe Burst, Multi-Account Stress, Multi-Broker Stress, Failure Injection, Timeout / Retry, Concurrency, or Performance Optimization. Those remain for Tasks 9.2–9.7.

**Task 9.2 — High Volume**

* Use the Task 9.1 harness to test increasing execution volumes.
* Verify correctness, state integrity, result integrity, and absence of lost or duplicated executions.
* Keep the test deterministic and offline.
* Do not introduce optimization or production behavior changes.

**Task 9.2 — Status: COMPLETED**

* Status: `COMPLETED`
* Commit: `a64b7bb`
* Files added/changed:
  * `core/simulation_harness.py` — extended with the volume-scenario methods (`volume_order_fields`, `build_volume_plan`, `run_volume_scenario`); reuses the Task 9.1 components, no new architecture.
  * `test_block9_task9_2.py` — Task 9.2 High Volume tests.
* Execution mode: fully offline and deterministic.
* Volumes tested: 10, 50, and 100 orders.
* Real path exercised: `ExecutionPlanner → ExecutionPlan → DispatchCore.dispatch() → BrokerManager → OrderEngine → SimulationBroker → DispatchResult`.
* Sequences are unique and complete; no lost execution and no duplicate execution observed.
* No sequence/order mismatch observed.
* State contamination across consecutive runs checked; deterministic rerun checked.
* Live trading never enabled (`live_trading_enabled` stays `False`).
* No real network, no real broker, no real credential, and no real order used.
* `DispatchCore` and `OrderEngine` unchanged; M6-A through M6-E unchanged; Block 6 account binding unchanged; Block 7 broker routing unchanged; Block 8 instrumentation unchanged.
* No concurrency / async / queue / optimization / caching / batching architecture added.
* Task 9.2 tests: `15/15 PASS`.
* Full regression after Task 9.2: `562/562 PASS`.
* `git diff --check`: clean.
* Commit/Push: completed (`a64b7bb`); `origin/master` now at `a64b7bb`.

**Task 9.2 boundary (explicitly NOT included):** Task 9.2 only implemented High Volume Simulation. Severe Burst is Task 9.3, Multi-Account is Task 9.4, Multi-Broker is Task 9.5, and Failure Injection is Task 9.6.

**Task 9.3 — Severe Burst**

* Extend the simulation to model highly concentrated/burst execution arrival.
* Verify that burst conditions do not corrupt sequence identity, results, or state.
* Keep real trading disabled and keep the scenario fully simulated.

**Task 9.3 — Status: COMPLETED**

* Status: `COMPLETED`
* Commit: `fa68c63`
* Files added/changed: `core/simulation_harness.py` (added `run_burst_scenario`; deterministic burst volume 250, larger than every Task 9.2 volume) and `test_block9_task9_3.py`.
* Burst is severity, not concurrency: many orders in ONE `ExecutionPlan`, ONE `dispatch()` call, executed sequentially by the real engine.
* Fully offline and deterministic; sequence completeness/uniqueness, no lost/duplicated execution, consecutive-burst state isolation, and deterministic rerun proven.
* Task 9.3 tests: `10/10 PASS`; full regression after Task 9.3: `572/572 PASS`.

**Task 9.4 — Multi-Account Isolation**

* Simulate multiple accounts processing different orders at the same time.
* Explicitly verify account isolation.
* Example requirement:
  `Account 1 → Stock A`
  `Account 2 → Stock B`
* No account may receive another account's order, state, instrument, or result.

**Task 9.4 — Status: COMPLETED**

* Status: `COMPLETED` (Multi-Account Isolation)
* Files added/changed: `core/simulation_harness.py` (added `multi_account_plan` / `run_multi_account_scenario`; interleaved `ACC-SIM-1 → STOCK-A` / `ACC-SIM-2 → STOCK-B`) and `test_block9_task9_4.py`.
* Isolation proven via exact `(sequence, account, instrument)` integrity, distinct account balances observable in the real M6-D `fund` trail, and consecutive-run state isolation.
* Fully offline and deterministic; no production code changed.
* Task 9.4 tests: `13/13 PASS`.

**Task 9.5 — Multi-Broker Isolation**

* Simulate multiple brokers with independent execution paths.
* Verify broker, account, instrument, sequence, and result isolation.
* Example:
  `Account 1 → Broker A`
  `Account 2 → Broker B`
* No broker-specific state or result may cross into another broker path.

**Task 9.5 — Status: COMPLETED**

* Status: `COMPLETED`
* Commit: `b56623c`
* Files added/changed: `core/simulation_harness.py` (added `build_dual_broker_harness` on the existing Block 7 `register()` seam, plus `multi_broker_plan` / `run_multi_broker_scenario`) and `test_block9_task9_5.py`.
* Proven end-to-end: `ACC-SIM-1 → STOCK-A → SIM-A` and `ACC-SIM-2 → STOCK-B → SIM-B` (interleaved, one plan, one dispatch) with per-broker provider isolation and no cross-contamination.
* Fully offline and deterministic; no production code changed.
* Task 9.5 tests: `13/13 PASS`.

**Task 9.6 — Failure Injection**

* Simulate controlled Broker/API/network failures.
* Cover failure categories such as exception, timeout, failed response, and missing response where the existing architecture can represent them.
* Verify fail-closed behavior and preservation of existing safety gates.
* Do not perform real network or real broker failure testing in this Block.

**Task 9.6 — Status: COMPLETED**

* Status: `COMPLETED`
* Commit: `2f6ada7`
* Failure injection implemented ONLY in `SimulationBroker` (`configure_failure` / `clear_failure`, one-shot and identity-scoped); no production component changed.
* Real path preserved: `ExecutionPlanner → ExecutionPlan → DispatchCore.dispatch() → BrokerManager → OrderEngine → SimulationBroker → DispatchResult`.
* Implemented failure modes:
  1. `exception` — controlled exception inside the real `place_order` call; the engine's own handling produces the per-order result and the aggregate verdict fail-closes to `BLOCKED` while the remaining independent orders still execute.
  2. `failed response` — broker returns a failure envelope in the shape the current path already carries (observable at the broker seam; per the current contract the aggregate verdict stays `ALL_PROCESSED`).
  3. simulated `timeout` — a fully simulated `TimeoutError` (no socket, no real network, no sleep).
* Missing/no-response was NOT implemented due to the current contract (the broker path has no representable "no response" state); it must NOT be treated as an existing capability.
* Failures are deterministic and offline; failure position, sequence, account, broker, instrument, and outcome are not random.
* No real broker, no real credential, no real network, and no real/live order used; `live_trading_enabled` stays `False` and the live refusal still wins fail-closed.
* M6-A through M6-E remain intact, active, and NOT bypassed on the injected path.
* Isolation and state isolation tested (failure isolation between accounts/brokers/instruments; consecutive failure/healthy runs with no leakage of failure, identity, or counters).
* Task 9.6 tests: `13` focused tests PASS.
* Full regression after Task 9.6: `611/611 PASS`.
* Commit/Push: completed (`2f6ada7`).

**Task 9.7 — Acceptance & Closure**

* Status: `COMPLETED`
* Commit: `4be5044` — `test: add Block 9 acceptance and closure tests`
* Push: completed to `origin/master`.

Task 9.7 ran the final combined Block 9 scenarios and verified all acceptance criteria before changing the Block 9 status to `COMPLETED`.

**Focused test results (Task 9.7):** `7/7 PASS`

**Block 9 focused tests (Tasks 9.1–9.7):** `85/85 PASS`

**Full project regression:** `618/618 PASS`

**`git diff --check`:** clean

**Final acceptance coverage (verified):**

- High Volume
- Severe Burst
- Multi-Account Isolation
- Multi-Broker Isolation
- Failure Injection
- account/broker/instrument/sequence isolation
- no lost executions
- no duplicated executions
- no cross-routed execution/result contamination
- state isolation across consecutive runs
- deterministic rerun behavior
- preservation of M6-A through M6-E

**Safety evidence recorded:**

- `live_trading_enabled` remained `False`
- no real orders were sent
- no real broker credentials were required
- no real-world network stress was performed
- simulation remained fully offline
- production DispatchCore / OrderEngine / Broker contracts were not redesigned or replaced

### Fixed Block 9 Boundaries

Explicitly document that Block 9 must NOT:

* enable `live_trading_enabled`
* send real orders
* require real broker credentials
* perform real-world network stress testing
* redesign DispatchCore
* bypass or weaken M6-A through M6-E
* introduce M6-F / Order Splitting
* perform automatic optimization
* replace the existing production dispatch architecture

### Ordering

Document the required sequence:

`9.1 → 9.2 → 9.3 → 9.4 → 9.5 → 9.6 → 9.7`

Each later task depends on the simulation foundation established by Task 9.1.

---

### Block 10 — Controlled Live Execution

**Goal:** After Block 9 is complete and validated, give the system a controlled, fail-closed path for Live Execution.

**Architectural Note (critical):** Block 10 is **NOT** a redesign of capabilities already built and validated in Blocks 5, 6, 7, 8, and 9. Block 10 reuses the existing Multi-Account Execution (Block 6), Multi-Broker Execution (Block 7), Execution Tracking (Block 5), Latency instrumentation (Block 8), and Stress/Simulation harness (Block 9) capabilities exactly as they are. Block 10 only adds the minimal layer required to enable **Controlled Live Execution**, and it preserves every existing M6-A through M6-E safety gate.

**Scope:**
- Define explicitly the conditions under which Live Execution is permitted.
- Add a final, independent Safety Gate that prevents any real order from being dispatched when Live conditions are not satisfied.
- Enable Live Execution on a single, controlled dispatch path, preserving the existing architecture.
- Final end-to-end verification that Dry Run remains non-real and Live remains gated.

**Out of Scope (Block 10 must NOT):**
- Redesign Multi-Account Execution (Block 6).
- Redesign Multi-Broker Execution (Block 7).
- Redesign Execution Tracking (Block 5).
- Redesign Latency Measurement/Optimization (Block 8).
- Redesign the Simulation Harness (Block 9).
- Bypass or weaken M6-A through M6-E.
- Introduce M6-F / Order Splitting.
- Change the `Planner → Dispatch Core → Account/Broker binding → OrderEngine → Broker` dispatch path.
- Send any real order before explicit human approval.

**Output:** Controlled, gated entry into Live Trading.

**Dependencies:** Block 9 — Stress / Simulation

**Status:** COMPLETED — Tasks 10.1, 10.2, 10.3, and 10.4 are all `COMPLETED` (Task 10.4: commit `5164fda`, `test: add Block 10 final live verification`; 3/3 focused acceptance tests PASS; full regression 640/640 PASS). No real order was ever sent during Block 10 — no real credentials, network, or broker API were used — and entry into actual Live trading still requires the Task 10.1 prerequisites, including explicit human approval.

#### Task 10.1 — Live Execution Contract

Define precisely the conditions under which Live Execution is permitted.

This task must specify:
- What "Live" means exactly (a dispatch path where real orders may be submitted to a real Broker for a real Account, as opposed to Dry Run which never submits).
- The prerequisites that must hold before Live is allowed (Block 9 complete and green; M6-A through M6-E gates active; Architect review completed; explicit human approval given; a Live-capable Broker/Account bound).
- The conditions that forbid Live Execution (unmet prerequisites; any M6 gate returning BLOCKED/UNVERIFIED; missing or invalid Account/Broker binding; no human approval token).
- The boundary between Dry Run and Live: the single, explicit switch point where `live` transitions from `False` (Dry Run, always the current default) to `True` (Live), guarded by the Safety Gate.

**Output:** A formal Live Execution Contract (conditions + gate rules + Dry-Run/Live boundary).

**Status:** COMPLETED — commit `ff253e7` (`docs: define Block 10 Task 10.1 live execution contract`)

#### Task 10.1 Deliverable — Live Execution Contract

Documentation-only contract, derived from the code as it exists today (no new architecture, no gate implemented, no live order, no Python/test file changed). It is the rulebook Task 10.2 (Safety Gate) and Task 10.3 (Controlled Live Dispatch) must implement against. Task 10.1 status has been updated above to `COMPLETED` (commit `ff253e7`).

**Current reality (verified in code, pre-10.2/10.3):** every dispatch is Dry Run. `DispatchCore` sets `live_trading_enabled = False` at construction ("Block 10 owns that switch"), `_dispatch()` hard-codes `live=False` in every `BrokerDispatchRequest` ("dry-run always, until Block 10"), `SimulationHarness` mirrors production with `live_trading_enabled = False`, and no real broker is ever constructed in the Block 9 path.

##### 1. Definitions

**Dry Run (system default, unchanged):** a dispatch in which every `BrokerDispatchRequest` is built with `live=False`. Consequences on the real path:
- `OrderEngine.execute_by_ins_code(..., live=False)` calls `broker.place_order(order, live=False)`, which returns `{"mode": "DRY_RUN", "sent": False, "payload": ...}` — nothing is submitted.
- Per-order results carry `sent=False`; the aggregate `DispatchResult` carries `sent=False`.
- All M6-A … M6-E gates still run normally inside `OrderEngine.prepare()`.
- No public API signature changes; Dry Run remains the default for every caller.

**Live:** a dispatch in which, for at least one order, the `BrokerDispatchRequest` carries `live=True` AND the resolved broker instance itself has `live_trading_enabled=True`, so that `broker.place_order(order, live=True)` proceeds past both existing guards and submits through the broker's real session (`session.post(...)`).

**What makes a dispatch "real":** per order, at the broker boundary: `place_order(order, live=True)` reached with `live_trading_enabled == True` on that same broker instance. Both conditions are required; missing either one is not live:
- envelope `live=True` + broker flag `False` → the engine guard returns `mode="BLOCKED"` fail-closed and the broker is never called live;
- even if that guard were bypassed, the broker's own lock raises `RuntimeError` when `live_trading_enabled` is `False` (independent second lock).

There is exactly one live path — the existing one. No parallel live path exists and none may be created.

##### 2. Live Prerequisites (ALL must hold before Live is allowed)

1. **Block 9 complete and validated.** Block 9 is `COMPLETED` — Task 9.7 Acceptance & Closure passed (Block 9 focused tests `85/85 PASS`, full regression `618/618 PASS`) and the Block 9 status, including the Roadmap Summary row, reads `COMPLETED`.
2. **M6-A … M6-E valid and active** on the real engine path (they execute inside `OrderEngine.prepare()`; any BLOCKED/UNVERIFIED verdict aborts the order).
3. **Valid Account** for the sequence: resolvable from `plan.accounts` via `plan.conditions["binding"][sequence]["account_id"]` (DispatchCore `_plan_account`, fail-closed on missing/invalid).
4. **Valid, usable Broker:** resolvable via the existing `BrokerManager.get(broker_name)` with its `get_instrument_provider(broker_name)` provider (Block 7 seam).
5. **Valid Account/Broker binding:** `plan.conditions["binding"][sequence]["broker_name"]` and `plan.account_routes` consistent with Block 6 semantics.
6. **Architect review** of the controlled-live implementation completed.
7. **Explicit human approval** — recorded, dispatch-scoped, revocable; its absence forbids Live unconditionally.

Additional conditions observed as genuinely necessary from the existing code (not invented):

8. `DispatchCore.live_trading_enabled == True` (the instance flag that already exists, deliberately `False`; Block 10 owns it).
9. For every broker that would receive live orders: that broker instance's `live_trading_enabled == True`.
10. The instrument resolves through the broker's own provider (M6-A identity depends on it).

##### 3. Live Prohibition Conditions (Live MUST be forbidden when)

- Any prerequisite of §2 is missing, invalid, or unverifiable.
- Any M6 gate returns `BLOCKED` or `UNVERIFIED`.
- The Account or Broker is unknown/invalid (unresolvable from the plan).
- The Account/Broker binding is invalid or inconsistent with `plan.account_routes`.
- Human approval is absent.
- The Live status is unknown or ambiguous (flag states unreadable) — treated as not-live.

General rule: **Unknown / Invalid / Unverified → Live forbidden.**

##### 4. Dry Run / Live Boundary (single switch point)

- The boundary is the construction of `BrokerDispatchRequest` inside `DispatchCore._dispatch()` (Block 2 routing stage). Today it is hard-coded `live=False`.
- Contract: `live=False` → Dry Run (system default). `live=True` may appear in the envelope **only** as the output of the Task 10.2 Safety Gate evaluating §2/§3 at this exact point. No other component may set `live=True`.
- Defense in depth already present and to be preserved: envelope flag → engine guard (`execute_by_ins_code` checks the broker flag) → broker lock (`place_order` + `live_trading_enabled`).
- This task defines the location and rules only; the gate itself is Task 10.2 scope.

##### 5. Fail-Closed Behavior (contract level)

- Any precondition that cannot be verified leaves `live=False` — the dispatch continues as Dry Run or is blocked; failures surface as `mode="BLOCKED"` per the existing engine/core fail-closed contracts. Never fail-open.

##### 6. Relation to M6-A … M6-E

The contract never bypasses them. Live requires the same real engine path `execute_by_ins_code → prepare() (M6-A … M6-E) → broker.place_order`. M6 verdicts are an input condition of Live permission, not an alternative to it.

##### 7. Relation to Account/Broker Binding (Blocks 6 & 7)

Live respects the same per-sequence binding (`plan.conditions["binding"]` + `plan.account_routes`) and Block 7 broker/provider resolution; no routing is invented. The Safety Gate verifies binding validity as a prerequisite (§2.5, §3).

##### 8. What Remains for Later Tasks

- **Task 10.2:** implement the independent Safety Gate at the §4 boundary — evaluate §2/§3, produce `live=True` only on a full pass, otherwise block with `mode="BLOCKED"` and `live` effectively `False`.
- **Task 10.3:** enable the single controlled live dispatch path on top of the gate (no redesign of Blocks 5–9).
- **Task 10.4:** final verification suite proving Dry Run stays non-real and Live fires only under this contract.

#### Task 10.2 — Safety Gate

Add a final, independent Safety Gate that prevents a real order from being dispatched when the Live conditions of Task 10.1 are not satisfied.

This task focuses on control and prevention. It MUST NOT redesign the existing Dispatch logic.

**Output:** A Safety Gate (guard) that is evaluated at the Live Dispatch boundary; fail-closed: any unmet condition blocks dispatch with `mode="BLOCKED"` and `live` effectively `False`.

**Status:** COMPLETED — commit `79fc94c` (`feat: add Block 10 safety gate`). 11 focused tests PASS; full regression 629/629 PASS.

#### Task 10.3 — Controlled Live Dispatch

Enable Live Execution on a single, limited, controlled dispatch path while preserving the existing architecture:

`Planner → Dispatch Core → Account/Broker binding → OrderEngine → Broker`

This task MUST NOT redesign Multi-Account, Multi-Broker, Execution Tracking, or the existing Dispatch Architecture.

**Output:** A gated Live Dispatch path that reuses Block 6 (account binding), Block 7 (broker routing), Block 5 (tracking), and Block 2/4 (Dispatch Core), adding only the Live enablement layer on top.

**Status:** COMPLETED — commit `6cabcad` (`feat: add controlled live dispatch bridge`). 8 focused tests PASS; full regression 637/637 PASS. No real live execution was performed.

#### Task 10.4 — Final Live Verification

Final verification of Block 10.

Minimum verifications:
- Dry Run remains non-real (no order sent; `live=False` / `sent=False`) across all scenarios.
- Live is active only under the exact conditions defined in Task 10.1.
- The Safety Gate (Task 10.2) blocks dispatch whenever Live conditions are invalid.
- Mismatched Account and Broker combinations do not dispatch Live.
- The existing Dispatch path is preserved (Planner → Dispatch Core → Account/Broker binding → OrderEngine → Broker).
- Undesired or accidental Live activation is covered by tests (no random/implicit Live enablement).

**Output:** Final verification suite proving Controlled Live Execution is safe and that Live never fires unintentionally.

**Status:** COMPLETED — commit `5164fda` (`test: add Block 10 final live verification`). 3/3 focused acceptance tests PASS; full regression 640/640 PASS. Verified: the fail-closed prerequisite matrix at the real dispatch level (no gate, every prerequisite missing/invalid, raising gate, invalid decision → Dry Run `live=False`); Account/Broker identity preserved on the controlled Live path at the broker boundary; M6-A … M6-E remain authoritative and block even after `SafetyGate = ALLOW`; no unintended production Live path exists; no real order sent; no real credentials/network/API used.

#### Block 10 — Task Summary

| Task | هدف | مسئولیت | خارج از Scope |
|---|---|---|---|
| 10.1 | Live Execution Contract | تعریف شرایط مجاز بودن Live | هیچ Dispatch یا Broker implementationی اضافه نشود |
| 10.2 | Safety Gate | جلوگیری از ارسال واقعی در شرایط نامعتبر | بازطراحی منطق Dispatch موجود |
| 10.3 | Controlled Live Dispatch | فعال‌سازی Live در مسیر محدود و کنترل‌شده | بازطراحی Multi-Account / Multi-Broker / Tracking / Architecture موجود |
| 10.4 | Final Live Verification | اعتبارسنجی نهایی | ارسال هر سفارش واقعی قبل از تأیید انسانی |

**Acceptance Criteria:**
- The four Tasks above are defined and sequenced.
- Live cannot dispatch when any M6 gate is BLOCKED/UNVERIFIED or when human approval is absent.
- Dry Run path is byte-identical in behavior to the pre-Block-10 path.
- No Block 5, 6, 7, 8, or 9 capability is redesigned or replaced.
- No real order is sent before explicit human approval.
- `git diff` shows only documentation for Block 10 roadmap definition (this task); no code/test changes.

---

### Dependency Graph

```
Block 0 → Block 1 → Block 2
                        ↓
            Block 3      Block 4
              ↓            ↓
              Block 5 (depends on Block 2, Block 3, Block 4)
                        ↓
                    Block 6
                        ↓
                    Block 7
                        ↓
                    Block 8
                        ↓
                    Block 9
                        ↓
                   Block 10
                        ↓
                      UI
```

**Key architectural points:**

- **Block 3 and Block 4 are siblings**, not dependent on each other. Both depend on Block 2 (Dispatch Core).
- **Block 5 depends on Block 2, Block 3, and Block 4** so it can track both dispatch paths.
- **Latency instrumentation starts in Block 2**, not Block 8. Block 8 analyzes and optimizes existing data.
- **Block 10 depends on Block 9** and must reuse Blocks 5–9 as-is; it only adds the Live enablement layer.
- **UI depends on Block 10**, so the Controlled Live Execution path is a prerequisite for the UI to offer a Live Trading surface.

### Roadmap Summary

| Block | Name | Dependencies | Status |
|-------|------|--------------|--------|
| 0 | Dispatch Architecture Foundation | — | IMPLEMENTED (committed `7b29897`) |
| 1 | Execution Planner | Block 0 | COMPLETE (committed `2c4e857`, pushed `origin/master`) |
| 2 | Dispatch Core / Low-Latency Engine | Block 1 | IMPLEMENTED (committed) |
| 3 | Timed / Burst Dispatch | Block 2 | NOT STARTED |
| 4 | Event-Driven Dispatch | Block 2 | NOT STARTED |
| 5 | Execution Tracking | Block 2, Block 3, Block 4 | COMPLETED |
| 6 | Multi-Account Execution | Block 5 | COMPLETED |
| 7 | Multi-Broker Execution | Block 6 | COMPLETED |
| 8 | Latency Measurement & Optimization | Block 7 | COMPLETED (Tasks 8.1-8.5 implemented) |
| 9 | Stress / Simulation | Block 8 | COMPLETED |
| 10 | Controlled Live Execution | Block 9 | COMPLETED (10.1–10.4) |
| UI | User Interface | Block 10 | NOT STARTED |

**M6-F — Order Splitting:** Deferred / Future Development (out of scope per Architect decision).

