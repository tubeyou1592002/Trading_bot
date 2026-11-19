# فهرست API و سرویس‌ها

`Base URL` اصلی که در تنظیمات Production bundle آمده و در لاگ build-number هم دیده شده: `https://api-mts.orbis.easytrader.ir/`. همهٔ مسیرهای زیر نسبت به همین base هستند، مگر جایی که صریحاً URL دیگری آمده باشد. Presence در JavaScript به معنای استفاده/پشتیبانی رسمی یا تأیید شبکه نیست.

## Endpointهای قطعی در کد

| خانواده | Path | Method | Schema قابل مشاهده | شواهد |
|---|---|---:|---|---|
| راه‌اندازی | `/boot/api/build-number?deviceType=1` | GET | query `deviceType`; response بررسی نشده | Network `200`; کد منبع درخواست در لاگ |
| حساب/نشست | `/easy/api/startsession` | GET | نام فیلدهای پاسخ نامشخص | `chunk-BO8VqOCp.js` L1 ~8.4k |
| حساب/نشست | `/easy/api/account/same-login` | POST | body شامل `uuid` و دادهٔ اضافی نامشخص | `main-JXOX7C46.js` L1 ~801k |
| حساب/نشست | `/easy/api/account/logout` | POST | body مشخص نشده | همان فایل L1 ~802.8k |
| حساب/نشست | `/easy/api/account/remove-sessions` | POST | body `{ids: array}` | همان فایل L1 ~386k |
| حساب | `/finance/api/payment-account-balances` | GET | response نامشخص | همان فایل L1 ~56k |
| قدرت خرید نماد | `/orders/api/order/money/order-entry?symbolIsin={}` | GET | JavaScript: پاسخ به `buyingPower + sum(credits[].amount)` تبدیل و برای خلاصه/راهنما مصرف می‌شود؛ مستقیماً در محاسبهٔ حداقل/حداکثر مقدار فرم دیده نشد. Network در capture موجود مشاهده نشد | فقط JavaScript `main-JXOX7C46.js` L1 ~2,354.5k |
| نماد | `/symbols/api/marketdata/v2` | POST | body array; response fields شامل `symbolIsin`, `bestBuyQuantity`, `bestSellQuantity`, `lowPrice`, `highPrice` | `chunk-miVgflIQ.js` L1 ~497.4k |
| نماد | `/symbols/api/MarketData/symbol-info-data` | POST | `{isin}` | همان فایل L1 ~497.8k |
| نماد | `/symbols/api/MarketData/tse-index` | GET | response array | همان فایل L1 ~522k |
| نماد | `/symbols/api/MarketData/indInstTrade` | POST | `{isin}` | `main-JXOX7C46.js` L1 ~1,993k |
| نماد | `/symbols/api/symbols/all` | POST | `{hash}` | همان فایل L1 ~3,841.7k |
| نماد | `/symbols/api/symbols/some` | POST | `{isins: array}` | همان فایل L1 ~3,841.8k |
| نماد | `/symbols/api/symbols/manners` | GET | response نامشخص | همان فایل L1 ~3,841.9k |
| نماد/بازار | `/easy/api/symbol-analysis/ind-inst?isin={}` | GET | response array و انتخاب عنصر اول | همان فایل L1 ~1,992.8k |
| بازار | `/market-data/api/v1/market-status/latest` | GET | response نامشخص | همان فایل L1 ~264k |
| بازار | `/symbols/api/MarketData/market-map` | GET | response نامشخص | همان فایل L1 ~2,845.4k |
| بازار | `/symbols/api/OptionMarketData/{Symbols\|BaseSymbols}/Map` | GET | response نامشخص | همان فایل L1 ~2,845.7k |
| بازار | `/ms/api/MarketSheet/all/{marketId}` | GET | `buySheets[]`, `sellSheets[]` | `chunk-C-XDM7Jf.js` L1 ~28.4k |
| بازار | `/easy/api/MarketWatch` | GET/POST/PUT/DELETE | GET response fields شامل `id`, `isDefault`, `name`, `order`, `createDateTime`, `watchCategorySymbols[].symbolIsin`; mutation schema در سند نمادها | `chunk-B9VcS7O8.js` L1 ~28.3k |
| بازار | `/easy/api/MarketWatch/symbols` | POST/DELETE | body متغیر؛ schema جزئی نامشخص | همان فایل L1 ~29.1k |
| پرتفو | `/assetmodule/api/performance` | GET | Network: `{items: array<object>}`؛ نمونهٔ فیلدها در `network-discovery.md` | Network HTTP 200؛ JavaScript `main-JXOX7C46.js` L1 ~1,084.5k |
| پرتفو | `/assetmodule/api/performance/AssetValue`, `/history`, `/sold[/concise]` | GET/POST | `items[]`; queryهای `symbolIsin`, `startfrom`, `skip`, `take`; sold body `{symbolIsins}` | فقط JavaScript؛ همان فایل L1 ~1,084.5k |
| پرتفو | `/assetmodule/api/return-tracker/return` | GET | response نامشخص | همان فایل L1 ~1,085.5k |
| پرتفو | `/assetmodule/api/return-tracker/cash-flows` | POST | body object نامشخص | همان فایل L1 ~1,085.6k |
| سفارش | `/core/api/order` | GET | `orders[]`, `algoSuffixCharacters` | همان فایل L1 ~2,249.4k |
| سفارش | `/core/api/v2/order` | POST | JavaScript: `{order: object}`؛ Network: `{isSuccessful:boolean, id:string, message:string, omsError:null}`؛ نمونه HTTP 200 با عملیات ناموفق | JavaScript `main-JXOX7C46.js` L1 ~2,249.6k؛ Network در جریان طبیعی 2026-11-13 |
| سفارش | `/core/api/v2/order` | PUT | `{modifyOrder: object}` | همان فایل L1 ~2,249.9k |
| سفارش | `/core/api/v2/delete-order` | DELETE | `{orderId, orderFrom}` | همان فایل L1 ~2,250k |
| سفارش | `/core/api/order/batchCreate` و `/batchDelete` | POST | body متغیر؛ schema نامشخص | همان فایل L1 ~2,263.8k و ~2,250.2k |
| سفارش | `/ms/api/MarketSheet/order-place?actionType={}` | POST/GET | POST body مجموعهٔ سفارش؛ GET header `order-id`; پاسخ از `orderPlaces` خوانده می‌شود | همان فایل L1 ~2,248.5k |
| سفارش | `/unrequested-orders/api/order/{pending,oms-status,hasPending}` | GET | pending array/status fields؛ `ordersStatus[].orderId`, `orderState` در کد مصرف می‌شود | همان فایل L1 ~2,296.5k |
| سفارش | `/unrequested-orders/api/order/approve-all` و `/order/{id}/approve` | PUT/POST | body خالی برای approve تکی؛ تغییر وضعیت | همان فایل L1 ~2,297.7k |
| آپشن | `/option/api/Orders/{side}` | POST/PUT | مدل سفارش، side در path؛ response header `X-Order-Id` | همان فایل L1 ~2,267.5k |
| آپشن | `/option/api/Orders` و `/Orders/bulk` | DELETE | `{orderId, orderFrom}` و `{ordersId, orderFrom}` | همان فایل L1 ~2,268k |
| آپشن | `/option/api/Orders/margin/{add\|update}` | POST | object سفارش + `orderFrom` | همان فایل L1 ~2,371k |
| آپشن | `/option/api/Strategies/CoveredCall/order/{id}/available` | GET | پاسخ خام نامشخص؛ wrapper از `baseIsin` استفاده می‌کند | همان فایل L1 ~2,371k |
| آپشن | `/option-asset/api/Assets/{id}` | GET | در این شواهد response مشخص نیست | فقط JavaScript `chunk-BKX6pD38.js` L1 ~23.9k |
| آپشن | `/option-asset/api/Assets/positions-profit-loss?lastInvestmentPeriod={boolean}` | GET | Network: `{openPositionsProfitLoss:number, closedPositionsProfitLoss:number}` | Network HTTP 200؛ JavaScript همان فایل L1 ~23.9k |
| کیف پول | `/mofidcard/api/balance` | GET | response fields از نمونهٔ واقعی مشخص نیست | `main-JXOX7C46.js` L1 ~406k |
| مالی/اعتبار | `/credit/api/pointxPoint` | GET | schema نامشخص | همان فایل L1 ~1,559.6k |
| IPO آفلاین | `/ipo/api/order` | POST؛ `/ipo/api/ipo/customer/offline-orders` POST؛ `/ipo/api/order` DELETE | بدنهٔ ثبت نامشخص؛ خواندن سفارش‌ها `{symbolIsins}`؛ حذف `{orderId}` | همان فایل L1 ~1,558.5k |

## Endpointهای دارای شواهد شبکه

- `GET https://api-mts.orbis.easytrader.ir/boot/api/build-number?deviceType=1` → `200`؛ فقط پاسخ عمومی راه‌اندازی. بدنه در این مستند ثبت نشده است.
- `GET https://login.emofid.com/.well-known/openid-configuration` → `200` و `GET https://login.emofid.com/connect/authorize` → `303`؛ مسیرهای عمومی ورود، مقادیر query حذف شده‌اند.
- Network حساب/موجودی: `GET /easy/api/money`، `GET /assetmodule/api/performance` و `GET /option-asset/api/Assets/positions-profit-loss?lastInvestmentPeriod={boolean}` همگی با HTTP `200` مشاهده شدند؛ schema پاک‌سازی‌شده در [Network Discovery](network-discovery.md) است.
- endpointهای دیگر فقط در صورت تصریح در شواهد Network تأییدشده محسوب می‌شوند؛ فهرست کد-محور به‌تنهایی شاهد Network نیست.

## Prefixهای سرویس تعریف‌شده در bundle

`chunk-miVgflIQ.js` L1 حدود offset 5.8k یک نگاشت prefix تعریف می‌کند. این‌ها فقط prefix هستند، نه endpointهای مستقل:

- `crm` → `crm/api/`; `oms` → `core/api/`; `orders` → `orders/api/`
- `option` → `option/api/`; `optionWorker` → `option-worker/api/`; `optionAsset` → `option-asset/api/`
- `algo` → `algo/api/order`; `algoHistory` → `algo/api/order-history`; `offline` → `algo/api/offline/`
- `symbol` → `symbols/api/`; `easy` → `easy/api/`; `portfolio` → `portfolio/api/`
- `finance` → `finance/api/`; `assets` → `assetmodule/api/`; `assetIntegration` → `asset-integration/api/v1/`
- `marketSheet` → `ms/api/MarketSheet/`; `marketData` → `market-data/api/v1/`; `miniChart` → `chart/api/v2/datafeed/miniChart/`
- `userEngagement` → `user-engagement/api/v2/`; `userEngagementV3` → `user-engagement/api/v3/`; `feedback` → `user-engagement/api/v3/feedback`
- `notification` → `notification/api/v1/`; `notificationV2` → `notification/api/v2/`
- همچنین: `ipg`, `smartIpgV1`, `smartIpgV2`, `smartIpgAdmin`, `notificationAdmin`, `easyAgentAdmin`, `fundVTwo`, `wallet`, `tbs`, `contract`, `marketReport`, `blockAsset`, `freeze`, `protectivePut`, `credit`, `transaction`, `symbolAiAnalysis`, `unrequestedOrders`, `cardIntegration`, `easyAgent`, `admin`, `admin_v2`, `assetIntegrationAdminV2`, `ipo`, `adminOptionAsset`, `ms`, `voc`.

Base URLهای stage/admin و سرویس‌های جانبی نیز در bundle هستند؛ وجودشان به معنای مجازبودن یا فعال‌بودن آن‌ها برای اتصال Trading_bot نیست.

## فیلدهای استاندارد قالب که شواهد آن‌ها موجود نیست

برای **هر endpoint کد-قطعی** در جدول بالا، مگر آن‌جا که خلافش صریحاً نوشته شده باشد:

- **نوع احراز هویت:** از کد عمومی به تنهایی مشخص نیست؛ نیاز به session/OIDC برای هر endpoint باید در ترافیک پس از ورود کاربر تأیید شود.
- **فیلدهای اجباری/اختیاری:** در bundle به عنوان قرارداد API اعلام نشده‌اند. حضور فیلد در call-site به معنی required بودن سرور نیست.
- **HTTP status codes:** نامشخص؛ به جز statusهای صریحاً مشاهده‌شده در بخش Network. branch `429` در client سفارش، وضعیت واقعی پاسخ سرور را ثابت نمی‌کند.
- **وابستگی بین APIها:** در مواردی که state/store client صریحاً response را به درخواست بعدی map می‌کند، در صفحهٔ مربوطه توضیح داده شد؛ dependency قراردادی سمت سرور نامشخص است.

برای `GET /boot/api/build-number`, نیاز به ورود مشاهده نشد و status شبکه‌ای `200` است. برای سه endpoint حساب/موجودی بالا statusهای `200` در Network ثبت شده‌اند. برای بقیهٔ endpointهای صرفاً کد-محور، status شبکه‌ای نامشخص است.

## شواهد شبکه پس از ورود

درصد قطعیت مسیرهای استاتیک با مشاهدهٔ درخواست واقعی یکی نیست. جدول و schemaهای پاسخ فقط در [گزارش جداگانهٔ Network Discovery](network-discovery.md) آمده‌اند؛ query value، بدنهٔ خام و مقدار فیلدهای مالی/حساب حذف شده‌اند. برای endpointهای فقط‌کد، status و auth همچنان نامشخص‌اند.

## منابع پایهٔ ظرفیت خرید و فروش — وضعیت شواهد

| منبع | Endpoint/جریان | نیاز مصرف‌کننده | Network | JavaScript |
|---|---|---|---|---|
| پول/مانده | `GET /easy/api/money` | `buyPowerT2:number` برای `AccountBalance` | HTTP 200 و schema در `network-discovery.md` | Money service → store → رویداد `money.all` → فرم |
| update پول | Lightstreamer topic `money`, adapter `SLE_ADAPTER` | در کد update شامل `buyPowerT2:number` | handshake دیده شده؛ topic payload/schema ثبت نشده | Code-only mapping به Money store |
| دارایی پرتفوی | `GET /assetmodule/api/performance` | `items[].symbolIsin:string`, `items[].asset:number` | HTTP 200؛ schema نمونه در `network-discovery.md` | performance service → portfolio store → `portfolio.items` → sell max |
| limits نماد | `POST /symbols/api/marketdata/v2` و/یا جریان symbol | چهار حد min/max خرید/فروش، در مدل عددی | این POST در capture موجود نیست؛ schema payload stream هم نداریم | endpoint در کد هست، اما اتصال قطعی چهار limit به پاسخ آن اثبات نشده؛ symbol mapper فیلدهای خام را تبدیل می‌کند |

این جدول source map قراردادی API نیست؛ statusهای Network فقط برای مسیرهایی ثبت شده‌اند که صریحاً در Network Discovery آمده‌اند.
