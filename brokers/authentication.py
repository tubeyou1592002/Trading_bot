"""
brokers/authentication.py — Block 9, Task 4, Stage 2.

قرارداد عمومی احراز هویت، مستقل از بروکر.

هدف
---
یک لایه‌ی قراردادی واحد برای ورود به حساب کارگزاری که پیاده‌سازی هر
بروکر (آگاه، و غیره) پشت یک رابط مشترک قرار گیرد. لایه‌های بالاتر
(``ui.authentication_service.AuthenticationService`` و در نهایت رابط
کاربری) فقط با این قرارداد کار می‌کنند و هیچ جزئیات اختصاصی بروکر
(مثل ``captchaId`` آگاه، ساختار توکن یا endpointها) را نمی‌بینند.

مرز معماری (مستقل از بروکر بودن):

    LoginChallenge              چالش عمومیِ قابل‌نمایش (مثلاً تصویر کپچا)
        │
        ▼
    AuthenticationAdapter      پیاده‌سازی اختصاصی هر بروکر
        │   begin_login(username, password)  -> LoginChallenge
        │   complete_login(response)         -> AuthenticatedSession
        │   cancel_login()                   -> None
        │   is_authenticated()               -> bool
        │   get_authenticated_session()      -> AuthenticatedSession | None
        │   refresh_authenticated_session()  -> AuthenticatedSession
        ▼
    AuthenticatedSession       نتیجه‌ی موفق احراز هویت (توکن، شناسه کاربر)

قوانین قرارداد:

    * هیچ فیلد محرمانه‌ای (رمز عبور، توکن) در ``LoginChallenge`` قرار
      نمی‌گیرد؛ چالش فقط چیزی است که باید به کاربر نمایش داده شود.
    * ``AuthenticatedSession`` توکن را در خود نگه می‌دارد اما در
      ``repr`` / ``str`` و خروجی‌های عمومی هرگز آن را افشا نمی‌کند.
    * خطاهای احراز هویت هرگز رمز عبور یا توکن را در پیام، ``__cause__``
      یا ``__context__`` خود قرار نمی‌دهند.
    * ``complete_login`` فقط پس از دریافت پاسخ چالش و تأیید موفقیت
      واقعی API مجاز به برگرداندن ``AuthenticatedSession`` است؛ پاسخ
      ظاهراً موفق اما ناقص باید با ``IncompleteLoginError`` رد شود.
    * رفتار API ناشناخته حدس زده نمی‌شود؛ هر بروکر فقط همان رفتار
      تأییدشده‌ی واقعی خود را پیاده‌سازی می‌کند.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


class AuthenticationError(Exception):
    """
    پایه‌ی تمام خطاهای قرارداد احراز هویت.

    پیام این خطاها هرگز رمز عبور یا توکن را شامل نمی‌شود.
    """


class LoginNotInProgressError(AuthenticationError):
    """
    تکمیل یا لغو ورود بدون یک تلاش ورود در حال انجام، فراخوانی شده است.

    یا هیچ ``begin_login``‌ای انجام نشده، یا تلاش قبلاً تکمیل/لغو شده است.
    """


class LoginChallengeError(AuthenticationError):
    """
    دریافت چالش (مثلاً کپچا) از سمت بروکر ناموفق بود.

    هیچ پاسخی از کاربر نباید در انتظار بماند.
    """


class LoginRejectedError(AuthenticationError):
    """
    بروکر ورود را رد کرد: اعتبارنامه نادرست، کپچای اشتباه، حساب مسدود و
    مشابه آن.

    این یک خطای «قابل تکرار توسط کاربر» است: کاربر می‌تواند با چالش
    جدیدی دوباره تلاش کند.
    """


class IncompleteLoginError(AuthenticationError):
    """
    بروکر گزارش موفقیت داد اما نتیجه‌ی کامل احراز هویت را ارائه نکرد.

    برای آگاه: وجود توکن دسترسی معتبر و ``userIdentifier`` الزامی است.
    یک پاسخ ظاهراً موفق اما ناقص هرگز نباید حساب را به حالت واردشده
    ببرد؛ این خطا fail-closed است.
    """


class AuthenticationUnavailableError(AuthenticationError):
    """
    ارتباط با سرویس احراز هویت بروکر ممکن نشد (شبکه، قطعی سرویس،
    timeout یا پاسخ غیرقابل تفسیر).

    این یک خطای زیرساختی است، نه رد اعتبارنامه توسط بروکر.
    """


class TokenRefreshError(AuthenticationError):
    """
    نوسازی نشست احرازشدهٔ یک حساب ممکن نشد.

    دلایل ممکن: آداپتر از نوسازی توکن پشتیبانی نمی‌کند، حساب هنوز
    احراز هویت نشده است، یا درخواست نوسازی بروکر شکست خورد. پیام،
    ``__cause__`` و ``__context__`` این خطا هرگز توکن دسترسی یا توکن
    تازه‌سازی را افشا نمی‌کنند.

    سیاست نهاییِ invalidation پس از شکست نوسازی بخشی از Stage 2C است و
    در این مرحله تعریف نمی‌شود.
    """


def _raise_clean(error: Exception) -> None:
    """
    انتشار یک خطای پاک‌سازی‌شده بدون زنجیره‌ی استثنای محرمانه.

    صرف ``raise ... from None`` یا صفر کردن ``__context__`` پیش از
    ``raise`` کافی نیست: وقتی این تابع داخل یک بلوک ``except`` بیرونی
    صدا زده شود، خود مفسر در لحظه‌ی ``raise`` مقدار ``__context__`` را
    روی استثنای در حال هندل تنظیم می‌کند و محرمانه دوباره برمی‌گردد.

    راه‌حل: خطا داخل یک ``try/except`` داخلی بالا انداخته، گرفته و دوباره
    پاک‌سازی می‌شود و سپس با ``raise`` بدون آرگومان منتشر می‌گردد. در آن
    لحظه استثنای فعال همان خطای جاری است، پس مفسر ``__context__`` جدیدی
    روی آن نمی‌گذارد و مقدار ``None`` حفظ می‌شود.
    """
    error.__cause__ = None
    error.__context__ = None
    error.__suppress_context__ = True
    try:
        raise error
    except BaseException as exc:
        exc.__cause__ = None
        exc.__context__ = None
        exc.__suppress_context__ = True
        raise


@dataclass(frozen=True)
class LoginChallenge:
    """
    چالش عمومی و قابل‌نمایشِ یک تلاش ورود.

    فیلدها:

        kind            نوع چالش، مثلاً ``"captcha_image"``. ثابت‌های
                        ``CHALLENGE_*`` در همین ماژول.

        display_payload محتوای قابل نمایش به کاربر. برای کپچای تصویری،
                        داده‌ی Base64 تصویر است.

        prompt          راهنمای کوتاه فارسی برای نمایش کنار چالش.

    این شیء عمداً **هیچ** جزئیات اختصاصی بروکر (مانند ``captchaId`` آگاه)
    را حمل نمی‌کند. آن جزئیات فقط داخل آداپتر همان بروکر و همان حساب
    باقی می‌مانند و هرگز از مرز قرارداد عبور نمی‌کنند.
    """

    kind: str
    display_payload: str
    prompt: str


#: ثابت‌های نوع چالش شناخته‌شده (افزایش با افزودن بروکرها).
CHALLENGE_CAPTCHA_IMAGE = "captcha_image"


@dataclass(frozen=True)
class AuthenticatedSession:
    """
    نتیجه‌ی موفق و تأییدشده‌ی احراز هویت یک حساب.

    این شیء فقط پس از تأیید موفقیت واقعی API ساخته می‌شود و توکن‌ها را
    در خود دارد. توکن‌ها محرمانه‌اند و هرگز نباید در لاگ، پیام خطا،
    رابط کاربری یا ``repr`` نمایش داده شوند؛ به همین دلیل ``__repr__``
    و ``__str__`` این کلاس بازنویسی شده‌اند و فقط شناسه‌های غیرمحرمانه
    را نشان می‌دهند.
    """

    access_token: str
    user_identifier: str
    refresh_token: Optional[str] = None
    user_name: Optional[str] = None

    def __repr__(self) -> str:
        return (
            f"AuthenticatedSession("
            f"user_identifier={self.user_identifier!r}, "
            f"has_refresh_token={bool(self.refresh_token)}, "
            f"user_name={self.user_name!r})"
        )

    __str__ = __repr__


class AuthenticationAdapter(ABC):
    """
    رابط عمومی احراز هویت یک بروکر.

    هر پیاده‌سازی متعلق به **یک** حساب است: یک نمونه مستقل از بروکر،
    یک نشست HTTP مستقل و یک تلاش ورود واحد. دو حساب روی یک بروکر هرگز
    یک آداپتر (و در نتیجه یک نمونه بروکر) را به اشتراک نمی‌گذارند.

    چرخه‌ی یک تلاش ورود:

        begin_login(username, password)
            -> LoginChallenge            (چالش به کاربر نمایش داده می‌شود)

        complete_login(response)
            -> AuthenticatedSession      (فقط پس از تأیید موفقیت واقعی API)

        cancel_login()
            -> None                      (تلاش رها می‌شود، وضعیت پاک می‌شود)

    هر تلاش ورود یک‌بار است: پس از ``complete_login`` یا ``cancel_login``،
    آداپتر به حالت بدون تلاش فعال برمی‌گردد.
    """

    @property
    @abstractmethod
    def broker_name(self) -> str:
        """
        نام بروکری که این آداپتر به آن تعلق دارد (مثل ``"آگاه"``).

        باید با نام ثبت‌شده‌ی همان بروکر در ``BrokerManager`` یکسان باشد.
        """
        raise NotImplementedError

    @abstractmethod
    def begin_login(self, username: str, password: str) -> LoginChallenge:
        """
        شروع یک تلاش ورود و دریافت چالش.

        اعتبارنامه فقط برای همین تلاش نگه داشته می‌شود و بلافاصله پس از
        پایان آن (موفق، ناموفق یا لغو) از حافظه پاک می‌شود.

        در صورت شکست دریافت چالش، ``LoginChallengeError`` پرتاب می‌شود و
        هیچ تلاش فعلی‌ای باز نمی‌ماند.
        """
        raise NotImplementedError

    @abstractmethod
    def complete_login(self, response: str) -> AuthenticatedSession:
        """
        تکمیل تلاش ورود با پاسخ کاربر به چالش.

        فقط پس از تأیید موفقیت واقعی API، یک ``AuthenticatedSession``
        برمی‌گرداند. در غیر این صورت یکی از خطاهای قرارداد را پرتاب
        می‌کند:

            ``LoginNotInProgressError``    تلاش فعالی وجود ندارد.
            ``LoginRejectedError``          اعتبارنامه یا چالش رد شد.
            ``IncompleteLoginError``        پاسخ ظاهراً موفق اما ناقص.
            ``AuthenticationUnavailableError``  ارتباط ممکن نشد.

        در هر حالت شکست، تلاش فعلی پایان می‌یابد و وضعیت موقت پاک می‌شود.
        """
        raise NotImplementedError

    @abstractmethod
    def cancel_login(self) -> None:
        """
        لغو تلاش ورود در حال انجام.

        وضعیت موقت تلاش (از جمله چالش و اعتبارانه‌ی نگه‌داشته‌شده) پاک
        می‌شود. اگر تلاشی در حال انجام نباشد، ``LoginNotInProgressError``
        پرتاب می‌شود.
        """
        raise NotImplementedError

    @abstractmethod
    def is_authenticated(self) -> bool:
        """
        آیا این حساب در حال حاضر احراز هویت شده است؟

        فقط بر اساس نتیجه‌ی تأییدشده‌ی یک ورود کامل تصمیم می‌گیرد؛ هرگز
        حالت واردشده را فرض نمی‌کند.
        """
        raise NotImplementedError

    @abstractmethod
    def get_authenticated_session(self) -> Optional[AuthenticatedSession]:
        """
        نشست احراز شده‌ی این حساب، یا ``None`` اگر وارد نشده است.

        شیء برگشتی محرمانه است و نباید لاگ یا نمایش داده شود.
        """
        raise NotImplementedError

    def get_tradable_balance(self):
        """
        موجودی قابل‌معاملهٔ سطح حساب (قدرت خرید) از API خود broker.

        این قرارداد مستقل از نام و جزئیات broker است: هر پیاده‌سازی
        باید از runtime و نشست اختصاصی همین حساب استفاده کند و مقدار
        ``tradableBalanceT1`` را برگرداند؛ نه ظرفیت خرید نمادمحور
        (``calculatedquantity``).

        پیاده‌سازی پیش‌فرض **abstract نیست** تا آداپترهای brokerهایی که
        API مستند/پیاده‌سازی‌شده‌ای برای این مقدار ندارند همچنان قابل
        ساخت بمانند. چنین آداپتری صریحاً ``NotImplementedError`` پرتاب
        می‌کند و هیچ رفتاری حدس زده نمی‌شود؛ لایهٔ UI مقدار را «نامشخص»
        نمایش می‌دهد.
        """
        raise NotImplementedError(
            "این آداپتر قابلیت دریافت موجودی قابل‌معامله را "
            "پیاده‌سازی نکرده است."
        )

    def refresh_authenticated_session(self) -> AuthenticatedSession:
        """
        نوسازی نشست احرازشدهٔ همین حساب و بازگرداندن یک
        ``AuthenticatedSession`` تازه.

        این قرارداد **مستقل از بروکر** است: هیچ endpoint، مسیر، فیلد
        JSON یا نام بروکر در این امضا ظاهر نمی‌شود. پیاده‌سازی هر بروکر
        جزئیات اختصاصی خود را پشت همین متد نگه می‌دارد.

        پیش‌نیاز قرارداد: این حساب باید از قبل احراز هویت شده باشد
        (``is_authenticated()`` برابر ``True`` و
        ``get_authenticated_session()`` غیر ``None``). در غیر این صورت
        پیاده‌سازی باید fail-closed شکست بخورد.

        در صورت موفقیت، پیاده‌سازی باید نشست احرازشدهٔ خود را با توکن‌های
        تازه به‌روز کند و همان نشست را برگرداند. در صورت شکست، نشست
        قبلی باید دست‌نخورده باقی بماند و ``TokenRefreshError`` پرتاب
        شود؛ هیچ توکنی نباید در پیام خطا یا زنجیرهٔ استثنا افشا شود.

        پیاده‌سازی پیش‌فرض این متد **abstract نیست** تا آداپترهای موجودی
        که نوسازی توکن را پشتیبانی نمی‌کنند همچنان قابل ساخت بمانند؛
        چنین آداپتری به‌صورت صریح و ایمن ``TokenRefreshError`` پرتاب
        می‌کند و هیچ رفتاری فرض نمی‌شود.

        خطای پرتاب‌شده حتی اگر این متد داخل یک بلوک ``except`` بیرونی صدا
        زده شود، ``__context__`` و ``__cause__`` محرمانه را حمل نمی‌کند.
        """
        _raise_clean(
            TokenRefreshError(
                "این آداپتر از نوسازی نشست احرازشده پشتیبانی نمی‌کند"
            )
        )

    def set_request_recovery_handler(self, handler) -> None:
        """
        Attach a generic recovery handler invoked when an already-authenticated
        request is rejected with HTTP 401. The handler is account-scoped and
        must synchronize the refreshed session (broker + adapter + SessionManager)
        before returning, or raise to signal recovery failure.

        Passing ``None`` detaches any previously installed handler.
        """
        # Default: no-op. Adapters that support 401 recovery override this.
        pass

    def clear_authenticated_session(self) -> None:
        """
        Drop every retained authenticated artifact of THIS account after a
        failed 401 recovery, so no stale authenticated state stays usable.

        Implementations clear their ``AuthenticatedSession`` and any tokens or
        recovery handler retained in the underlying broker. This is a
        best-effort, fail-safe operation: it must never raise, and it never
        affects another account. The default is a no-op for adapters that hold
        no retained authenticated state; such an adapter is still removed from
        the service by the caller.
        """
        # Default: no-op. Adapters that retain authenticated state override.
        pass
