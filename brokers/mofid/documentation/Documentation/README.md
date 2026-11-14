# مستندات بررسی API مفید / EasyTrader

تاریخ بررسی: 2026-11-13

## خلاصه مدیریتی

**به‌روزرسانی 2026-11-14:** کاربر ورود مفید را در Trading_bot و نمایش قدرت خرید را به‌صورت دستی تأیید کرده است. این فقط تأیید ورود و خواندن قدرت خرید است؛ هیچ سفارش یا اجرای زنده‌ای تست نشده است. جزئیات و محدودیت‌ها در [authentication.md](authentication.md) ثبت شده‌اند.

این مجموعه مستندات شواهد JavaScript عمومی و Network برنامه را جدا می‌کند. مسیرهای API نماد، بازار، قدرت خرید، دارایی، سفارش و خدمات جانبی در bundleهای عمومی شناسایی شده‌اند؛ endpointهای مهم در [فهرست API](api-catalog.md) و [Network Discovery](network-discovery.md) آمده‌اند.

در سابقهٔ مرورگر ایزوله، ورود دستی کاربر انجام شد. مسیرهای OIDC شامل metadata، authorize و token exchange در Network با statusهای ثبت‌شده مشاهده شدند؛ bodyها و داده‌های احراز هویت استخراج یا ذخیره نشدند. درخواست‌های نشست برنامه نیز به صورت محدود مستند شده‌اند. شرح جریان و موارد ناقص در [احراز هویت و مدیریت نشست](authentication.md) است.

شواهد Network برای برخی APIهای فقط‌خواندنی حساب، موجودی، بازار و فهرست سفارش وجود دارد. یک پاسخ اولیهٔ ناموفق ثبت سفارش دستی نیز با `isSuccessful:false` و خطای محدودیت زمانی دیده شد؛ پذیرش نهایی بورس تأیید نشد. هیچ درخواست API دستی یا سفارش تغییردهنده‌ای از سوی بررسی‌کننده ارسال یا بازپخش نشده است.

## وضعیت احراز هویت

- **Network تاریخی:** `GET /.well-known/openid-configuration` با 200، `GET /connect/authorize` با 303، `POST /connect/token` با 200، و `GET /easy/api/startsession` و `POST /easy/api/account/same-login` با 200 ثبت شده‌اند. schema token exchange و بدنه‌های نشست بررسی نشده‌اند.
- **JavaScript:** redirect callback، انتخاب storage، پشتیبانی کتابخانه از silent renew، logout redirect و شاخه‌های 401/403 در کد دیده شده‌اند؛ جزئیات و سطح اطمینان در `authentication.md` است.
- **محدودیت فعلی:** پس از راه‌اندازی مجدد/اتصال مجدد Chrome DevTools MCP، تنها صفحهٔ `about:blank` و صفر درخواست preserved در دسترس بود. بنابراین trace تاریخی برای بررسی جزئیات بیشتر قابل بازیابی نیست؛ ورود مجدد انجام نشده است و برای تکمیل موارد ناقص باید کاربر زمان آماده‌بودن را اعلام کند.

## نتیجه‌های دیگر بررسی

- سه endpoint حساب/موجودی در Network با HTTP 200 مشاهده شده‌اند: `GET /easy/api/money`، `GET /assetmodule/api/performance` و `GET /option-asset/api/Assets/positions-profit-loss`؛ schemaهای پاک‌سازی‌شده در [گزارش Network Discovery](network-discovery.md) آمده‌اند. سایر مسیرهای کد-محور به‌عنوان شواهد Network تلقی نمی‌شوند.
- در پوشهٔ محلی 58 فایل JavaScript وجود داشت؛ گزارش اسکن اولیه 61 مورد را شمرده بود. سه فایل پشتیبان در پوشهٔ اولیه نبودند. تاریخچهٔ بعدی 94 URL یکتای JavaScript را نشان داد که 36 مورد آن در پوشهٔ محلی موجود نبودند.
- Source Map عمومی در پوشهٔ JavaScript محلی پیدا نشد؛ اشاره‌های موجود در bundleها، وجود فایل map را ثابت نمی‌کنند.
- در مشاهدهٔ طبیعی فرم خرید، `GET /orders/api/order/money/order-entry` در Network دیده نشد؛ مسیر همچنان فقط در JavaScript مستند است. پاسخ `POST /core/api/v2/order` با HTTP 200 مقدار `isSuccessful:false` داشت، بنابراین عملیات موفق نبود و وضعیت بورس نامشخص است. جزئیات پاک‌سازی‌شده در `network-discovery.md` و `buying-selling-capacity.md` آمده است.
- هیچ تغییری در Trading_bot انجام نشده است.

## اسناد

- [احراز هویت و مدیریت نشست](authentication.md)
- [نقشهٔ راه ورود مفید به Trading_bot](mofid-login-roadmap.md)
- [گزارش Network Discovery](network-discovery.md)
- [حساب و موجودی](account-and-balance.md)
- [نمادها و بازار](symbols-and-market.md)
- [ظرفیت خرید و فروش](buying-selling-capacity.md)
- [سفارش‌ها](orders.md)
- [فهرست API](api-catalog.md)
- [معماری اتصال](integration-architecture.md)
- [موارد نامشخص و ریسک‌ها](unknowns-and-risks.md)
