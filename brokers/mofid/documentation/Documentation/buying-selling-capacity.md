# ظرفیت خرید و فروش

## موارد شناسایی‌شده

| عملکرد | Path | Method | فیلدها و نوع محتمل | شواهد |
|---|---|---:|---|---|
| قدرت خرید برای نماد | `/orders/api/order/money/order-entry?symbolIsin={}` | GET | query `symbolIsin`؛ response `buyingPower` و `credits[]` با `amount`. مقدارهای قدرت/اعتبار در جمع عددی‌اند؛ `number` محتمل، تأییدنشده | `main-JXOX7C46.js` L1 offset حدود 2,354,500 |
| حاشیهٔ موردنیاز آپشن | `/option/api/Orders/margin/{add\|update}` | POST | body شامل دادهٔ سفارش ورودی به همراه `orderFrom`; جزئیات مدل نامشخص | `main-JXOX7C46.js` L1 offset 2,370,976 |
| دسترس‌پذیری استراتژی Covered Call | `/option/api/Strategies/CoveredCall/order/{id}/available` | GET | پاسخ در wrapper با `baseIsin` و `availabilityType` ترکیب می‌شود؛ schema خام نامشخص | همان فایل، offset حدود 2,371,100 |
| دسترس‌پذیری استراتژی Gamma | `/option/api/Strategies/Gamma/order/{id}/available?gammaType={}` | GET | `gammaType` از نوع enum در کد انتخاب می‌شود؛ نوع wire معلوم نیست | همان فایل، offset حدود 2,371,300 |

## ظرفیت مجاز خرید/فروش نماد

خواص نماد `canBuy` و `canSell` در UI به شکل شرطی/boolean مصرف می‌شوند. همچنین `baseVol`, `buyCommission`, `sellCommission`, `symbolName`, `title`, `manner`, `isCaution` از دادهٔ نماد map می‌شوند (`main-JXOX7C46.js` L1 offset حدود 1,090,500). نوع دقیق wire فقط برای برخی خواص از تبدیل عددی/شرطی محتمل است.

در فایل‌های بررسی‌شده endpointی با نام صریح `buyingCapacity` یا `sellingCapacity` پیدا نشد. `capacityUsed` در گزارش واژه‌یابی عمدتاً مربوط به ظرفیت متن/جلسهٔ chatbot است و نباید به ظرفیت معاملاتی نسبت داده شود.

## وضعیت

این endpointها فقط در کد دیده شده‌اند؛ status واقعی، قواعد کارگزاری، نیازمندی احراز هویت و تفاوت ظرفیت با order-entry در شبکه تأیید نشده است. هیچ endpoint ظرفیت فراخوانی نشد.

## شواهد شبکه پس از ورود

`GET /easy/api/money` با `200` فیلدهای عددی `buyPowerT0`, `buyPowerT1`, `buyPowerT2` و گروهی از مانده/مسدودی‌ها را برگرداند؛ مقادیر حذف شده‌اند. endpoint نماد-محور `/orders/api/order/money/order-entry` و APIهای حاشیهٔ آپشن در این بارگذاری شبکه دیده نشدند و در حال حاضر فقط شواهد کد دارند.

## بررسی Network در جریان طبیعی فرم خرید

در لاگ نشست مورخ 2026-11-13، درخواست‌های جست‌وجو و بارگذاری داده‌های نماد مشاهده شدند. در بازهٔ بررسی‌شده تا ارسال فرم، `GET /orders/api/order/money/order-entry` دیده نشد؛ بنابراین ارتباط زمانی درخواست شبکه‌ای ظرفیت با نمایش حداقل/حداکثر تعداد در این نمونه قابل تأیید نیست. هیچ endpoint مستقل ظرفیت فروش نیز شناسایی نشد.

ثبت سفارش طبیعی کاربر با `POST /core/api/v2/order` و status `200` انجام شد، اما پاسخ پاک‌سازی‌شده `{isSuccessful:boolean, id:string, message:string, omsError:null}` مقدار `isSuccessful:false` داشت و پیام خطای محدودیت زمانی ثبت شده است. این درخواست تغییردهنده صرفاً به‌عنوان شاهد عملیات کاربر مستند شده، نه آزمون ظرفیت. وضعیت پذیرش در OMS/بورس از شواهد موجود نامشخص است.

**تفکیک شواهد:** `order-entry` همچنان فقط JavaScript-only است (پارامتر `symbolIsin` و دسترسی کد به `buyingPower` و `credits[].amount`). هیچ پاسخ Network برای آن در این جریان ثبت نشد. مقادیر سفارش و شناسه‌ها نگهداری نشده‌اند.

## تحلیل عمیق JavaScript: حداقل و حداکثر مقدار

در `main-JXOX7C46.js`، کامپوننت مقدار فرم `minQuantity` و `maxQuantity` را محاسبه می‌کند و به `option-form-value` می‌دهد. این محاسبات client-side هستند؛ ورودی‌هایشان از stateهای فرم/نماد/حساب می‌آیند.

- حدود حجم مجاز از `MarketData` خوانده می‌شوند. map سمت به فیلدها چنین است: خرید `minValidBuyVolume` و `maxValidBuyVolume`؛ فروش `minValidSellVolume` و `maxValidSellVolume`.
- خرید: `maxQuantity` از `AccountBalance` (مصرف‌کنندهٔ رویداد `money.all`, فیلد `buyPowerT2`) و قیمت، کارمزد، تنظیمات قیمت پنهان/اندازه قرارداد و حدود حجم مجاز محاسبه و به `minDealableCount` گرد می‌شود. حداقل خرید از حداقل قابل معاملهٔ نماد که با `Vr$2(symbol, price)` محاسبه می‌شود، با سقف affordability مقایسه و به حدود حجم مجاز clamp می‌شود. در نمادهای option، حداقل قابل معامله از `minDealableCount` می‌آید.
- فروش: `maxQuantity` برابر دارایی نماد در `PortfolioSymbol.asset` است. حداقل فروش از تابع `Nr$3(symbol, price, asset, commission)` می‌آید و سپس به حدود حجم مجاز/`minDealableCount` clamp می‌شود. تابع برای نمادهای بازار TSE/IFB حداقل ارزش معامله را لحاظ می‌کند؛ جزئیات تابع در bundle است و این یادداشت قرارداد API محسوب نمی‌شود.
- `canBuy` و `canSell` در بخش‌های UI/portfolio برای فعال‌کردن اقدام خرید/فروش و ساخت دادهٔ نماد مصرف می‌شوند. در مسیر بازکردن فرم، بررسی مجوز سمت UI انجام می‌شود؛ این دو flag به تنهایی مقادیر حداقل/حداکثر را تولید نمی‌کنند.
- سرویس `getSymbolBuyPower(symbolIsin)` درخواست `/orders/api/order/money/order-entry?symbolIsin=...` را می‌سازد. پاسخ در تابع `jr$3` به صورت `buyingPower + sum(credits[].amount)` جمع می‌شود و برای آیتم خلاصه/راهنمای قدرت خرید نماد مصرف می‌شود. این فراخوانی تحت feature flag `BitwiseBasedBuyingPower` و وجود نماد انتخاب‌شده فعال می‌شود. بر اساس dataflow موجود، `order-entry` در محاسبهٔ `minQuantity`/`maxQuantity` به‌طور مستقیم استفاده نشده؛ حد خرید از `AccountBalance` و حدود/قیمت بازار محاسبه می‌شود.

## ارزیابی Network برای این نشست

در Network موجود، نماد و داده‌های بازار/پرتفوی قبلاً بارگذاری شده‌اند و درخواست ثبت سفارش دیده می‌شود، اما `GET /orders/api/order/money/order-entry` در فهرست درخواست‌ها وجود ندارد. بنابراین رفتار runtime feature flag، پاسخ واقعی `order-entry` و ارتباط زمانی آن با فرم در این capture نامشخص است. در زمان این بازبینی فرم سفارش بسته بود؛ درخواست جدیدی ایجاد نشد. برای تأیید runtime باید کاربر فرم را دستی باز کند و سپس فقط درخواست‌های Fetch/XHR تازه بررسی شوند.

**نتیجه:** منبع عددهای حداقل/حداکثر در JavaScript به‌صورت غیرمستقیم شناسایی شد: محاسبهٔ مرورگر از MarketData limits, قیمت/کارمزد, buyPowerT2 و portfolio asset. منبع نهایی Network برای حدود نماد/قیمت و مسیر symbol buy-power هنوز کامل نیست؛ نسبت دادن همهٔ اعداد به یک API واحد قطعی نیست.

## ردیابی منابع دادهٔ پایه — بررسی JavaScript و Network موجود

### قدرت خرید / `AccountBalance`

**JavaScript (code-only):** سرویس Money با `GET /easy/api/money` مقدار اولیه را می‌گیرد (`getUserMoneyInfo`). همان سرویس هنگام راه‌اندازی `subscribeToLs()` را نیز dispatch می‌کند و Lightstreamer را با topic `money` و adapter `SLE_ADAPTER` گوش می‌دهد. نتیجهٔ REST در store با رویداد `Money.setMoney` ذخیره می‌شود؛ consumer/store آن را به رویداد برنامه‌ای `money.all` منتشر می‌کند. به‌روزرسانی‌های stream نیز فیلدهای numeric را parse کرده و با همان `setMoney` وارد store می‌کنند؛ در نتیجه `money.all` هم از مقدار اولیهٔ REST و هم از updateهای stream تغذیه می‌شود. `AccountBalance` مقدار `money.all.data.buyPowerT2` را می‌خواند. مقدار واقعی حساب در این سند درج نمی‌شود.

**Network موجود:** `GET /easy/api/money` با HTTP `200` مشاهده شده و schema پاک‌سازی‌شده‌اش در `network-discovery.md` شامل `buyPowerT2:number` است. سابقهٔ نشست همچنین handshakeهای Lightstreamer را با HTTP `200` ثبت کرده، اما پیام subscription/topic و updateهای money را با schema فیلدبه‌فیلد ثبت نکرده است.

**ارزیابی:** endpoint REST برای snapshot پول Network-confirmed است. نسبت‌دادن updateهای بعدی `money.all` به stream از JavaScript قطعی، ولی payload آن در Network این نشست تأیید نشده است.

### دارایی نماد در پرتفوی / حداکثر فروش

**JavaScript (code-only):** `PortfolioFacade.getPortfolioItems()` پاسخ `GET /assetmodule/api/performance` را از `items` برمی‌دارد؛ effect بارگذاری portfolio آن را به store می‌نویسد. producer پرتفوی برای هر نماد رویداد `portfolio.items` را با فیلدهای لازم از جمله `symbolIsin` و `asset` منتشر می‌کند. `PortfolioSymbol` فرم، ردیف متناظر با نماد انتخابی را از این state می‌یابد و `asset` را به `symbolQuantity` می‌دهد؛ `maxQuantity` سمت فروش از همان مقدار `symbolQuantity` می‌آید.

**Network موجود:** `GET /assetmodule/api/performance` با HTTP `200` مشاهده شده است؛ schema پاک‌سازی‌شده `{items: array<object>}` و نمونهٔ field `asset:number` در `network-discovery.md` آمده است. مقدارهای دارایی و شناسه‌های واقعی استفاده نشده‌اند.

**ارزیابی:** endpoint REST عملکرد/پرتفوی و وجود field `asset` Network-confirmed است؛ انتقال همان آیتم از store و مصرف در max sell، JavaScript-confirmed است. به‌روزرسانی لحظه‌ای دارایی یا مسیر مستقل holdings در Network فعلی تأیید نشده است.

### حدود `MarketData`

**JavaScript (code-only):** فرم از شیء `MarketData` و بر اساس side یکی از این جفت فیلدها را انتخاب می‌کند: `minValidBuyVolume`/`maxValidBuyVolume` یا `minValidSellVolume`/`maxValidSellVolume`. mapper در `chunk-miVgflIQ.js` کلیدهای خام `min-valid-buy-volume`, `max-valid-buy-volume`, `min-valid-sell-volume`, `max-valid-sell-volume` را به این فیلدها تبدیل کرده و با unary numeric conversion/zero fallback مقدار عددی می‌سازد. سرویس HTTP `GetMarketData` به `POST /symbols/api/marketdata/v2` وصل است، اما mapper پاسخ این مسیر فقط `symbolIsin`, `bestBuyQuantity`, `bestSellQuantity`, `lowPrice`, `highPrice` را برای مدل ساده map می‌کند؛ مدرک فعلی ثابت نمی‌کند همین چهار valid-volume limit از پاسخ این POST آمده باشند. کد همچنین Lightstreamer consumer و mapper برای symbol data دارد؛ تعیین payload واقعیِ حاوی این چهار کلید به Network نیاز دارد.

**Network موجود:** `POST /symbols/api/marketdata/v2` در فهرست Network نشست بررسی‌شده نیامده است. handshake ایجاد نشست Lightstreamer با `200` قبلاً دیده شده، اما schema پیام topic `symbol` یا presence/type این چهار کلید ثبت نشده است.

**ارزیابی:** وجود و تبدیل فیلدها در JavaScript Code-only؛ endpoint/stream اولیه و پاسخ Network تأمین‌کنندهٔ این چهار حد Unknown.

## Capture طبیعی لازم برای بستن شکاف‌ها

1. پس از ورود دستی، بارگذاری طبیعی صفحهٔ اصلی را برای snapshot `GET /easy/api/money` و شروع stream ثبت کنیم؛ فقط Method/Path/status/schema پاک‌سازی‌شده، بدون body خام یا مقدارها.
2. کاربر بخش پرتفوی را باز کند یا صبر کند تا holdings به‌طور طبیعی بار شوند؛ درخواست تازهٔ performance/portfolio و فقط schema فیلد `asset` را ثبت کنیم. هیچ نمادی را دستی API نکنیم.
3. کاربر یک نماد را انتخاب و فرم خرید، سپس در صورت تمایل فرم فروش را باز کند؛ درخواست‌های Fetch/XHR تازه، زمان آن‌ها نسبت به نمایش rangeها، و فقط نام/type فیلدهای پاسخ را بررسی کنیم. اگر DevTools MCP ترافیک stream را فهرست نکند، payload از آن استخراج‌شده تلقی نشود.
4. برای هر درخواست، از بررسی/ذخیرهٔ مقدارها، headerهای محرمانه، شناسه‌ها و body خام پرهیز شود؛ هیچ submit یا mutation انجام نشود.


## مشاهده دستی کاربر: حدود حجم سه نماد

نمونه‌های زیر مستقیماً توسط کاربر از فرم سفارش EasyTrader گزارش شده‌اند. آن‌ها **مشاهده دستی کاربر** هستند؛ Network-confirmed نیستند و منبع API یا stream را اثبات نمی‌کنند.

| نماد | حداقل خرید | حداکثر خرید | حداقل فروش | حداکثر فروش |
|---|---:|---:|---:|---:|
| خودرو | 1 | 3000000 | 1 | 3000000 |
| غشهد | 1 | 300000 | 1 | 300000 |
| سیمکات | 1 | 30000 | 1 | 30000 |

در هر سه نمونه سقف گزارش‌شدهٔ خرید و فروش برای همان نماد برابر است؛ سقف میان نمادها متفاوت است. در main-JXOX7C46.js، validRanges$ حداقل و حداکثر را با توجه به سمت سفارش از MarketData می‌خواند: خرید از minValidBuyVolume و maxValidBuyVolume، فروش از minValidSellVolume و maxValidSellVolume. بنابراین الگوی گزارش‌شده با ساختار انتخاب فیلدهای کد سازگار است، اما مقدارهای واقعی این propertyها در Network دیده نشده‌اند.

کد همچنین محاسبهٔ مقدار سفارش اولیه را با عوامل دیگری محدود می‌کند؛ از جمله قدرت خرید/قیمت/کارمزد در خرید و دارایی پرتفوی در فروش. پس این نمونه‌ها به‌تنهایی نشان نمی‌دهند اعداد سقف دقیقاً از valid-volumeهای MarketData آمده‌اند یا از قید دیگری در نمایش/محاسبهٔ فرم اثر گرفته‌اند. منشأ مقادیر و API تأمین‌کننده همچنان نامشخص است.