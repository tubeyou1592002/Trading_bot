"""
brokers/agaah/auth_adapter.py — Block 9, Task 4, Stage 2.

آداپتر احراز هویت آگاه.

این ماژول پیاده‌سازی قرارداد عمومی
(``brokers.authentication.AuthenticationAdapter``) برای بروکر آگاه است.
تمام منطق اختصاصی آگاه (کپچا، captchaId، ساختار پاسخ ورود) فقط اینجا
زندگی می‌کند و از مرز قرارداد عبور نمی‌کند.

استفاده از رفتار واقعی و موجود API آگاه
----------------------------------------
این آداپتر هیچ endpoint یا رفتار جدیدی اختراع نمی‌کند. فقط از دو متد
موجود ``AgaahBroker.get_captcha()`` و ``AgaahBroker.login()`` استفاده
می‌کند:

    get_captcha() -> {"captchaId": ..., "captcha": <base64 image>}

    login(username, password, captcha, captcha_id)
        -> {"userName": ..., "userIdentifier": ..., "hasRefreshToken": ...}
        و در صورت موفقیت access_token / refresh_token / user_identifier
        را روی همان نمونه‌ی بروکر ثبت می‌کند.

المان‌های اختصاصی آگاه که باید داخل همین آداپتر بمانند:

    * captchaId دریافت‌شده از get_captcha() — فقط اینجا نگه داشته می‌شود
      تا در complete_login با پاسخ کاربر جفت شود. این مقدار هرگز در
      LoginChallenge یا هر خروجی عمومی قرار نمی‌گیرد.
    * وضعیت همان یک تلاش ورود.
    * نگه‌داری موقت اعتبارانه فقط برای طول عمر همان تلاش.

مرز نمونه‌ها
-----------
هر آداپتر متعلق به **یک** حساب است و یک نمونه مستقل ``AgaahBroker`` را
در بر می‌گیرد. دو حساب روی آگاه هرگز یک نشست HTTP، یک وضعیت ورود یا
یک توکن را به اشتراک نمی‌گذارند (قانون معماری Block 9 Task 4).

امنیت
-----
هیچ رمز عبور یا توکنی نباید در پیام خطا، ``repr`` یا زنجیره‌ی
استثناها (``__cause__`` / ``__context__``) افشا شود. بنابراین پیش از
ساخت خطای نهایی، همه‌ی مقادیر محرمانه‌ی موجود (رمز عبور همان تلاش،
توکن‌های بروکر و توکن‌های نشست احرازشده) جمع‌آوری و متن خطا با آن‌ها
پاک‌سازی می‌شود و خطای نهایی بدون زنجیره‌ی استثنای محرمانه منتشر
می‌شود.

تست آفلاین
----------
به صورت پیش‌فرض یک نمونه‌ی واقعی ``AgaahBroker`` ساخته می‌شود که خودش
یک requests.Session واقعی دارد؛ اما می‌توان یک نمونه از پیش ساخته‌شده
را به broker= پاس داد و نشست HTTP جعلی را روی broker.session نصب کرد.
تست‌ها این‌گونه کار می‌کنند و هیچ درخواست شبکه‌ای واقعی ارسال نمی‌شود.
"""

from typing import List, Optional

from brokers.authentication import (
    AuthenticatedSession,
    AuthenticationAdapter,
    AuthenticationUnavailableError,
    CHALLENGE_CAPTCHA_IMAGE,
    IncompleteLoginError,
    LoginChallenge,
    LoginChallengeError,
    LoginNotInProgressError,
    LoginRejectedError,
    TokenRefreshError,
)

from .broker import AgaahBroker


_REDACTED = "***"


def _redact(text: str, secrets) -> str:
    """
    حذف هر یک از مقادیر محرمانه از متن پیام.

    اگر متن حاوی رمز عبور یا توکن باشد، آن بخش با REDACTED جایگزین
    می‌شود تا یک پیام خطای سرویس نتواند محرمانه را echo کند.
    """
    cleaned = text
    for secret in secrets:
        if not isinstance(secret, str) or not secret:
            continue
        if secret in cleaned:
            cleaned = cleaned.replace(secret, _REDACTED)
    return cleaned


def _is_incomplete_login_error(exc: Exception) -> bool:
    """
    تشخیص «پاسخ ظاهراً موفق اما ناقص» از «رد ورود توسط سرور».

    AgaahBroker.login() در هر دو حالت RuntimeError پرتاب می‌کند، اما
    پیام‌های مربوط به نقص پاسخ (نبود accessToken / userIdentifier /
    data معتبر) از پیام‌های رد شده توسط API متمایز هستند. این تشخیص فقط
    بر اساس پیام‌های شناخته‌شده‌ی خود AgaahBroker انجام می‌شود و هیچ
    رفتار API جدیدی فرض نمی‌کند.
    """
    message = str(exc)
    markers = (
        "accessToken",
        "userIdentifier",
        "پاسخ ورود فاقد data",
    )
    return any(marker in message for marker in markers)


class AgahAuthenticationAdapter(AuthenticationAdapter):
    """
    پیاده‌سازی قرارداد احراز هویت برای بروکر آگاه.

    یک نمونه = یک حساب + یک AgaahBroker مستقل + یک نشست HTTP مستقل.
    """

    def __init__(self, broker: Optional[AgaahBroker] = None):
        """
        broker: نمونه‌ی AgaahBroker این حساب. اگر داده نشود، یک نمونه‌ی
        جدید ساخته می‌شود. تزریق نمونه مسیر تست آفلاین است: می‌توان یک
        نشست HTTP جعلی روی broker.session نصب کرد.
        """
        self._broker = broker if broker is not None else AgaahBroker()

        # وضعیت موقتِ همین یک تلاش ورود. بعد از پایان تلاش (موفق، ناموفق
        # یا لغو) همه پاک می‌شوند.
        self._pending_captcha_id: Optional[str] = None
        self._pending_username: Optional[str] = None
        self._pending_password: Optional[str] = None

        self._authenticated: Optional[AuthenticatedSession] = None

    @property
    def broker_name(self) -> str:
        return self._broker.name

    @property
    def broker(self) -> AgaahBroker:
        """نمونه‌ی مستقل بروکر این حساب (برای استفاده‌ی بعد از ورود)."""
        return self._broker

    # ------------------------------------------------------------------
    # داخلی
    # ------------------------------------------------------------------

    def _has_pending_login(self) -> bool:
        return self._pending_captcha_id is not None

    def _clear_pending(self) -> None:
        """پاک‌سازی کامل وضعیت موقت تلاش؛ اعتبارانه آزاد می‌شود."""
        self._pending_captcha_id = None
        self._pending_username = None
        self._pending_password = None

    def _current_secrets(self) -> List[str]:
        """
        مقادیر محرمانه‌ای که همین حالا در آداپتر موجودند.

        شامل رمز عبور تلاش جاری و توکن‌های نشست احرازشده (در صورت وجود).
        """
        secrets: List[str] = []
        if isinstance(self._pending_password, str) and self._pending_password:
            secrets.append(self._pending_password)
        if self._authenticated is not None:
            if self._authenticated.access_token:
                secrets.append(self._authenticated.access_token)
            if self._authenticated.refresh_token:
                secrets.append(self._authenticated.refresh_token)
        return secrets

    def _get_redact_secrets(self, password: Optional[str] = None) -> List[str]:
        """
        جمع‌آوری کامل مقادیر محرمانه برای redact کردن پیام خطا.

        شامل:
        - رمز عبور تلاش جاری (از طریق _current_secrets)؛
        - رمز عبور همین تلاش که به‌صورت صریح پاس داده شده است، چون در
          complete_login وضعیت pending ممکن است پیش از پاک‌سازی متن خطا
          پاک شده باشد؛
        - access_token و refresh_token موجود در شیء broker؛
        - access_token و refresh_token موجود در AuthenticatedSession.
        """
        secrets = self._current_secrets()
        if isinstance(password, str) and password and password not in secrets:
            secrets.append(password)

        for value in (
            getattr(self._broker, "access_token", None),
            getattr(self._broker, "refresh_token", None),
        ):
            if isinstance(value, str) and value and value not in secrets:
                secrets.append(value)

        return [s for s in secrets if isinstance(s, str) and s]

    @staticmethod
    def _raise_clean(error: Exception) -> None:
        """
        انتشار یک خطای پاک‌سازی‌شده بدون زنجیره‌ی استثنای محرمانه.

        صرف ``raise ... from None`` یا صفر کردن ``__context__`` پیش از
        ``raise`` کافی نیست: وقتی آداپتر داخل یک بلوک ``except`` بیرونی
        صدا زده شود، خود مفسر در لحظه‌ی ``raise`` مقدار ``__context__`` را
        روی استثنای در حال هندل تنظیم می‌کند و محرمانه دوباره برمی‌گردد.

        راه‌حل: خطا داخل یک ``try/except`` داخلی بالا انداخته، گرفته و
        دوباره پاک‌سازی می‌شود و سپس با ``raise`` بدون آرگومان منتشر
        می‌گردد. در آن لحظه استثنای فعال همان خطای جاری است، پس مفسر
        ``__context__`` جدیدی روی آن نمی‌گذارد و مقدار ``None`` حفظ می‌شود.
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

    # ------------------------------------------------------------------
    # قرارداد عمومی
    # ------------------------------------------------------------------

    def begin_login(self, username: str, password: str) -> LoginChallenge:
        """
        دریافت کپچا از آگاه و شروع یک تلاش ورود.

        از AgaahBroker.get_captcha() موجود استفاده می‌کند. تصویر کپچا
        (Base64) به‌عنوان محتوای قابل نمایش در LoginChallenge قرار
        می‌گیرد؛ captchaId فقط داخل این آداپتر نگه داشته می‌شود.

        اگر این حساب از قبل احراز هویت شده باشد، تلاش ورود دیگری رد
        می‌شود و نشست، توکن‌ها و وضعیت احراز قبلی دست‌نخورده می‌مانند.
        """
        if self._authenticated is not None:
            raise LoginNotInProgressError(
                "این حساب از قبل احراز هویت شده است؛ برای ورود مجدد ابتدا "
                "نشست فعلی باید بسته شود."
            )

        if self._has_pending_login():
            raise LoginNotInProgressError(
                "یک تلاش ورود دیگر از قبل در حال انجام است؛ "
                "ابتدا باید لغو یا تکمیل شود."
            )

        if not isinstance(username, str) or not username.strip():
            raise LoginNotInProgressError(
                "username برای شروع ورود الزامی است."
            )
        if not isinstance(password, str) or not password.strip():
            raise LoginNotInProgressError(
                "password برای شروع ورود الزامی است."
            )

        error = None
        captcha_data = None
        try:
            captcha_data = self._broker.get_captcha()
        except Exception as exc:
            error = exc

        if error is not None or not isinstance(captcha_data, dict):
            self._clear_pending()
            secrets = self._get_redact_secrets(password)
            detail = "" if error is None else _redact(str(error), secrets)
            if error is not None:
                # خود استثنای اصلی نیز پاک‌سازی می‌شود تا حتی اگر جایی
                # نگه داشته شود، محرمانه را حمل نکند.
                error.args = (detail,)
            self._raise_clean(
                LoginChallengeError(
                    "دریافت کپچا از آگاه ناموفق بود"
                    + (f": {detail}" if detail else "")
                )
            )

        captcha_id = captcha_data.get("captchaId")
        captcha_image = captcha_data.get("captcha")

        if not captcha_id or not captcha_image:
            self._clear_pending()
            self._raise_clean(
                LoginChallengeError(
                    "پاسخ کپچای آگاه ناقص است "
                    "(captchaId یا captcha خالی است)."
                )
            )

        self._pending_captcha_id = captcha_id
        self._pending_username = username
        self._pending_password = password

        return LoginChallenge(
            kind=CHALLENGE_CAPTCHA_IMAGE,
            display_payload=captcha_image,
            prompt="کد تصویر کپچای آگاه را وارد کنید.",
        )

    def complete_login(self, response: str) -> AuthenticatedSession:
        """
        تکمیل ورود آگاه با پاسخ کپچا.

        از AgaahBroker.login() موجود با همان captchaId دریافتی استفاده
        می‌کند. موفقیت فقط زمانی تأیید می‌شود که هم توکن دسترسی معتبر و
        هم userIdentifier از پاسخ واقعی API حاصل شده باشند؛ در غیر این
        صورت IncompleteLoginError پرتاب می‌شود و حساب وارد نمی‌شود.
        """
        if not self._has_pending_login():
            raise LoginNotInProgressError(
                "تلاش ورودی در حال انجام نیست؛ ابتدا begin_login را "
                "صدا بزنید."
            )

        captcha_id = self._pending_captcha_id
        username = self._pending_username
        password = self._pending_password

        if not isinstance(response, str) or not response.strip():
            self._clear_pending()
            self._raise_clean(
                LoginRejectedError(
                    "پاسخ کپچا نمی‌تواند خالی باشد."
                )
            )

        error = None
        login_result = None
        try:
            login_result = self._broker.login(
                username=username,
                password=password,
                captcha=response.strip(),
                captcha_id=captcha_id,
            )
        except Exception as exc:
            error = exc
        finally:
            # اعتبارانه فقط برای طول عمر همین تلاش نگه داشته می‌شد.
            self._clear_pending()

        if error is not None:
            # ترتیب مهم است: تشخیص نقص پیش از پاک‌سازی پیام انجام می‌شود،
            # چون redact نشانگرهای accessToken/userIdentifier را حذف
            # می‌کند.
            incomplete = _is_incomplete_login_error(error)
            # رمز عبور همین تلاش صریحاً پاس می‌شود چون pending پاک شده
            # است؛ توکن‌های بروکر و نشست هم جمع‌آوری می‌شوند.
            secrets = self._get_redact_secrets(password)
            detail = _redact(str(error), secrets)
            # خود استثنای اصلی نیز پاک‌سازی می‌شود.
            error.args = (detail,)

            if isinstance(error, AuthenticationUnavailableError):
                self._raise_clean(
                    AuthenticationUnavailableError(
                        "ارتباط با سرویس ورود آگاه ممکن نشد"
                    )
                )
            if incomplete:
                self._raise_clean(
                    IncompleteLoginError(
                        "ورود آگاه کامل نبود: " + detail
                    )
                )
            self._raise_clean(
                LoginRejectedError(
                    "ورود به آگاه ناموفق بود: " + detail
                )
            )

        # ------------------------------------------------------
        # تأیید نتیجه از روی وضعیت واقعی بروکر. این بررسی مستقل از
        # پیام‌هاست و fail-closed است: اگر فیلدهای الزامی موجود نباشند،
        # ورود کامل تلقی نمی‌شود.
        # ------------------------------------------------------

        access_token = getattr(self._broker, "access_token", None)
        user_identifier = getattr(self._broker, "user_identifier", None)

        if not access_token or not user_identifier:
            self._raise_clean(
                IncompleteLoginError(
                    "ورود آگاه کامل نبود: accessToken یا userIdentifier از "
                    "پاسخ API حاصل نشد."
                )
            )

        if not isinstance(login_result, dict):
            self._raise_clean(
                IncompleteLoginError(
                    "خروجی ورود آگاه ساختار معتبری نداشت."
                )
            )

        self._authenticated = AuthenticatedSession(
            access_token=access_token,
            user_identifier=user_identifier,
            refresh_token=getattr(self._broker, "refresh_token", None),
            user_name=login_result.get("userName"),
        )

        return self._authenticated

    def cancel_login(self) -> None:
        """لغو تلاش ورود در حال انجام و پاک‌سازی وضعیت موقت آگاه."""
        if not self._has_pending_login():
            raise LoginNotInProgressError(
                "تلاش ورود در حال انجام نیست که لغو شود."
            )
        self._clear_pending()

    def is_authenticated(self) -> bool:
        """آیا این حساب با یک ورود کاملِ تأییدشده وارد شده است؟"""
        return self._authenticated is not None

    def get_authenticated_session(self) -> Optional[AuthenticatedSession]:
        """نشست احرازشده‌ی این حساب، یا None اگر وارد نشده است."""
        return self._authenticated

    def get_tradable_balance(self):
        """
        موجودی قابل‌معاملهٔ همین حساب آگاه (قدرت خرید).

        فقط روی نمونه‌ی بروکرِ همین حساب اجرا می‌شود تا نشست و runtime
        حساب‌های دیگر دخالت نکنند. جزئیات endpoint و فیلد پاسخ داخل
        ``AgaahBroker.get_tradable_balance`` باقی می‌ماند و هیچ پیام
        حساسی به لایه‌ی بالاتر منتقل نمی‌شود.
        """
        if self._authenticated is None:
            self._raise_clean(
                AuthenticationUnavailableError(
                    "این حساب هنوز احراز هویت نشده است؛ دریافت قدرت "
                    "خرید ممکن نیست."
                )
            )

        try:
            return self._broker.get_tradable_balance()
        except Exception:
            self._raise_clean(
                AuthenticationUnavailableError(
                    "دریافت قدرت خرید از آگاه ناموفق بود"
                )
            )

    def set_request_recovery_handler(self, handler) -> None:
        # Forward to underlying broker if it supports setting recovery handler
        try:
            set_handler = getattr(self._broker, "set_unauthorized_recovery", None)
            if callable(set_handler):
                set_handler(handler)
        except Exception:
            pass

    def clear_authenticated_session(self) -> None:
        """
        Drop this account's retained authenticated state after a failed 401
        recovery. Best-effort and fail-safe: never raises, never touches
        another account.

        Clears the adapter's ``AuthenticatedSession``, detaches the 401
        recovery handler from the underlying account-owned broker and clears
        that broker's access/refresh token and user identifier, so neither the
        adapter nor the broker can serve a stale authenticated view after the
        account's local session has been invalidated.
        """
        self._authenticated = None
        try:
            self._broker.set_unauthorized_recovery(None)
        except Exception:
            pass
        try:
            self._broker.access_token = None
            self._broker.refresh_token = None
            self._broker.user_identifier = None
        except Exception:
            pass

    def refresh_authenticated_session(self) -> AuthenticatedSession:
        """
        نوسازی توکن‌های آگاه برای همین حسابِ احرازشده.

        این متد فقط قرارداد مستقل از بروکر
        (``AuthenticationAdapter.refresh_authenticated_session``) را
        پیاده می‌کند و جزئیات اختصاصی آگاه (endpoint، فیلدهای JSON،
        ساختار پاسخ) داخل خودِ ``AgaahBroker.refresh_tokens()``
        می‌مانند.

        مسیر کار:

            1. پیش‌نیاز: این آداپتر باید از قبل احراز هویت شده و یک
               ``AuthenticatedSession`` داشته باشد؛ در غیر این صورت
               بدون هیچ درخواستی ``TokenRefreshError`` پرتاب می‌شود.
            2. فراخوانی ``self._broker.refresh_tokens()`` روی نمونه‌ی
               بروکر همین حساب (هیچ نمونه یا آداپتر دیگری دخالت ندارد).
            3. در صورت شکست، نشست قبلی دست‌نخورده می‌ماند و یک خطای
               پاک‌سازی‌شده بدون افشای توکن یا زنجیره‌ی استثنای حساس
               پرتاب می‌شود.
            4. در صورت موفقیت، توکن‌های تازه‌ی بروکر اعتبارسنجی شده و یک
               ``AuthenticatedSession`` تازه ساخته می‌شود که
               ``user_identifier`` و ``user_name`` قبلی را حفظ می‌کند
               (این endpoint بازگرداندن مقدار تازه‌ای برای آن‌ها تأیید
               نشده است). تنها پس از اعتبارسنجی کامل، ``_authenticated``
               جایگزین می‌شود.

        هیچ نوسازی یا retry خودکاری در متدهای درخواست انجام نمی‌شود؛ این
        متد فقط با فراخوانی صریح اجرا می‌گردد.
        """
        if self._authenticated is None:
            self._raise_clean(
                TokenRefreshError(
                    "این حساب هنوز احراز هویت نشده است؛ نوسازی توکن "
                    "ممکن نیست."
                )
            )

        previous = self._authenticated

        error = None
        try:
            self._broker.refresh_tokens()
        except Exception as exc:
            error = exc

        if error is not None:
            secrets = self._get_redact_secrets()
            detail = _redact(str(error), secrets)
            # خود استثنای اصلی نیز پاک‌سازی می‌شود تا حتی اگر جایی نگه
            # داشته شود، محرمانه را حمل نکند.
            error.args = (detail,)
            self._raise_clean(
                TokenRefreshError(
                    "نوسازی توکن آگاه ناموفق بود"
                    + (f": {detail}" if detail else ".")
                )
            )

        access_token = getattr(self._broker, "access_token", None)
        refresh_token = getattr(self._broker, "refresh_token", None)

        if not isinstance(access_token, str) or not access_token.strip():
            self._raise_clean(
                TokenRefreshError(
                    "accessToken جایگزین پس از نوسازی معتبر نیست."
                )
            )

        if not isinstance(refresh_token, str) or not refresh_token.strip():
            self._raise_clean(
                TokenRefreshError(
                    "refreshToken جایگزین پس از نوسازی معتبر نیست."
                )
            )

        refreshed = AuthenticatedSession(
            access_token=access_token,
            user_identifier=previous.user_identifier,
            refresh_token=refresh_token,
            user_name=previous.user_name,
        )

        self._authenticated = refreshed
        return refreshed


# ---------------------------------------------------------------------------
# Factory آماده برای لایه‌های بالاتر
# ---------------------------------------------------------------------------

def make_agah_adapter_factory(broker_manager):
    """
    ساخت factory آگاه متصل به مدیر بروکر تزریق‌شده.

    factory شناسه‌ی حساب را دریافت می‌کند و broker را فقط از مسیر
    ``get_for_account(account_id, "آگاه")`` resolve می‌کند. هر آداپتر
    تازه همان broker حساب‌محور را می‌پیچد؛ ساخت broker و جداسازی حساب‌ها
    تحت مالکیت BrokerManager باقی می‌ماند.

    این تابع مسیر ثبت آگاه در ``AuthenticationService`` است: لایه‌ی
    فراخوان manager را به این factory تزریق می‌کند؛ سرویس فقط factory
    عمومی و account_id را می‌شناسد.
    """

    def factory(account_id: str) -> AgahAuthenticationAdapter:
        broker = broker_manager.get_for_account(account_id, "آگاه")
        return AgahAuthenticationAdapter(broker)

    return factory
