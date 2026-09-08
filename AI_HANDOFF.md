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

Project State: M5 completed (ca3e2cbf, pushed) + M6-A completed (Architect approved, pushed as 7ce09e3) + M6-B completed (Architect approved, pushed as 84f9130) + M6-C Account Cash + BUY Capacity completed (Architect approved, pushed as 03ede4e) + M6-D Portfolio Quantity / SELL Gate completed (Architect approved, pushed as f3bdf1d) + Documentation Checkpoint.

Last Completed Milestone: M6-D — Portfolio Quantity / SELL Gate (all gates implemented, tested, and committed).

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

**Status:** NOT STARTED

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

**Status:** NOT STARTED

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

**Status:** NOT STARTED

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

### Block 5 — Execution Tracking

**Goal:** Track the full execution cycle.

**Scope:**
- Dispatch request.
- Broker response.
- Order status.
- Registration confirmation in the trading core, only if a reliable contract exists.

This block must be usable through both Timed/Burst and Event-Driven paths.

**Dependencies:** Block 2, Block 3, Block 4

**Status:** NOT STARTED

---

### Block 6 — Multi-Account Execution

**Goal:** Execute one Execution Plan across multiple Accounts.

**Scope:**
- Multiple Accounts from one Broker.
- Coordinated yet independent execution per Account.
- Preserve Account isolation and Account contracts.

**Output:** Execution of one order plan across multiple accounts.

**Dependencies:** Block 5

**Status:** NOT STARTED

---

### Block 7 — Multi-Broker Execution

**Goal:** Extend execution to multiple Brokers.

**Scope:**
- Multiple Brokers.
- Multiple Accounts across multiple Brokers.
- Preserve Broker abstraction.
- Dispatch Core must not depend on any single Broker implementation.

**Output:** Multi-Account / Multi-Broker Dispatch.

**Dependencies:** Block 6

**Status:** NOT STARTED

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

**Status:** NOT STARTED

---

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

**Status:** NOT STARTED

---

### Block 10 — Controlled Live Execution

**Goal:** Controlled entry into Live Trading, only after:
- Completion of required blocks
- Successful tests
- Architect review
- Explicit human approval

**Output:** Controlled entry into Live Trading.

**Dependencies:** Block 9

**Status:** NOT STARTED

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
```

**Key architectural points:**

- **Block 3 and Block 4 are siblings**, not dependent on each other. Both depend on Block 2 (Dispatch Core).
- **Block 5 depends on Block 2, Block 3, and Block 4** so it can track both dispatch paths.
- **Latency instrumentation starts in Block 2**, not Block 8. Block 8 analyzes and optimizes existing data.

### Roadmap Summary

| Block | Name | Dependencies | Status |
|-------|------|--------------|--------|
| 0 | Dispatch Architecture Foundation | — | NOT STARTED |
| 1 | Execution Planner | Block 0 | NOT STARTED |
| 2 | Dispatch Core / Low-Latency Engine | Block 1 | NOT STARTED |
| 3 | Timed / Burst Dispatch | Block 2 | NOT STARTED |
| 4 | Event-Driven Dispatch | Block 2 | NOT STARTED |
| 5 | Execution Tracking | Block 2, Block 3, Block 4 | NOT STARTED |
| 6 | Multi-Account Execution | Block 5 | NOT STARTED |
| 7 | Multi-Broker Execution | Block 6 | NOT STARTED |
| 8 | Latency Measurement & Optimization | Block 7 | NOT STARTED |
| 9 | Stress / Simulation | Block 8 | NOT STARTED |
| 10 | Controlled Live Execution | Block 9 | NOT STARTED |

**M6-F — Order Splitting:** Deferred / Future Development (out of scope per Architect decision).

