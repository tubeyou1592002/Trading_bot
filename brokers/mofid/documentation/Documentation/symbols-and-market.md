# نمادها و داده‌های بازار

تمام endpointهای این صفحه در JavaScript دیده شده‌اند؛ هیچ‌کدام جز سرویس build-number در لاگ شبکهٔ پیش از ورود تأیید نشده‌اند.

| Path | Method | ورودی/خروجی قابل استناد | منبع |
|---|---:|---|---|
| `/symbols/api/marketdata/v2` | POST | body آرایه‌ای از ورودی‌های market data؛ پاسخ map می‌شود و کد از `symbolIsin`, `bestBuyQuantity`, `bestSellQuantity`, `lowPrice`, `highPrice` استفاده می‌کند. نوع دقیق هر فیلد از سورس موجود معلوم نیست؛ کمیت/قیمت عددی محتمل است | `chunk-miVgflIQ.js` L1 offset 497,376 |
| `/symbols/api/MarketData/symbol-info-data` | POST | body `{isin: ...}`؛ پاسخ به صورت opaque مصرف می‌شود | همان فایل، offset 497,790 |
| `/symbols/api/MarketData/tse-index` | GET | response به صورت آرایه مصرف و اصلاح می‌شود؛ schema نامشخص | همان فایل، offset حدود 522k |
| `/symbols/api/MarketData/indInstTrade` | POST | body `{isin: ...}`؛ schema پاسخ نامشخص | `main-JXOX7C46.js` L1 offset 1,993,025 |
| `/easy/api/symbol-analysis/ind-inst?isin={isin}` | GET | response به صورت آرایه مصرف می‌شود و عنصر اول انتخاب می‌شود | `main-JXOX7C46.js` L1 offset 1,992,781 |
| `/symbols/api/MarketData/market-map` | GET | schema نامشخص | `main-JXOX7C46.js` L1 offset 2,845,400 |
| `/symbols/api/OptionMarketData/{Symbols\|BaseSymbols}/Map` | GET | مقدار مسیر بر اساس نوع نماد انتخاب می‌شود؛ schema نامشخص | همان فایل، offset حدود 2,845,700 |
| `/ms/api/MarketSheet/all/{marketId}` | GET | کد از `buySheets` و `sellSheets` استفاده می‌کند؛ `marketId` نام‌گذاری این سند است، نام پارامتر در bundle صرفاً متغیر فشرده‌شده است | `chunk-C-XDM7Jf.js` L1 offset 28,400 |
| `/market-data/api/v1/market-status/latest` | GET | schema نامشخص | `main-JXOX7C46.js` L1 offset 264,162 |
| `/symbols/api/symbols/all` | POST | body `{hash: ...}` | `main-JXOX7C46.js` L1 offset 3,841,657 |
| `/symbols/api/symbols/some` | POST | body `{isins: [...]}` | همان فایل، offset حدود 3,841,800 |
| `/symbols/api/symbols/manners` | GET | schema نامشخص | همان فایل، offset حدود 3,841,900 |
| `/easy/api/MarketWatch` | GET / POST / PUT / DELETE | GET به صورت آرایه‌ای map می‌شود؛ نام‌های مشاهده‌شده: `id`, `isDefault`, `name`, `order`, `createDateTime`, `watchCategorySymbols[].symbolIsin`. POST body ورودی object، PUT `{categories: ...}`، DELETE `{ids: ...}` | `chunk-B9VcS7O8.js` L1 offset 28,279 و 28,500–29,200 |
| `/easy/api/MarketWatch/symbols` | POST / DELETE | body ورودی نمادها، ساختار جزئی نامشخص | همان فایل، offset حدود 29k |

در `MarketWatch`، `id` با `.trim()` استفاده می‌شود؛ رشته‌ای بودن محتمل است. `createDateTime` به `Date` تبدیل می‌شود؛ نوع wire format نامشخص است. `isDefault` در منطق boolean استفاده می‌شود. این‌ها استنباط از مصرف کد هستند و schema رسمی نیستند.

## دادهٔ زنده

bundle مسیرهای `easy/api/market-live/...` از جمله `market-trading`, `industries/positive-negative-symbols`, `buying-queue`, `selling-queue`, `most-view`, `most-demand`, `most-supply`, `most-value`, `most-volume` و `index` را در کلیدهای داده ثبت می‌کند (`main-JXOX7C46.js` L1 offsets حدود 202k–210k). در آن محل‌ها HTTP method قابل تعیین نیست؛ ممکن است مصرف از لایهٔ live-data/کش باشد. بنابراین متدها **نامشخص** و شبکه نیز تأییدنشده است.

## شواهد شبکه پس از ورود

GETهای `TradingTime`, `tse-index`, `MarketWatch`, market-live industry indicators, symbol analysis, mini-chart history و MarketSheet sum با statusهای موفق مشاهده شدند. query valueها و شناسهٔ نماد واقعی حذف شدند؛ schemaهای پاک‌سازی‌شده در [Network Discovery](network-discovery.md) آمده‌اند.
