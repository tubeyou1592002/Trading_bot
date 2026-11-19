# معماری اتصال به Trading_bot

## معماری مشاهده‌شده در EasyTrader

1. Frontend عمومی روی `https://d.easytrader.ir` است.
2. تنظیمات production bundle، Base URL سرویس MTS را `https://api-mts.orbis.easytrader.ir/` مشخص می‌کند. مسیرهای HTTP در prefixهایی مانند `core/api/`, `orders/api/`, `symbols/api/`, `easy/api/` و `assetmodule/api/` قرار دارند.
3. احراز هویت از مسیر OIDC و `login.emofid.com` شروع می‌شود. تنظیم دقیق token transport برای APIهای خصوصی در شبکهٔ احرازشده مشاهده نشده است.
4. کد یک مسیر جداگانه برای live-data/LS دارد؛ bundle حاوی مصرف‌کننده‌های `listenToLs` است. نشانی production LS در تنظیمات دیده می‌شود، اما handshake و پیام‌های آن در لاگ این ممیزی تأیید نشده‌اند.
5. محیط stage هم در bundle تنظیم شده است؛ آن را با endpointهای production مخلوط نکنید.

## تطبیق با Trading_bot

اسناد معماری Trading_bot لایهٔ broker adapter جدا از Core را مقرر می‌کنند. در صورت ادامهٔ کار، EasyTrader باید به عنوان adapter مستقل اضافه شود و از مسیر موجود `Core → Broker Interface → Broker Adapter` استفاده کند. کد موجود را در این مأموریت تغییر ندادم.

## نتیجهٔ امکان‌پذیری

- **از نظر فنی:** بله، وجود REST-style HTTP client، base URLهای service-based، OIDC و APIهای نماد/سفارش نشان می‌دهد ایجاد adapter ممکن است.
- **برای خواندن عمومی/بازار:** بخش‌هایی از نماد و market data در کد عمومی قابل شناسایی‌اند، ولی شبکه و schema هنوز باید فقط با درخواست‌های عادی و read-only تأیید شود.
- **برای حساب/سفارش:** باید کاربر در مرورگر isolated وارد شود و اجازهٔ بررسی ترافیک read-only بدهد. هیچ order mutation نباید برای آزمون اجرا شود.
- **برای معاملهٔ واقعی:** تا روشن‌شدن مجوز رسمی، rate limits، semantics مدل سفارش، سازگاری شناسهٔ نماد و خطا/timeoutها، این مستند برای ارسال سفارش کافی نیست.

## الگوی پیشنهادی فقط در سطح معماری

ساختار مستقل `EasyTraderAdapter`، mapper صریح بین instrumentهای Trading_bot و شناسه‌های موردنیاز EasyTrader، و پشتیبانی fail-closed برای auth/timeout/unknown response. این پیشنهاد معماری است، نه تأیید قرارداد API یا تغییر کد.

## مشاهدهٔ شبکه پس از ورود

شبکهٔ واقعی، GETهای موفق برای مانده/قدرت خرید، performance، market data و snapshotهای سفارش را تأیید کرد؛ schemaها در `network-discovery.md` هستند. چون `POST /core/api/v2/order` اجرا نشد، اتصال عملیاتی هنوز از نظر پذیرش/رد/partial-fill یا وضعیت نهایی بورس ارزیابی نشده است.
