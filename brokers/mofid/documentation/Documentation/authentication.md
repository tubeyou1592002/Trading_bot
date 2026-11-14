# احراز هویت و مدیریت نشست EasyTrader

## نتیجهٔ پیاده‌سازی در Trading_bot (2026-11-14)

کاربر ورود مفید را در worktree برنامه به‌صورت دستی آزمایش کرد و تأیید کرد حساب وارد شد و قدرت خرید نمایش داده شد. این نتیجه فقط ورود و خواندن قدرت خرید را پوشش می‌دهد؛ تست سفارش یا اجرای زنده انجام نشده است.

توالی طبیعی ثبت‌شده در Chrome پس از ورود: `POST /easy/api/account/same-login` (200) ← `GET /easy/api/startsession` (200) ← `GET /easy/api/money` (200). پاسخ money دارای `buyPowerT2:number` بود و برنامه همین فیلد را نمایش داد. هیچ مقدار مالی، توکن، Cookie یا header محرمانه‌ای در این سند درج نمی‌شود.

درخواست `same-login` از JSON با `uuid` و شیء `userDeviceInfo` استفاده می‌کند. فیلدهای مشاهده‌شدهٔ شیء عبارت‌اند از `appBuildNo`, `width`, `height`, `devicePlatform`, `platformInfo`. سورس EasyTrader نشان می‌دهد UUID در localStorage با کلید `uuid` پایدار می‌شود، build از `meta[name=app-build]`/`environment.build` می‌آید، ابعاد از اندازهٔ پنجره و `platformInfo` از User-Agent می‌آید؛ `devicePlatform` در وب دسکتاپ `Desktop` بود. مقدار build مشاهده‌شده `59762` است و ممکن است با نسخه‌های بعدی تغییر کند.

کاربر همچنین رد شدن ورود با اعتبارنامهٔ اشتباه را آزمایش کرد. برنامه به‌روزرسانی شد تا پاسخ فرم ورود ردشده پیام فارسی مشخص «نام کاربری یا رمز عبور اشتباه است، یا ورود توسط کارگزاری رد شد» بدهد. خطای شبکه و پاسخ ناشناخته همچنان پیام عمومی دارند.

تاریخ بازبینی: 2026-11-13

## جمع‌بندی شواهد قبلی و کمبودها

قبلاً OIDC metadata (`GET /.well-known/openid-configuration`, HTTP 200)، آغاز authorization (`GET /connect/authorize`, HTTP 303)، پیاده‌سازی `signinRedirect()` و endpointهای نشست برنامه مستند شده بود. در سابقهٔ Network تاریخی این نشست، `POST /connect/token` با HTTP 200 و پس از آن `POST /easy/api/account/same-login` با HTTP 200 نیز ثبت شده بود. کاربر ورود را دستی انجام داده بود. هیچ body یا header احراز هویت بازبینی یا ذخیره نشده است.

در اتصال قبلی DevTools، لاگ‌های تاریخی از دسترس خارج شده بودند. پس از آن کاربر در صفحهٔ ایزوله ورود دستی را انجام داد و capture طبیعی جدید در بخش «ثبت جدید پس از ورود دستی» اضافه شده است. در همان capture نیز bodyهای محرمانه و مقدار headerها بررسی/ثبت نشده‌اند.

## نقشهٔ مرحله‌به‌مرحله

| گام | جریان | وضعیت شواهد |
|---:|---|---|
| 1 | صفحهٔ EasyTrader ورود OIDC را با `signinRedirect()` شروع می‌کند. | کد JavaScript قطعی؛ Network جزئیات شروع در سابقهٔ تاریخی ناقص |
| 2 | کلاینت metadata را از `GET https://login.emofid.com/.well-known/openid-configuration` دریافت می‌کند؛ HTTP 200 ثبت شده است. | Network تاریخی تأییدشده؛ بدنه بررسی نشده |
| 3 | مرورگر به `GET https://login.emofid.com/connect/authorize` می‌رود؛ HTTP 303 به `/Login` ثبت شد. | Network تأییدشده؛ نام queryها ثبت و مقدارها حذف شدند |
| 4 | کاربر اطلاعات ورود را دستی در صفحهٔ ارائه‌دهنده وارد می‌کند. | کاربر ورود دستی موفق را قبلاً اعلام کرده؛ درخواست فرم و پاسخ آن در شواهد قابل دسترسی فعلی نیست |
| 5 | `POST https://login.emofid.com/connect/token` با HTTP 200 در سابقهٔ Network ثبت شده است. | Network تاریخی تأییدشده فقط برای Method/Path/Status؛ body و response schema عمداً بررسی نشده |
| 6 | برنامه callback را با `signinRedirectCallback(window.location.href)` پردازش می‌کند؛ Network نشان داد `GET d.easytrader.ir/auth-callback` با 200 بارگذاری شد. | پیاده‌سازی JavaScript و مسیر callback در Network تأیید شدند؛ مقدارهای query حذف شده‌اند |
| 7 | مرورگر به `https://d.easytrader.ir/auth-callback` با HTTP 200 بازگشت؛ سپس صفحهٔ برنامه در مسیر اصلی دیده شد. | مسیر callback و بازگشت تأییدشده؛ query values حذف شده‌اند |
| 8 | برنامه `GET /easy/api/startsession` را برای آغاز نشست برنامه اجرا می‌کند؛ در Network با HTTP 200 دیده شد. نمونهٔ پاسخ فقط نام فیلدهای `serverTime:string` و `startSessionTimeStamp:string` را داشت. | Network تأییدشده؛ مقادیر حذف‌شده |
| 9 | برنامه `POST /easy/api/account/same-login` را انجام می‌دهد؛ HTTP 200. | Network request schema شامل `uuid`, `appBuildNo`, اندازهٔ viewport و اطلاعات پلتفرم است؛ مقادیر حذف شده‌اند |

ترتیب بالا از سابقهٔ تاریخی و کد کنار هم بازسازی شده است؛ timestamp کامل مراحل و درخواست‌های فرم ورود قابل بازیابی نیستند. دامنهٔ احراز هویت مشاهده‌شده `login.emofid.com` و دامنهٔ API نشست `api-mts.orbis.easytrader.ir` است. دامنهٔ `d.easytrader.ir` میزبان برنامه است.

## APIهای احراز هویت و نشست — شواهد Network

| Method | Host و Path | Status مشاهده‌شده | Schema یا محدودیت | وضعیت |
|---|---|---:|---|---|
| GET | `login.emofid.com/.well-known/openid-configuration` | 200 | metadata و response body در این بررسی parse نشده | تأییدشده در سابقهٔ تاریخی |
| GET | `login.emofid.com/connect/authorize` | 303 | query names و redirect به `/Login` در capture جدید ثبت شدند؛ query values حذف شده‌اند | تأییدشده |
| POST | `login.emofid.com/connect/token` | 200 | Content-Type و schema پاک‌سازی‌شده در بخش capture جدید ثبت شده؛ مقادیر token بررسی/ثبت نشده‌اند | تأییدشده؛ schema نمونه موجود |
| GET | `api-mts.orbis.easytrader.ir/easy/api/startsession` | 200 | response: `{serverTime:string, startSessionTimeStamp:string}` | تأییدشده |
| POST | `api-mts.orbis.easytrader.ir/easy/api/account/same-login` | 200 | schema request در capture جدید ثبت شده؛ response body بررسی نشده | تأییدشده؛ response ناقص |
| POST | `api-mts.orbis.easytrader.ir/easy/api/account/logout` | 200 | بدنه و Content-Type در مستند ثبت نشده | Network تأییدشده؛ schema ناقص |

در capture جدید، درخواست‌های ورود و خروج ثبت شدند. statusهای 401/403 و درخواست refresh مشاهده نشدند.

## نگهداری نشست و تمدید اعتبار — شواهد JavaScript

- کتابخانهٔ OIDC در `main-JXOX7C46.js` از `signinRedirect()` و `signinRedirectCallback()` استفاده می‌کند. پیاده‌سازی کتابخانه از PKCE پشتیبانی می‌کند؛ وجود پارامترهای PKCE در درخواست واقعی این نشست اکنون قابل بازبینی نیست.
- پیاده‌سازی کتابخانه، state store را به طور پیش‌فرض روی `localStorage` قرار می‌دهد؛ امکان تنظیم store دیگر وجود دارد.
- سازندهٔ UserManager در bundle، `userStore` را با توجه به `storeMode` انتخاب می‌کند: `localStorage` اگر مقدار mode برابر 0 باشد، در غیر این صورت `sessionStorage`. مقدار runtime خود تنظیم مشخص نیست؛ اما در capture زنده، وجود ورودی OIDC user در `sessionStorage` و نبود آن در `localStorage` به‌صورت Boolean تأیید شد. هیچ مقدار یا نام کلید واقعی خوانده/گزارش نشد.
- کلید `redirect-after-login` در کد در `localStorage` و `sessionStorage` نوشته و پس از بازگشت خوانده/حذف می‌شود. مقدار آن در این سند نیامده است.
- کتابخانهٔ OIDC قابلیت تمدید بی‌صدا و مصرف refresh grant را دارد. با این حال، تنظیم UserManager دیده‌شده در bundle مقدار `automaticSilentRenew:false` دارد؛ فعال بودن تمدید خودکار برای نمونهٔ runtime تأیید نشده است. عمر نشست، زمان انقضا، refresh واقعی و پاسخ‌های تمدید در Network **نامشخص** هستند.
- کد مسیر `POST /easy/api/account/logout` و `signoutRedirect()` را دارد؛ POST و redirectهای خروج در Network مشاهده شدند. `removeUser()` در کد پس از شروع خروج فراخوانی می‌شود؛ پاک‌شدن storage برنامه پس از خروج در runtime تأیید نشد.

## رفتار 401 و 403 — شواهد JavaScript

Interceptor در bundle پاسخ‌های 401 و 403 را می‌شمارد و در صورت برقرار بودن شرط‌های نقش کاربر، پس از آستانهٔ کد (دو پاسخ برای کاربر غیرمهمان؛ 30 برای مهمان) `logOutFromApp()` را فراخوانی می‌کند. شرط‌های داخلی و بعضی مسیرها استثنا دارند؛ این توصیف رفتار کد است، نه نتیجهٔ آزمایش شبکه. در capture طبیعی جدید، پاسخ 401 یا 403 مشاهده نشد؛ رفتار runtime این کد همچنان از Network تأیید نشده است.

## تفکیک و وضعیت کلی

- **Network تأییدشده در capture ورود/خروج:** metadata، authorize، فرم ورود، callback، token exchange، دو مسیر نشست برنامه و درخواست‌های logout با statusهای جدول.
- **JavaScript قطعی:** شروع/تکمیل redirect، انتخاب storage، قابلیت renew، logout و شاخه‌های 401/403.
- **ناقص یا نامشخص:** مقدارهای واقعی پارامترهای authorize/callback (عمداً حذف شده‌اند)، مقدار runtime `storeMode`, refresh/expiry واقعی، body پاسخ logout، پاک‌شدن runtime storage پس از خروج و رفتار واقعی در 401/403.
- **حفظ حریم خصوصی:** هیچ رمز، OTP، Cookie، Authorization، JWT، access/refresh token، مقدار storage یا شناسهٔ کاربر در این سند ثبت نشده است.

کاربر ورود دستی و سپس خروج را برای capture جدید انجام داده است. مواردی که مشاهده نشدند، از جمله تمدید نشست و پاک‌شدن storage برنامه پس از خروج، همچنان نامشخص‌اند و فقط در صورت وقوع طبیعی قابل ثبت خواهند بود.

## ثبت جدید پس از ورود دستی — شواهد Network

کاربر ورود دستی موفق را اعلام کرد. صفحهٔ `d.easytrader.ir` در مرورگر ایزولهٔ `easytrader-auth-preparation` مشاهده شد. درخواست‌های زیر فقط از سابقهٔ طبیعی مرورگر خوانده شدند؛ هیچ درخواست احراز هویت ایجاد یا بازپخش نشد. تمام مقدارهای فرم، query، header و بدنه حذف شدند.

### نقشهٔ واقعی redirect و callback

| ترتیب | Method و Path | Status | Content-Type / Schema پاک‌سازی‌شده | نتیجه |
|---:|---|---:|---|---|
| 1 | `GET login.emofid.com/.well-known/openid-configuration` | 200 | بدنه بررسی نشد | metadata ارائه‌دهنده دریافت شد |
| 2 | `GET login.emofid.com/connect/authorize` | 303 | query names: `client_id`, `redirect_uri`, `response_type`, `scope`, `state`, `code_challenge` | redirect به `login.emofid.com/Login`; فقط نام `ReturnUrl` ثبت شد |
| 3 | `GET login.emofid.com/Login` | 200 | `text/html` | صفحهٔ فرم ورود بارگذاری شد |
| 4 | `POST login.emofid.com/Login` | 302 | Request `application/x-www-form-urlencoded`; فیلدها: `Username:string`, `Password:string`, `__RequestVerificationToken:string` | پاسخ به `/connect/authorize/callback` هدایت کرد؛ query names شامل پارامترهای authorize و `code_challenge_method` بود |
| 5 | `GET login.emofid.com/connect/authorize/callback` | 303 | redirect به `https://d.easytrader.ir/auth-callback`; query names: `code`, `state`, `session_state`, `iss` | مسیر بازگشت به برنامه تأیید شد؛ مقادیر query حذف شدند |
| 6 | `GET d.easytrader.ir/auth-callback` | 200 | `text/html` | صفحهٔ callback برنامه بارگذاری شد |
| 7 | `POST login.emofid.com/connect/token` | 200 | Request `application/x-www-form-urlencoded`; فیلدها: `grant_type:string`, `redirect_uri:string`, `code:string`, `code_verifier:string`, `client_id:string`; Response `application/json` | token exchange با پاسخ موفق HTTP تأیید شد؛ هیچ مقدار token استخراج یا ذخیره نشد |
| 8 | `POST api-mts.orbis.easytrader.ir/easy/api/account/same-login` | 200 | Request `application/json`; schema: `{uuid:string, appBuildNo:string, width:number, height:number, devicePlatform:string, platformInfo:string}` | درخواست بررسی نشست برنامه؛ response body بررسی نشد |
| 9 | `GET api-mts.orbis.easytrader.ir/easy/api/startsession` | 200 | Request و Response `application/json`; response `{serverTime:string, startSessionTimeStamp:string}` | آغاز نشست برنامه تأیید شد |
| 10 | `POST ls.easytrader.ir/lightstreamer/create_session.txt` و `POST ls-marketsheet.easytrader.ir/lightstreamer/create_session.txt` | 200 | query name `LS_protocol`; body و response بررسی نشد | دو نشست stream برنامه ایجاد شدند؛ جزئیات session حذف/بررسی‌نشده |

پاسخ token exchange در نمونهٔ مشاهده‌شده دارای schema زیر بود: `{id_token:string, access_token:string, expires_in:number, token_type:string, scope:string}`. هیچ مقدار یا header محرمانه ثبت نشده است. فیلد `refresh_token` در schema این پاسخ مشاهده نشد؛ این موضوع به‌تنهایی نبود refresh در سایر جریان‌ها را ثابت نمی‌کند.

### محل نشست در runtime

در صفحهٔ پس از ورود، فقط وجود/عدم وجود دسته‌های کلید بررسی شد و هیچ نام کلید واقعی یا مقداری خوانده/گزارش نشد. در لحظهٔ بررسی، ورودی OIDC user در `sessionStorage` وجود داشت و ورودی هم‌نوع در `localStorage` دیده نشد. دادهٔ redirect-after-login در هیچ‌یک از این دو محل در زمان بررسی موجود نبود. این مشاهده runtime است و به همین نشست محدود می‌شود.

### تمدید، انقضا، خروج و خطای احراز هویت

- پس از ورود، درخواست refresh جداگانه یا token exchange دیگری در لاگ بررسی‌شده دیده نشد؛ تمدید طبیعی هنوز مشاهده نشده است.
- خروج دستی کاربر در capture جدید مشاهده شد؛ ترتیب و redirectها در بخش «خروج دستی کاربر — شواهد Network» ثبت شده‌اند. هیچ اقدام خروجی از سوی بررسی‌کننده انجام نشد.
- در درخواست‌های این جریان status `401` یا `403` مشاهده نشد.
- رفتار renew/logout و شاخه‌های 401/403 که قبلاً در بخش شواهد JavaScript ثبت شده‌اند، از Network مستقل‌اند و نتیجهٔ رفتار runtime محسوب نمی‌شوند.

این ثبت، شواهد جدید Network را از شواهد JavaScript بخش‌های قبلی جدا نگه می‌دارد. مقدار password، CSRF token، code، state، session_state، Cookie، Authorization و tokenها در سند وجود ندارد.

## خروج دستی کاربر — شواهد Network

کاربر اعلام کرد از رابط EasyTrader خروج زده است. درخواست‌ها فقط از لاگ طبیعی مرورگر خوانده شدند؛ هیچ logout یا request دیگری از سوی بررسی‌کننده اجرا نشد و هیچ مقدار query/header/session ذخیره نشد.

| ترتیب | Method و Path | Status | نتیجهٔ پاک‌سازی‌شده |
|---:|---|---:|---|
| 1 | `POST api-mts.orbis.easytrader.ir/easy/api/account/logout` | 200 | درخواست خروج برنامه پاسخ HTTP موفق گرفت؛ body و Content-Type ثبت نشده‌اند |
| 2 | `GET login.emofid.com/connect/endsession` | 303 | query names: `id_token_hint`, `post_logout_redirect_uri`; پاسخ به `login.emofid.com/Logout` رفت و نام query `logoutId` بود؛ همهٔ مقدارها حذف شدند |
| 3 | `GET login.emofid.com/Logout` | 302 | redirect به `https://d.easytrader.ir/` |
| 4 | redirect بعدی برنامه | `GET login.emofid.com/.well-known/openid-configuration` با 200 و `GET login.emofid.com/connect/authorize` با 303 | برنامه ورود OIDC را دوباره آغاز کرد و به `/Login` هدایت شد؛ صفحهٔ نهایی مرورگر فرم ورود بود |

این توالی نشان می‌دهد endpoint خروج برنامه و مسیر end-session ارائه‌دهنده اجرا شدند و بعد از بازگشت، کاربر برای ورود دوباره به صفحهٔ ورود رسید. بنابراین خروج در سطح رابط/جریان OIDC مشاهده شده است. پاک‌شدن Cookie یا storage به‌صورت مستقیم بررسی نشد و هیچ Cookie یا مقدار نشست خوانده نشد. هیچ token exchange یا ورود مجددی پس از logout مشاهده نشد.

### محدودیت مشاهدهٔ storage پس از خروج

پس از redirect نهایی، صفحهٔ فعال روی دامنهٔ `login.emofid.com` بود. برای بررسی این‌که storage مختص origin برنامه پاک شده یا نه، به EasyTrader بازنگشتم و storage را دستکاری نکردم. بنابراین وضعیت storage برنامه پس از خروج **نامشخص** است. شواهد JavaScript قبلی، `signoutRedirect()` و `removeUser()` را نشان می‌دهد، اما پاک‌شدن عملی storage در این capture تأیید نشده است.
