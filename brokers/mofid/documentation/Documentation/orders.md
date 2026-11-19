# سفارش‌ها

**هشدار شواهد:** مسیرهای تغییر وضعیت سفارش فقط از JavaScript استخراج شده‌اند. هیچ‌کدام فراخوانی یا بازپخش نشده‌اند.

## OMS سفارش عادی

| عملکرد | Path | Method | Request fields / response | محل |
|---|---|---:|---|---|
| فهرست سفارش‌ها | `/core/api/order` | GET | کد از `orders` و `algoSuffixCharacters` استفاده می‌کند؛ schema عناصر سفارش نامشخص | `main-JXOX7C46.js` L1 offset حدود 2,249,365 |
| ثبت سفارش | `/core/api/v2/order` | POST | body `{order: ...}`؛ مدل داخلی سفارش نامشخص | همان فایل، offset حدود 2,249,644 |
| ویرایش سفارش | `/core/api/v2/order` | PUT | body `{modifyOrder: ...}` | همان فایل، offset حدود 2,249,900 |
| لغو سفارش | `/core/api/v2/delete-order` | DELETE | body `{orderId, orderFrom}`؛ نوع دقیق شناسه/منبع نامشخص | همان فایل، offset حدود 2,250,000 |
| ثبت گروهی | `/core/api/order/batchCreate` | POST | body متغیر `e`؛ schema نامشخص | همان فایل، offset حدود 2,263,800 |
| حذف گروهی | `/core/api/order/batchDelete` | POST | body متغیر `e`؛ schema نامشخص | همان فایل، offset حدود 2,250,200 |

در wrapper کد سفارش عادی برای پاسخ خطا branch روی `status === 429` دارد و پیام محدودیت سفارش در ساعت نشان می‌دهد. این فقط رفتار و متن client است؛ status یا سقف عملیاتی شبکه‌ای تأیید نشده است.

## چرخهٔ order-place از MarketSheet

- `POST /ms/api/MarketSheet/order-place?actionType={actionType}` با body از سفارش‌های فیلترشده؛ پاسخ از `orderPlaces` خوانده می‌شود.
- `GET /ms/api/MarketSheet/order-place?actionType={push|get}` با header به نام `order-id`؛ پاسخ از `orderPlaces` خوانده می‌شود.
- منبع: `main-JXOX7C46.js` L1 offsets حدود 2,248,500–2,249,200.

## سفارش آپشن

- `POST /option/api/Orders/{side}` و `PUT /option/api/Orders/{side}`؛ body از مدل سفارش ساخته می‌شود و `side` از body حذف و در مسیر قرار می‌گیرد. پاسخ موفق از header `X-Order-Id` شناسهٔ سفارش می‌خواند؛ مقدار واقعی درج نشده است. `main-JXOX7C46.js` L1 offsets حدود 2,267,400–2,267,900.
- `DELETE /option/api/Orders` با `{orderId, orderFrom}`.
- `DELETE /option/api/Orders/bulk` با `{ordersId, orderFrom}`.
- حاشیه: `POST /option/api/Orders/margin/{add|update}` با مدل ورودی سفارش و `orderFrom`.
- اطلاعات/سود و زیان: `GET /option-asset/api/Assets/{id}?lastInvestmentPeriod=false` و `GET /option-asset/api/Assets/positions-profit-loss?lastInvestmentPeriod={boolean}`.
- منابع: `main-JXOX7C46.js` L1 offset حدود 2,267k و `chunk-BKX6pD38.js` L1 offsets حدود 23,900–24,200.

## سفارش‌های تأییدنشده

- `GET /unrequested-orders/api/order/hasPending`
- `GET /unrequested-orders/api/order/pending`
- `GET /unrequested-orders/api/order/oms-status`
- `PUT /unrequested-orders/api/order/approve-all`
- `POST /unrequested-orders/api/order/{id}/approve` با body خالی/null

منبع: `main-JXOX7C46.js` L1 offsets حدود 2,296,500–2,298,000. سه مسیر نخست در کد فقط خواندنی‌اند؛ دو مسیر آخر تغییر وضعیت ایجاد می‌کنند و اجرا نشده‌اند.

## استراتژی و draft آپشن

در `chunk-BKX6pD38.js`، L1 offsets حدود 22,000–24,000:

- `GET /option/api/Strategies/{type}/{id}`
- `PUT /option/api/Strategies/{type}` با `{strategyId, quantity}`
- `DELETE /option/api/Strategies/{type}?StrategyId={id}`
- `POST /option/api/Strategies/history` با object ورودی نامشخص
- `GET /option/api/StrategyDrafts` و `GET /option/api/StrategyDrafts/{id}`
- `POST` و `PUT /option/api/StrategyDrafts/Custom` با مدل draft نامشخص
- `DELETE /option/api/StrategyDrafts/{id}`

این مسیرها کد-قطعی و شبکه-تأییدنشده‌اند. هیچ مقدار شناسه، سفارش یا draft ثبت نشده است.

## Network Discovery پس از ورود

`GET /core/api/order` (دو مشاهده)، `GET /algo/api/order/active` و `GET /unrequested-orders/api/order/hasPending` با `200` تأیید شدند. responseهای ثبت‌شده برای schema عنصر سفارش کافی نبودند؛ مقدار یا وضعیت واقعی سفارش گزارش نشده است. هیچ POST/PUT/DELETE سفارش اجرا نشد. تفاوت response اولیه با پذیرش بورس و مسیر پیام‌های accepted/rejected/partial-fill هنوز **نامشخص شبکه‌ای** است؛ طرح آزمایشی sandbox اجرا نشده در [گزارش Network Discovery](network-discovery.md) آمده است.

## Network Discovery — ثبت دستی مشاهده‌شده

پس از اعلام کاربر که سفارش را از رابط کاربری فرستاده، یک `POST /core/api/v2/order` با status `200` مشاهده شد. Request Content-Type برابر `application/json` و Response Content-Type برابر `application/json; charset=utf-8` بود. Schema پاک‌سازی‌شدهٔ request و response، پاسخ اولیه و محدودیت تفسیر آن در [گزارش Network Discovery](network-discovery.md#مشاهدهٔ-سفارش-دستی-کاربر--شواهد-شبکه) ثبت شده است.

در لاگ بعدی، status/event منتسب به همان سفارش برای پذیرش، رد، انجام جزئی یا کامل دیده نشد. بنابراین شواهد شبکه فقط پاسخ اولیهٔ backend را ثابت می‌کند؛ پذیرش نهایی بورس و پیوند آن با پاسخ اولیه نامشخص است. هیچ درخواست ثبت، اصلاح یا لغوی از سوی بررسی‌کننده ارسال یا بازپخش نشد. این مشاهده از شواهد JavaScript بالا مستقل است.

## نتیجهٔ همان درخواست دستی با پیام محدودیت زمانی

بازخوانی read-only پاسخ موجود `POST /core/api/v2/order` نشان داد: HTTP `200`, `isSuccessful:false`, `omsError:null`, `message` با پیام محدودهٔ زمانی نامعتبر منطبق، و `id` رشتهٔ خالی. بنابراین HTTP موفق به معنی موفقیت عملیات نیست؛ پاسخ نشان می‌دهد backend درخواست را برای محدودیت زمانی ناموفق دانسته و شناسهٔ سفارش قابل استفاده نداده است. این پاسخ به‌تنهایی وضعیت مستقل بورس را ثابت نمی‌کند؛ پذیرش یا ثبت نهایی بورس در شواهد موجود **تأیید نشده** است. هیچ درخواست جدید یا سفارش دیگری انجام نشد.

## حضور سفارش ناموفق در فهرست‌ها — وضعیت شواهد

GETهای قبلی `/core/api/order` و `/algo/api/order/active` پیش از POST ناموفق بودند و GET تازه‌ای از فهرست پس از آن مشاهده نشد. پس نمی‌توان تعیین کرد سفارش ناموفق ظاهر شده یا نه. schema هر عنصر `orders` نیز `unknown` بود، بنابراین نمایش سفارش‌های ردشده در این فهرست تأیید نشده است.

کد عمومی مسیرهای جداگانهٔ `GET /unrequested-orders/api/order/pending` و `GET /unrequested-orders/api/order/oms-status` را نشان می‌دهد و از `ordersStatus[].orderId` و `orderState` استفاده می‌کند؛ این مسیرها برای این سفارش در Network مشاهده نشدند. شواهد و تفکیک Network/JavaScript در [گزارش Network Discovery](network-discovery.md#آیا-سفارش-ناموفق-در-فهرست-سفارشها-دیده-میشود) آمده است.
