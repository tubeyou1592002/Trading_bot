# Network Discovery — شواهد شبکه

تاریخ: 2026-11-13. بخش‌های اولیه این گزارش درخواست‌های `GET` عادی پس از ورود دستی را پوشش می‌دهند. در مرحلهٔ بعد، کاربر اعلام کرد سفارش را شخصاً از رابط EasyTrader فرستاده است؛ فقط درخواست ثبت‌شدهٔ همان اقدام و پاسخ آن به‌صورت ایستا و پاک‌سازی‌شده بررسی شد. هیچ درخواست تغییردهنده‌ای از سوی بررسی‌کننده ارسال یا بازپخش نشد. بدنهٔ خام و مقدارهای حساس در مستندات نیامده‌اند.

Base URL درخواست‌های برنامه در این بخش: `https://api-mts.orbis.easytrader.ir`. مسیرهای پارامتری و query valueها به placeholder تبدیل شده‌اند. Schemaهای JSON از نام فیلدها و نوع مقدارها خلاصه شده‌اند؛ برای آرایهٔ خالی، نوع عنصر نامشخص است. این نمونه‌ها قرارداد رسمی API نیستند.

## حساب، مانده و قدرت خرید

| Method | Path | Status | Request schema | Response schema پاک‌سازی‌شده |
|---|---|---:|---|---|
| GET | `/easy/api/money` | 200 | بدون query/body | object؛ `t0`, `t1`, `t2`, `buyPowerT0`, `buyPowerT1`, `buyPowerT2`, `blockT2`, `withdrawBlockT2`, `marginBlock`, `credit`, `avandCredit`, `walletWithdrawBalanceT0`, `warrantValueCredit`, `hamiBalance`, `block`: همگی `number` |
| GET | `/assetmodule/api/performance` | 200 | بدون query/body | `{items: array<object>}`؛ نمونه شامل `symbolIsin:string`, `symbolName:string` (مقدار حذف‌شده), `date:string`, `persianDate:number`, `asset:number`, `bonusShareVolume:number`, `stockRightVolume:number`, `periodicDPSAmount:number`, `lastDPSAmount:number`, `totalDPSAmount:number`, `breakevenPoint:number`, `periodicBuyAveragePrice:number`, `totalBuyAveragePrice:number`, `periodicBuyAmount:number`, `totalBuyAmount:number`, `periodicSellAveragePrice:number`, `totalSellAveragePrice:number`, `periodicSellAmount:number`, `totalSellAmount:number`, `periodicBoughtVolume:number`, `totalBoughtVolume:number`, `periodicSoldVolume:number`, `totalSoldVolume:number`, `periodicRealizedProfitAndLoss:number`, `totalRealizedProfitAndLoss:number`, `calculationVersion:string` و فیلدهای عددی مشابه برای DPS/P&L/حجم |
| GET | `/option-asset/api/Assets/positions-profit-loss?lastInvestmentPeriod={boolean}` | 200 | query `lastInvestmentPeriod`; مقدار حذف شد | `{openPositionsProfitLoss:number, closedPositionsProfitLoss:number}` |
| GET | `/easy/api/startsession` | 200 | بدون query/body | `{serverTime:string, startSessionTimeStamp:string}` |
| GET | `/easy/api/account/server-time/{timestamp}` | 200 (۵ مشاهده) | path param `timestamp` عددی/زمانی؛ مقدار حذف شد | `{diff:number, serverTimestamp:number}` |
| GET | `/finance/api/customers/has-children` | 200 | بدون query/body | body برای جلوگیری از استخراج دادهٔ رابطهٔ حساب بررسی نشد |
| GET | `/credit/api/isCreditCustomer` | 200 | بدون query/body | body بررسی نشد؛ schema نامشخص |
| GET | `/easy/api/StockCondition` | 200 | بدون query/body | body بررسی نشد؛ schema نامشخص |
| GET | `/easy/api/StockCondition/riskAgreement` | 204 | بدون query/body | بدون body قابل مشاهده |

`/easy/api/money` شواهد شبکه‌ای مستقیم برای فیلدهای قدرت خرید/مانده است. endpoint کد-محور `/orders/api/order/money/order-entry?symbolIsin=...` در این بارگذاری شبکه دیده نشد؛ فقط در JavaScript وجود دارد.

## نمادها و بازار

| Method | Path | Status | Request schema | Response schema پاک‌سازی‌شده |
|---|---|---:|---|---|
| GET | `/symbols/api/TradingTime` | 200 | بدون query/body | `{items: array<{title: array<string>, days: array<number>, tradingTimeType:number, startPreTradingTime:string, endPreTradingTime:string, startTradingTime:string, endTradingTime:string, startTalTime:string, endTalTime:string}>}` |
| GET | `/symbols/api/MarketData/tse-index` | 200 | بدون query/body | `array<{dayOfEvent:string, indexChanges:number, lastIndexValue:number, percentVariation:number, symbolIsin:string, symbolTitle:string}>` |
| GET | `/symbols/api/symbols/manners` | 200 | بدون query/body | بدنه در DevTools به JSON schema قابل parse تبدیل نشد؛ نام فیلدها نامشخص |
| GET | `/easy/api/market-live/industries/positive-negative-symbols` | 200 | بدون query/body | `array<{industryCode:string, industryName:string, negativeCount:number, zeroCount:number, positiveCount:number}>` |
| GET | `/easy/api/symbol-analysis/technical-analysis?isin={}` | 200 (۲ مشاهده) | query `isin`; مقدار حذف شد | `{totalScore:{cat:string, value:number, state:string}, categoryScore:array<{cat:string, catFa:string, state:string}>}` |
| GET | `/easy/api/symbol-analysis/ind-inst?isin={}` | 200 (۵ مشاهده) | query `isin`; مقدار حذف شد | آرایه‌ای از فیلدهای عددی تحلیل خرید/فروش حقیقی/حقوقی، از جمله `indBuyVol`, `indBuyPow`, `indSellVol`, `insSellVol`, `insBuyVol`, `bidPres`, `netInd`, `buyPerInd`, `sellPerInd`, `diffValInd` |
| GET | `/easy/api/symbol-analysis/ind-trading-trend?isin={}` | 200 (۵ مشاهده) | query `isin`; مقدار حذف شد | `array<{type:string, date:string, val:number}>` |
| GET | `/chart/api/v2/datafeed/miniChart/history?days={}&symbol={}` | 200 | query names `days`, `symbol`; valueها حذف شد | `{data:array<unknown>, s:string}` |
| GET | `/ms/api/MarketSheet/sum/{symbolIsin}` | 200 | path param `symbolIsin`; مقدار واقعی حذف شد | `{buyVolume:number, buyCount:number, sellVolume:number, sellCount:number}` |
| GET | `/easy/api/MarketWatch` | 200 | بدون query/body | آرایهٔ category؛ `id:string`, `isDefault:boolean`, `order:number`, `name:string` (مقدار حذف‌شده), `createDateTime:string`, `watchCategorySymbols:array<{symbolIsin:string}>` |

## فهرست سفارش و وضعیت

| Method | Path | Status | Request schema | Response schema پاک‌سازی‌شده |
|---|---|---:|---|---|
| GET | `/core/api/order` | 200 (۲ مشاهده) | بدون query/body | `{orders:array<unknown>, algoSuffixCharacters:string}`؛ schema عنصر سفارش در پاسخ قابل تأیید نبود |
| GET | `/algo/api/order/active` | 200 | بدون query/body | `{orderItemDto:array<unknown>, totalCount:number}`؛ schema عنصر سفارش نامشخص |
| GET | `/unrequested-orders/api/order/hasPending` | 200 | بدون query/body | `{hasPending:boolean}`؛ مقدار boolean گزارش نشده |
| GET | `/easy/api/draft` | 200 | بدون query/body | آرایه؛ فیلدهای draft بررسی نشدند تا دادهٔ کاربر استخراج نشود |

در لاگ این نشست، `GET /unrequested-orders/api/order/pending` و `GET /unrequested-orders/api/order/oms-status` دیده نشدند. بدنه‌های احتمالی سفارش خام یا وضعیت واقعی سفارش در این گزارش استخراج نشده‌اند.

## سایر GETهای برنامه که schema آن‌ها بررسی نشد

این مسیرها با status موفق در لاگ بودند؛ response body بررسی نشد چون برای هدف فعلی لازم نبود یا ممکن بود محتوای حساب/متن شخصی داشته باشد:

| Method | Path | Status |
|---|---|---:|
| GET | `/contract/api/Agreements` | 200 |
| GET | `/contract/api/contract` | 200 |
| GET | `/easy/api/clientAppSetting` | 200 |
| GET | `/easy/api/Notes` | 200 |
| GET | `/easy/api/Layout` | 200 |
| GET | `/ipo/api/ipo` | 200 |
| GET | `/notification/api/v1/inapp-message/nsc` | 200 |
| GET | `/notification/api/v1/inapp-message/instant` | 200 |
| GET | `/notification/api/v2/inapp-message/mofid` | 200 |
| GET | `/user-engagement/api/v3/feedback/active-tags` | 200 |
| GET | `/user-engagement/api/v3/Voc/features` | 200 |
| GET | `/user-engagement/api/v3/UserSegment/segment-name` | 200 |

## ثبت سفارش در برابر پذیرش نهایی

در مرحلهٔ GET-only قبلی، هیچ درخواست ثبت سفارش مشاهده نشد. در مرحلهٔ مشاهدهٔ دستی که در ادامه ثبت شده، یک POST از اقدام خود کاربر و پاسخ اولیهٔ آن دیده شد. پذیرش نهایی OMS/بورس، رد سفارش و انجام جزئی همچنان از شواهد شبکه قابل نتیجه‌گیری نیست.

- **Network:** `GET /core/api/order`, `GET /algo/api/order/active` و `GET /unrequested-orders/api/order/hasPending` با `200` مشاهده شدند؛ schema ردیف سفارش/وضعیت کافی برای تعیین پذیرش نهایی یا fill نداشت.
- **Code only:** bundle عمومی مسیر `POST /core/api/v2/order` را نشان می‌دهد و status خطای `429` را در client مدیریت می‌کند. همچنین کد endpointهای `order/pending` و `order/oms-status` را ترکیب و فیلدهای `ordersStatus[].orderId` و `orderState` را برای map کردن وضعیت به `omsOrderId` مصرف می‌کند. این مسیرها در شبکهٔ این نشست دیده نشدند.
- **نامشخص:** ارتباط پاسخ اولیه با نتیجهٔ OMS/بورس، پیام پذیرش/رد بورس، وضعیت partial fill و transport پیام‌های بعدی. پاسخ اولیه و شناسهٔ آن در بخش مشاهدهٔ دستی زیر ثبت شده‌اند؛ مقدار شناسه حذف شده است.

کد static به stream adapter با topic `order` نیز اشاره دارد، اما پیام stream و نگاشت وضعیت‌ها در شبکه تأیید نشدند.

## آزمایش مستقل چرخهٔ سفارش — طراحی شد، اجرا نشد

1. ابتدا فقط محیط رسمی sandbox/test کارگزاری و نبود مسیردهی به بازار واقعی تأیید شود. اگر محیط غیرتولیدی قابل اثبات نیست، آزمایش متوقف بماند.
2. پس از اجازهٔ صریح کاربر برای همان اجرای مستقل، یک سفارش آزمایشی فقط در sandbox از رابط کاربری خود EasyTrader ایجاد شود؛ هیچ cURL، بازپخش یا درخواست دستی API استفاده نشود.
3. فقط status و schema پاک‌سازی‌شدهٔ پاسخ اولیه ثبت شود؛ هیچ مقدار شناسه، حساب یا قیمت گزارش نشود.
4. سپس فقط GETهای عادی UI و streamهای خواندنی تا وضعیت نهایی ثبت شوند تا تفاوت acknowledgment اولیه با پذیرش/رد/partial fill مشخص شود.
5. اگر sandbox امکان partial fill را ندارد، آن بخش نامشخص می‌ماند؛ سفارش واقعی یا لغو واقعی برای تکمیل سناریو مجاز نیست.

**برای اجرای این آزمایش هنوز اجازهٔ جداگانه لازم است.** هیچ مرحله‌ای از آزمایش در این بررسی اجرا نشد.

## مشاهدهٔ سفارش دستی کاربر — شواهد شبکه

کاربر اعلام کرد سفارش را شخصاً از رابط EasyTrader ارسال کرده است. نقطهٔ شروع این مشاهده پس از درخواست شمارهٔ 522 در لاگ بود. درخواست‌های پس از آن فقط از لاگ موجود بررسی شدند؛ هیچ درخواست شبکه‌ای ایجاد یا بازپخش نشد.

### جدول زمانی

| ترتیب | رویداد | شواهد | نتیجه |
|---:|---|---|---|
| 1 | کاربر ثبت دستی سفارش را اعلام کرد | پیام کاربر؛ خودِ کلیک UI در این بررسی ثبت تصویری نشد | زمان دقیق محلی در لاگ موجود نیست |
| 2 | ارسال درخواست ثبت سفارش | `POST /core/api/v2/order`؛ HTTP `200`؛ `Content-Type: application/json`؛ بدنهٔ درخواست JSON | درخواست با پاسخ HTTP موفق برگشت؛ هیچ مقدار سفارش/شناسه‌ای ثبت نمی‌شود |
| 3 | پاسخ اولیهٔ API | `Content-Type: application/json; charset=utf-8`؛ schema پاسخ: `isSuccessful:boolean`, `id:string` (مقدار حذف‌شده), `message:string`, `omsError:null` در نمونهٔ مشاهده‌شده | پاسخ اولیهٔ backend ثبت شد؛ این به‌تنهایی پذیرش نهایی بورس را اثبات نمی‌کند |
| 4 | درخواست‌های بعدی در لاگ قابل مشاهده | پس از POST، چند بار منابع frontend و GETهای زمان سرور/تحلیل نماد دیده شدند | مسیر status یا stream دارای وضعیت متناظر با سفارش در بازهٔ بررسی‌شده مشاهده نشد |

ترتیب بالا از ترتیب درخواست‌ها در لاگ DevTools به دست آمده است؛ timestamp دقیق و مستقل برای هر مرحله در خروجی در دسترس نبود. شناسهٔ درخواست پاسخ فقط برای تحلیل داخلی استفاده شد و در سند به‌صورت مقدار ساختگی/حذف‌شده آمده است.

### Schema پاک‌سازی‌شدهٔ درخواست و پاسخ اولیه

| بخش | فیلدها و نوع دادهٔ مشاهده‌شده |
|---|---|
| Request body | `{order: {price:number, quantity:number, side:number, validityType:number, createDateTime:string, commission:number, symbolIsin:string, symbolName:string, orderModelType:number, totalValue:number, orderFrom:number}}` |
| Response body | `{isSuccessful:boolean, id:string, message:string, omsError:null}`؛ مقدارها حذف شده‌اند و این نمونه schema رسمی API محسوب نمی‌شود |

`200` و وجود فیلد `isSuccessful` فقط پاسخ HTTP و schema پاسخ اولیه را نشان می‌دهند. بدون مشاهدهٔ یک status/event بعدی، نمی‌توان نتیجه گرفت سفارش در بورس پذیرفته، رد یا اجرا شده است. پاسخ اولیهٔ backend و پاسخ/رویداد نهایی بورس در این شواهد به هم متصل نشده‌اند.

### وضعیت‌های بعدی و اصلاح/لغو

در بازهٔ لاگ بررسی‌شده، پس از ثبت دستی، درخواست وضعیت سفارش یا رویداد قابل انتساب به همان شناسه در دسترس نبود. وضعیت‌های پذیرش، رد، انجام جزئی و انجام کامل **مشاهده نشدند** و منبع وضعیت بورس نیز **نامشخص** است. درخواست طبیعی اصلاح یا لغو از سوی کاربر هم در این بازه مشاهده نشد.

| وضعیت | مشاهده شد؟ | منبع قابل اثبات |
|---|---|---|
| پاسخ اولیهٔ API | بله؛ HTTP 200 و schema بالا | backend API؛ شواهدی از پاسخ نهایی بورس نیست |
| پذیرش نهایی سفارش | خیر | نامشخص |
| رد سفارش | خیر | نامشخص |
| انجام جزئی | خیر | نامشخص |
| انجام کامل | خیر | نامشخص |
| اصلاح یا لغو دستی | خیر | نامشخص |

این بخش شواهد Network است. مسیرهای سفارش در `orders.md` که فقط از bundle استخراج شده‌اند، همچنان به‌عنوان شواهد JavaScript جداگانه علامت‌گذاری شده‌اند.

### نتیجهٔ عملیاتی همان پاسخ — بررسی تکمیلی

پاسخ همان `POST` از سابقهٔ موجود دوباره خوانده شد؛ درخواست تازه‌ای ارسال نشد. نتیجهٔ پاک‌سازی‌شده:

| لایه | مشاهده | تفسیر محدود به شواهد |
|---|---|---|
| پاسخ HTTP | status `200`؛ پاسخ JSON | درخواست به endpoint رسید و پاسخ HTTP دریافت شد؛ HTTP 200 به‌تنهایی موفقیت ثبت سفارش نیست |
| نتیجهٔ عملیات backend | `isSuccessful:false`؛ `omsError:null`؛ `message:string` و متن آن با خطای «محدوده زمانی سفارش معتبر نمی‌باشد» منطبق بود | backend برای عملیات نتیجهٔ ناموفق اعلام کرده؛ در این نمونه خطای OMS جداگانه‌ای در `omsError` گزارش نشده است |
| شناسهٔ پاسخ | کلید `id` وجود داشت، نوع `string` و مقدار خالی بود | این پاسخ شناسهٔ سفارش یا شناسهٔ درخواستِ قابل استفاده ارائه نمی‌کند؛ معنای شناسهٔ عمومی `id` را نمی‌توان از مقدار خالی تعیین کرد |
| پذیرش سفارش در بورس | هیچ status یا پیام بورس در لاگ مرتبط مشاهده نشد | شواهدی از ثبت نهایی در سامانهٔ سفارش یا پذیرش بورس نداریم؛ پاسخ backend بر رد اعتبار زمانی دلالت می‌کند، اما پاسخ مستقل بورس در دسترس نیست |

بنابراین باید بین «پاسخ HTTP موفق» و «عملیات سفارش ناموفق» تفکیک کرد: HTTP 200 فقط انتقال پاسخ را تأیید می‌کند، در حالی که `isSuccessful:false` و پیام محدودیت زمانی نشان می‌دهند backend عملیات را موفق ندانسته است. با `id` خالی، این پاسخ شاهدی بر ایجاد شناسهٔ سفارش نیست. هیچ رویداد بعدی برای پذیرش، رد رسمی بورس یا اجرا مشاهده نشده؛ نتیجهٔ بورس **نامشخص/تأییدنشده** باقی می‌ماند.

## آیا سفارش ناموفق در فهرست سفارش‌ها دیده می‌شود؟

در لاگ موجود، GETهای موفق `/core/api/order` و `/algo/api/order/active` پیش از POST ناموفق ثبت شده‌اند؛ پس پاسخ‌های قبلی نمی‌توانند نشان دهند آن سفارش بعداً در فهرست ظاهر شده یا نه. پس از POST ناموفق، GET تازه‌ای از فهرست سفارش‌ها در سابقهٔ بررسی‌شده دیده نشد. بنابراین حضور یا عدم حضور سفارش ناموفق **نامشخص** است.

همچنین schema شبکه‌ای فهرست `/core/api/order` فقط `{orders: array<unknown>, algoSuffixCharacters:string}` بود و schema هر ردیف سفارش قابل تأیید نشد. از شواهد فعلی نمی‌توان گفت آیا این فهرست سفارش‌های ردشده را هم شامل می‌کند یا وضعیت rejection را نمایش می‌دهد؛ این مورد **تأییدنشده** است.

### مسیرهای جداگانهٔ وضعیت

- **Network:** `GET /algo/api/order/active` و `GET /unrequested-orders/api/order/hasPending` با HTTP 200 دیده شدند، اما ردیف وضعیت سفارش و ارتباط با POST ناموفق مشخص نشد.
- **JavaScript فقط:** مسیرهای `GET /unrequested-orders/api/order/pending` و `GET /unrequested-orders/api/order/oms-status` در bundle شناسایی شده‌اند. کد از `ordersStatus[].orderId` و `orderState` برای اتصال/نگاشت وضعیت استفاده می‌کند. این دو مسیر پس از POST ناموفق در Network تأیید نشدند.

در بررسی دوبارهٔ لاگ غیرفعال، یک POST دیگر به همان مسیر ثبت سفارش با HTTP 200 نیز در ورودی‌های جدیدتر دیده شد. بدنه، پاسخ و ارتباط آن با سفارش قبلی بررسی نشده و در این نتیجه‌گیری استفاده نمی‌شود؛ بنابراین نتیجهٔ بالا فقط دربارهٔ پاسخ ناموفق بررسی‌شده است.

## بررسی طبیعی فرم خرید و ارسال سفارش — 2026-11-13

این بخش فقط درخواست‌های موجود در Network همان نشست را ثبت می‌کند. مقدارهای واقعی سفارش، نماد، حساب و احراز هویت حذف شده‌اند. زمان‌بندی بر اساس ترتیب درخواست‌های Network است؛ timestamp دقیق مراحل UI در این لاگ خلاصه‌شده قابل بازیابی نیست.

### پاسخ ثبت سفارش

| Method | Path | Status | Content-Type پاسخ | Schema پاک‌سازی‌شده | نتیجه |
|---|---|---:|---|---|---|
| POST | `/core/api/v2/order` | 200 | `application/json; charset=utf-8` | `{isSuccessful:boolean, id:string, message:string, omsError:null}` | `isSuccessful:false`؛ پاسخ HTTP 200 است اما عملیات ناموفق گزارش شده. `id` در نمونه خالی بود؛ مقدار ثبت نشده است. |

پاسخ به خطای محدودیت زمانی سفارش اشاره می‌کند. هیچ درخواست/رویداد بعدی قابل انتساب به همان سفارش برای تعیین وضعیت OMS/بورس در شواهد بررسی‌شده نبود؛ پذیرش یا ایجاد سفارش در بازار نامشخص است.

### ظرفیت خرید در جریان فرم

در لاگ موجود، پس از جست‌وجو و بارگذاری داده‌های نماد و پیش از `POST /core/api/v2/order`، درخواست `GET /orders/api/order/money/order-entry` مشاهده نشد. بنابراین Method/Path/Query و schema شبکه‌ای endpoint ظرفیت برای این جریان تأیید نشدند. پاسخ‌های endpointهای عمومی نماد/بازار در همین بازه به‌تنهایی به‌عنوان ظرفیت خرید تعبیر نمی‌شوند.

## تطبیق منابع پایهٔ ظرفیت — فقط شواهد ثبت‌شده

این جمع‌بندی با captureهای موجود و بررسی JavaScript محلی تطبیق داده شده؛ درخواست تازه‌ای ایجاد نشده و body خام بازبینی/ذخیره نشده است.

| منبع | Network موجود | فیلدهای لازم و نوع | سطح تأیید |
|---|---|---|---|
| Snapshot پول: `GET /easy/api/money` | HTTP 200 مشاهده‌شده | `buyPowerT2:number`؛ schema کامل پاک‌سازی‌شده در جدول حساب بالا | Network-confirmed برای REST؛ انتشار رویداد store فقط JavaScript |
| به‌روزرسانی پول: Lightstreamer topic `money` | فقط handshakeهای نشست با HTTP 200؛ پیام topic/schema ثبت نشده | کد، map numeric شامل `buyPowerT2`; payload Network نامشخص | JavaScript code-only برای mapping؛ Network نامشخص برای payload |
| آیتم‌های پرتفوی: `GET /assetmodule/api/performance` | HTTP 200 مشاهده‌شده | `{items: array<object>}`؛ نمونه دارای `symbolIsin:string`, `asset:number` | Network-confirmed برای نمونهٔ REST؛ store/form dataflow JavaScript |
| حدود volume: `POST /symbols/api/marketdata/v2` یا stream symbol | در capture ثبت‌شده POST دیده نشد؛ stream فقط handshake شناخته‌شده است | کد form نیازمند چهار `*Valid*Volume:number`؛ schema Network آن‌ها موجود نیست | Unknown برای منبع Network؛ JavaScript code-only برای نیاز و mapper |

`buyPowerT2` از schema پاک‌سازی‌شده است؛ هیچ مقدار مالی یا شناسه‌ای در این به‌روزرسانی درج نشده است.
