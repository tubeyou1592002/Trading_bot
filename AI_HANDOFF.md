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
brokers/base.py	کلاس‌های انتزاعی Broker و InstrumentProvider
brokers/agaah/__init__.py	صادرات AgaahBroker, AgaahInstrumentProvider, InstrumentLookupError
brokers/agaah/broker.py	کلاس AgaahBroker برای ارتباط با API آگاه
brokers/agaah/instrument_provider.py	کلاس AgaahInstrumentProvider برای نگاشت insCode → nscId
market/tsetmc.py	کلاس TSETMC برای دریافت اطلاعات نمادها
market/symbol_resolver.py	حل‌کننده‌ی نماد با نرمال‌سازی فارسی
models/instrument.py	مدل Instrument
models/broker_instrument.py	مدل BrokerInstrument
core/order_engine.py	هسته‌ی ثبت سفارش
test_instrument_provider.py	تست‌های واحد AgaahInstrumentProvider
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
test_order_build.py	پاس
test_broker_dry_run.py	پاس
Smoke test (main.py import)	پاس
موارد تأییدشده
منطق tseId == insCode به‌درستی کار می‌کند.

AgaahInstrumentProvider اولین نتیجه را انتخاب نمی‌کند (تأیید tseId اجباری است).

از cIsin یا پسوندهای 0001/0003 به‌عنوان کلید استفاده نمی‌شود.

insCode هرگز مستقیماً به broker.get_instrument() داده نمی‌شود.

کش در حافظه به‌درستی کار می‌کند.

خطاهای شبکه به InstrumentLookupError تبدیل می‌شوند.

8. Known Issues / Risks
get_trading_state(): فعلاً برای آگاه UNVERIFIED برمی‌گرداند (طبق Decision 017). نیاز به پیاده‌سازی واقعی دارد.

OrderEngine: هنوز با AgaahInstrumentProvider یکپارچه نشده است.

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
ما در انتهای فاز ۴ (نگاشت شناسه‌ها) قرار داریم و در آستانه‌ی فاز ۵ (یکپارچه‌سازی Order Engine) هستیم.

Milestone فعلی: تکمیل AgaahInstrumentProvider و تأیید نگاشت.

وضعیت: ✅ کامل و commit شده (2020f92).

11. Next Step
گام منطقی بعدی، یکپارچه‌سازی AgaahInstrumentProvider با OrderEngine است تا:

OrderEngine بتواند nscId را از insCode دریافت کند.

سفارش‌ها (ابتدا در حالت dry-run) ثبت شوند.

سپس get_trading_state برای آگاه پیاده‌سازی شود تا وضعیت معاملاتی واقعی بررسی شود.

پیشنهاد من: ابتدا OrderEngine را اصلاح کنیم تا از InstrumentProvider استفاده کند و سپس get_trading_state را تکمیل کنیم.

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
Date: 1405/06/20 (2026-09-04)

Project State: آماده برای فاز بعدی (یکپارچه‌سازی Order Engine)

Last Completed Milestone: پیاده‌سازی و تأیید AgaahInstrumentProvider (commit 2020f92)

Current Milestone: یکپارچه‌سازی OrderEngine و get_trading_state

Next Action: اصلاح OrderEngine برای استفاده از InstrumentProvider و سپس پیاده‌سازی get_trading_state برای آگاه

