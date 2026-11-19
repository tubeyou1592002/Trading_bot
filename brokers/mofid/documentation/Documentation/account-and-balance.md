# اطلاعات حساب و موجودی

## قدرت خرید قابل سفارش

| Path | Method | Schema قابل مشاهده | شواهد |
|---|---:|---|---|
| `/orders/api/order/money/order-entry?symbolIsin={symbolIsin}` | GET | ورودی `symbolIsin` از `encodeURIComponent` عبور می‌کند؛ پاسخ در کد به `buyingPower` و `credits[]` و `credits[].amount` دسترسی دارد. `buyingPower` و `amount` در جمع عددی به‌کار می‌روند، بنابراین نوع عددی محتمل است، نه schema رسمی | `main-JXOX7C46.js` L1 offset حدود 2,354,500؛ قطعی در کد، شبکه نامشاهد |

این endpoint در کد به سرویس `orders/api/` متصل است. مقدارهای قدرت خرید/اعتبار، شناسهٔ نماد واقعی یا اطلاعات حساب نمایش داده نشده‌اند.

## مانده‌ها و حساب‌های پرداخت

| Path | Method | یادداشت | شواهد |
|---|---:|---|---|
| `/finance/api/payment-account-balances` | GET | تابع نام‌گذاری‌شدهٔ `getBanksList` آن را مصرف می‌کند؛ response fields از کد قابل تعیین نیست | `main-JXOX7C46.js` L1 offset حدود 56k؛ قطعی در کد، شبکه نامشاهد |
| `/mofidcard/api/balance` | GET | موجودی کیف پول/کارت مفید، مجزا از ماندهٔ معاملاتی اوراق؛ response schema عملیاتی از Network تأیید نشده | `main-JXOX7C46.js` L1 offset حدود 406k؛ قطعی در کد، شبکه نامشاهد |
| `/mofidcard/api/user-info` | GET | endpoint کیف پول/کارت؛ فیلدهای هویتی/حساب عمداً در این سند استخراج نشده‌اند | `main-JXOX7C46.js` L1 offset حدود 406k؛ قطعی در کد، شبکه نامشاهد |

برای `balance` نمونهٔ mock در bundle وجود دارد؛ آن داده mock است و به عنوان response واقعی یا schema سرور استفاده نشده است.

## پورتفوی و بازده

- `GET /assetmodule/api/performance`
- `GET /assetmodule/api/performance/AssetValue?symbolIsin={optional}&startfrom={value}`؛ کد از `items` استفاده می‌کند.
- `GET /assetmodule/api/performance/history?symbolIsin={value}&skip={value}&take={value}`؛ کد `items` را map می‌کند. `skip` و `take` از ورودی به رشته تبدیل می‌شوند؛ نوع semantic آن‌ها محتمل است عددی باشد.
- `GET /assetmodule/api/performance/sold/concise`
- `POST /assetmodule/api/performance/sold` با body `{symbolIsins: [...]}`؛ کد response را از `items` می‌گیرد.
- `GET /assetmodule/api/return-tracker/return`
- `POST /assetmodule/api/return-tracker/cash-flows` با body object ورودیِ نامشخص.

شواهد JavaScript: `main-JXOX7C46.js` L1 offsets حدود 1,084,500 تا 1,085,700؛ مسیرهای خانواده در کد قطعی‌اند. شواهد Network: `GET /assetmodule/api/performance` و schema پاک‌سازی‌شدهٔ آن با HTTP 200 در [Network Discovery](network-discovery.md) ثبت شده است. سایر مسیرهای این فهرست در این اسناد شواهد شبکه‌ای ندارند؛ پاسخ‌های تاریخچه و statusهای آن‌ها نامشخص‌اند.

## شواهد شبکه پس از ورود

شواهد Network در [Network Discovery](network-discovery.md) ثبت شده‌اند:

| Method | Path دقیق | Status | Schema پاسخ پاک‌سازی‌شده |
|---|---|---:|---|
| GET | `/easy/api/money` | 200 | object؛ نام فیلدها و نوع همگی number |
| GET | `/assetmodule/api/performance` | 200 | `{items: array<object>}`؛ نمونهٔ فیلدها در Network Discovery آمده است |
| GET | `/option-asset/api/Assets/positions-profit-loss?lastInvestmentPeriod={boolean}` | 200 | `{openPositionsProfitLoss:number, closedPositionsProfitLoss:number}` |

مسیر code-only `/orders/api/order/money/order-entry` در درخواست‌های طبیعی این صفحه دیده نشد. این سه نمونه شواهد مشاهده‌شده‌اند، نه قرارداد رسمی API؛ هیچ مقدار مالی یا شناسه‌ای در این سند ثبت نشده است.

## زنجیرهٔ مصرف پول و دارایی پرتفوی در فرم سفارش

- **پول:** JavaScript سرویس Money در شروع برنامه `GET /easy/api/money` را برای snapshot اجرا می‌کند و به‌طور جداگانه subscription به Lightstreamer topic `money` را آغاز می‌کند. هر دو مسیر در Money store ادغام می‌شوند؛ facade از تغییرات store رویداد `money.all` را منتشر می‌کند و فرم `AccountBalance` را از `money.all.data.buyPowerT2` می‌سازد. Network موجود endpoint REST را با HTTP `200` و `buyPowerT2:number` تأیید می‌کند. handshakeهای Lightstreamer ثبت شده‌اند، ولی schema پیام money در Network نداریم.
- **دارایی نماد:** JavaScript از `GET /assetmodule/api/performance`، آرایهٔ `items` را می‌گیرد و در portfolio store نگه می‌دارد. producer مقدار `asset` هر نماد را در `portfolio.items` منتشر می‌کند؛ فرم مورد متناظر را با `symbolIsin` انتخاب می‌کند و حداکثر فروش را از `asset` می‌گیرد. Network endpoint را با HTTP `200` و نوع `asset:number` در نمونهٔ schema تأیید می‌کند؛ مسیرهای احتمالی update لحظه‌ای دارایی در capture موجود تعیین نشده‌اند. مقادیر واقعی حذف شده‌اند.

تفصیل زنجیرهٔ `MarketData` و captureهای لازم در [ظرفیت خرید و فروش](buying-selling-capacity.md) آمده است.
