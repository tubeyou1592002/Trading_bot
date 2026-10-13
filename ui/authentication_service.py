"""
ui/authentication_service.py — Block 9, Task 4, Stage 2.

سرویس هماهنگ‌کننده‌ی احراز هویت حساب‌ها.

این لایه، چهار جزء موجود را به هم وصل می‌کند و یک API برنامه‌ای برای
ورود به حساب‌ها فراهم می‌کند:

    AccountStore          هویت حساب و نام بروکر آن
    CredentialStore       اعتبارانه با کلید (account_id, broker_name)
    SessionManager        وضعیت نشست همان حساب
    AuthenticationAdapter پیاده‌سازی اختصاصی بروکر (آداپتر آگاه)

مرز معماری
----------
    AuthenticationService (این ماژول)
        ├── begin_login(account_id)               -> LoginChallenge
        ├── complete_login(account_id, response)  -> Session
        ├── cancel_login(account_id)              -> None
        ├── refresh_session(account_id)           -> Session
        ├── is_logged_in(account_id)              -> bool
        └── get_adapter(account_id)               -> AuthenticationAdapter | None

استقلال از بروکر (seam لایه‌ی UI)
--------------------------------
این ماژول **هیچ** کد بروکری را import نمی‌کند و نام هیچ بروکری در آن
hard-code نشده است. پیاده‌سازی‌های آداپتر از طریق تزریق
``adapter_factories`` (یک نگاشت از نام بروکر به تابع سازنده‌ی آداپتر)
وارد می‌شوند. این سرویس فقط قرارداد ``AuthenticationAdapter`` را
می‌شناسد، نه پیاده‌سازی آگاه را. نام بروکر ناشناخته fail-closed رد
می‌شود و هیچ رفتار حدسی انجام نمی‌شود.

قوانین قرارداد (Block 9 — Task 4):

    * حساب و بروکر از AccountStore خوانده می‌شوند؛ اعتبارانه با همان
      زوج (account_id, broker_name) از CredentialStore دریافت می‌شود.
    * اگر نشست حساب ثبت نشده باشد، با همان شناسه‌ی حساب و بروکر ثبت
      می‌شود؛ اگر نشست موجود با بروکر حساب تطابق نداشته باشد، عملیات
      رد می‌شود (fail-closed، بدون حدس).
    * هر حساب نمونه‌ی مستقل بروکر/آداپتر و نشست HTTP مستقل خود را
      دارد. یک نمونه‌ی بروکر با وضعیت احراز قابل‌تغییر هرگز بین چند
      حساب به اشتراک گذاشته نمی‌شود.
    * شروع ورود یک چالش عمومی و قابل‌نمایش برمی‌گرداند؛ جزئیات
      اختصاصی بروکر (مثل captchaId آگاه) فقط داخل آداپتر می‌مانند.
    * تکمیل ورود فقط پس از دریافت پاسخ چالش و تأیید موفقیت واقعی API
      مجاز است؛ پاسخ ظاهراً موفق اما ناقص حساب را وارد نمی‌کند.
    * در ورود ناموفق، نشست همان حساب به LOGGED_OUT برمی‌گردد، اطلاعات
      موقت پاک می‌شود و نمونه‌ی ناموفق حذف می‌شود.
    * پس از ورود موفق، وضعیت و توکن در SessionManager ثبت می‌شود و
      نمونه‌ی احرازشده برای استفاده‌ی آتی نگه داشته می‌شود.
    * از همان SessionManager موجود استفاده می‌شود و قرارداد آن تغییر
      نمی‌کند.
    * این ماژول هیچ رفتار سفارش‌گذاری، مسیر موازی یا تغییری در
      DispatchCore / OrderEngine ایجاد نمی‌کند.

تست آفلاین
----------
تست‌ها نگاشت adapter_factories خود را (آداپترهای جعلی) تزریق می‌کنند،
بنابراین هیچ درخواست شبکه‌ای، اعتبارانه‌ی واقعی یا نمونه‌ی واقعی
بروکر استفاده نمی‌شود.
"""

from typing import Callable, Dict, Optional

from .account_store import AccountStore, AccountStoreError
from .credential_store import CredentialStore, CredentialNotFoundError
from .session_manager import (
    Session,
    SessionManager,
    SessionNotFoundError,
    SessionState,
    SessionStateError,
)


class AuthenticationServiceError(Exception):
    """پایه‌ی خطاهای سرویس احراز هویت."""


class UnknownBrokerError(AuthenticationServiceError):
    """
    نام بروکر این حساب پشتیبانی نمی‌شود.

    هیچ رفتار حدسی برای بروکر ناشناخته انجام نمی‌شود (fail-closed).
    """


class InconsistentSessionError(AuthenticationServiceError):
    """
    نشست ثبت‌شده‌ی این حساب با بروکرِ حساب تطابق ندارد.

    عملیات رد می‌شود تا نشست و حساب هرگز با هم قاطی نشوند.
    """


class NoPendingLoginError(AuthenticationServiceError):
    """تلاش ورودی برای این حساب در حال انجام نیست."""


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


class AuthenticationService:
    """
    هماهنگ‌کننده‌ی ورود به حساب‌ها.

    یک سرویس = یک AccountStore + یک CredentialStore + یک SessionManager
    + مجموعه‌ای از آداپترهای مستقل، یکی برای هر حساب.
    """

    def __init__(
        self,
        account_store: AccountStore,
        credential_store: CredentialStore,
        session_manager: SessionManager,
        adapter_factories: Optional[Dict[str, Callable[[], "AuthenticationAdapter"]]] = None,
    ):
        """
        account_store:    منبع هویت حساب و نام بروکر.
        credential_store: منبع اعتبارانه با کلید (account_id, broker_name).
        session_manager:  مدیریت‌کننده‌ی وضعیت نشست همان حساب.
        adapter_factories: نگاشت نام بروکر به تابعی که یک آداپترِ مستقل
                          و تازه برای آن بروکر می‌سازد. این تنها مسیر
                          ورود پیاده‌سازی‌های بروکر به این سرویس است
                          (تزریق وابستگی) تا لایه‌ی UI به هیچ کد بروکری
                          وابسته نشود. هر فراخوانی باید یک نمونه‌ی جدید
                          بسازد؛ نمونه‌ها بین حساب‌ها به اشتراک گذاشته
                          نمی‌شوند.

        اگر adapter_factories خالی یا None باشد، سرویس برای هر نام
        بروکری fail-closed برمی‌گردد؛ هیچ بروکری به‌صورت پیش‌فرض
        حدس زده نمی‌شود.
        """
        self._accounts = account_store
        self._credentials = credential_store
        self._sessions = session_manager
        self._adapter_factories: Dict[str, Callable] = dict(
            adapter_factories or {}
        )

        # account_id -> آداپتر احرازشده‌ی نگه‌داشته‌شده برای استفاده‌ی آتی.
        self._adapters: Dict[str, "AuthenticationAdapter"] = {}

        # account_id -> آداپتر تلاش ورودِ در حال انجام. این نگاشت فقط
        # برای طول عمر یک چالش باز است و بعد از موفقیت به _adapters
        # منتقل می‌شود، و بعد از شکست یا لغو کاملاً حذف می‌شود.
        self._pending_logins: Dict[str, "AuthenticationAdapter"] = {}

    # ------------------------------------------------------------------
    # داخلی
    # ------------------------------------------------------------------

    def _resolve_account(self, account_id):
        """
        خواندن حساب از AccountStore و بررسی سازگاری نشست با بروکر حساب.

        اگر نشست حساب ثبت نشده باشد، با همان شناسه و بروکر ثبت می‌شود.
        """
        try:
            record = self._accounts.get(account_id)
        except AccountStoreError as exc:
            raise AuthenticationServiceError(str(exc)) from None

        broker_name = record.broker_name

        try:
            existing = self._sessions.get(account_id)
        except SessionNotFoundError:
            self._sessions.register(account_id, broker_name)
            existing = self._sessions.get(account_id)

        if existing.broker_name != broker_name:
            raise InconsistentSessionError(
                "نشست ثبت‌شده‌ی این حساب با بروکر حساب تطابق ندارد"
            )

        return record

    def _load_credentials(self, account_id, broker_name):
        """دریافت اعتبارانه با همان زوج (account_id, broker_name)."""
        try:
            return self._credentials.get_credentials(account_id, broker_name)
        except CredentialNotFoundError as exc:
            raise AuthenticationServiceError(str(exc)) from None

    def _build_adapter(self, broker_name):
        """
        ساخت یک آداپترِ مستقل و تازه برای این حساب.

        نام بروکر باید در adapter_factories ثبت شده باشد؛ در غیر این
        صورت fail-cلود رد می‌شود (UnknownBrokerError) و هیچ رفتار حدسی
        انجام نمی‌شود.
        """
        factory = self._adapter_factories.get(broker_name)
        if factory is None:
            raise UnknownBrokerError(
                f"هیچ آداپتری برای نام بروکر ثبت نشده است: {broker_name!r}"
            )
        return factory()

    def _clear_pending(self, account_id):
        """
        حذف آداپتر یک تلاش ناموفق/لغوشده و برگرداندن نشست همان حساب به
        LOGGED_OUT.
        """
        self._pending_logins.pop(account_id, None)
        try:
            if self._sessions.state(account_id) is SessionState.LOGIN_PENDING:
                self._sessions.fail_login(account_id)
        except SessionNotFoundError:
            pass

    # ------------------------------------------------------------------
    # API برنامه‌ای
    # ------------------------------------------------------------------

    def begin_login(self, account_id: str) -> "LoginChallenge":
        """
        شروع ورود یک حساب.

        ترتیب اصلاح‌شده:

            1. خواندن حساب و نام بروکر از AccountStore و بررسی/ثبت نشست
               در SessionManager.
            2. بررسی وضعیت نشست: اگر نشست از قبل LOGGED_IN یا
               LOGIN_PENDING باشد، AuthenticationServiceError پرتاب می‌شود.
            3. گذار نشست به LOGIN_PENDING از طریق SessionManager، پیش از
               هر کار جانبیِ پرهزینه (ساخت آداپتر، خواندن اعتبارانه یا
               درخواست کپچا).
            4. ساخت یک آداپتر مستقل برای این حساب (fail-closed اگر نام
               بروکر ثبت نشده است).
            5. دریافت اعتبارانه از CredentialStore.
            6. دریافت چالش از بروکر.
            7. در صورت موفقیت، آداپتر به عنوان تلاشِ در حال انجام ثبت
               می‌شود.

        یک شکست در هر مرحله‌ی پس از رزرو نشست (گام ۳)، نشست همان حساب
        را به LOGGED_OUT بازمی‌گرداند و وضعیت موقت آن تلاش را پاک می‌کند؛
        خطای اصلی به فراخواننده منتقل می‌شود.
        """
        record = self._resolve_account(account_id)

        # اگر حساب از قبل وارد شده یا یک تلاش ورود برای همین حساب در حال
        # انجام است: ورود تکراری/هم‌زمان رد می‌شود و هیچ عملیات جانبی
        # (ساخت آداپتر، خواندن اعتبارانه، درخواست بروکری) انجام نمی‌شود.
        current_state = self._sessions.state(account_id)
        if current_state is SessionState.LOGGED_IN:
            raise AuthenticationServiceError(
                "حساب از قبل وارد شده است؛ ورود مجدد مجاز نیست"
            )
        if current_state is SessionState.LOGIN_PENDING:
            raise AuthenticationServiceError(
                "یک تلاش ورود برای این حساب از قبل در حال انجام است"
            )

        # گذار نشست به LOGIN_PENDING، پیش از ساخت آداپتر، خواندن
        # اعتبارانه یا ارسال درخواست بروکری.
        self._sessions.begin_login(account_id)

        # ساخت آداپتر مستقل، خواندن اعتبارانه و شروع ورود بروکری.
        try:
            adapter = self._build_adapter(record.broker_name)
            credentials = self._load_credentials(
                account_id, record.broker_name
            )
            challenge = adapter.begin_login(
                credentials.username, credentials.password
            )
        except Exception:
            # شکست در ساخت آداپتر، بازیابی اعتبارانه یا دریافت چالش:
            # رزرو نشست لغو و وضعیت موقت آن تلاش پاک می‌شود؛ خطای اصلی
            # به فراخواننده منتقل می‌شود.
            self._clear_pending(account_id)
            raise

        # چالش دریافت شد: این آداپتر، تلاش ورود در حال انجام این حساب است.
        self._pending_logins[account_id] = adapter
        return challenge

    def complete_login(self, account_id: str, response: str) -> Session:
        """
        تکمیل ورود یک حساب با پاسخ چالش.

        فقط پس از تأیید موفقیت واقعی API توسط آداپتر، وضعیت نشست به
        LOGGED_IN و توکن در SessionManager ثبت می‌شود و آداپتر
        احرازشده برای استفاده‌ی آتی نگه داشته می‌شود.

        در هر شکست، نشست همان حساب به LOGGED_OUT برمی‌گردد، اطلاعات
        موقت پاک می‌شود و نمونه‌ی ناموفق حذف می‌شود.
        """
        adapter = self._pending_logins.get(account_id)
        if adapter is None:
            raise NoPendingLoginError(
                "تلاش ورودی برای این حساب در حال انجام نیست"
            )

        try:
            authenticated = adapter.complete_login(response)
        except Exception:
            # ورود ناموفق: پاکسازی کامل و برگرداندن نشست به LOGGED_OUT.
            self._clear_pending(account_id)
            raise

        try:
            session = self._sessions.mark_logged_in(
                account_id, token=authenticated.access_token
            )
        except Exception:
            # نشست نتوانست وارد شود؛ آداپترِ تلاش دور انداخته می‌شود.
            self._clear_pending(account_id)
            raise

        # ورود موفق: تلاش از حالت pending خارج و آداپتر احرازشده برای
        # استفاده‌ی آتی نگه داشته می‌شود.
        self._pending_logins.pop(account_id, None)
        self._adapters[account_id] = adapter
        return session

    def cancel_login(self, account_id: str) -> None:
        """
        لغو تلاش ورود یک حساب.

        وضعیت موقت پاک می‌شود، نشست به LOGGED_OUT برمی‌گردد و نمونه‌ی
        آداپترِ تلاش لغوشده حذف می‌شود. لغو فقط برای یک تلاش در حال
        انجام مجاز است.
        """
        adapter = self._pending_logins.get(account_id)
        if adapter is None:
            raise NoPendingLoginError(
                "تلاش ورودی برای این حساب در حال انجام نیست"
            )

        try:
            adapter.cancel_login()
        finally:
            self._clear_pending(account_id)

    def refresh_session(self, account_id: str) -> Session:
        """
        نوسازی صریح نشست احرازشدهٔ یک حساب و همگام‌سازی نمای توکن.

        این عملیات **مستقل از بروکر** است: سرویس هیچ endpoint، مسیر یا
        فیلد JSON اختصاصی آگاه را نمی‌شناسد و فقط قرارداد
        ``AuthenticationAdapter.refresh_authenticated_session()`` را
        فراخوانی می‌کند. هیچ نوسازی خودکار، retry، trigger، یا تغییر در
        مسیر سفارش انجام نمی‌شود؛ این متد فقط با فراخوانی صریح اجرا
        می‌گردد.

        ترتیب کار:

            1. رزولوشن و اعتبارسنجی حساب و نشست آن (fail-closed).
            2. پیش‌نیازها: حساب باید ``LOGGED_IN``، آداپتر همین حساب
               موجود و احرازشده باشد. اگر هر یک برقرار نباشد، **پیش از**
               فراخوانی آداپتر یا ارسال هر درخواستی رد می‌شود.
            3. فراخوانی قرارداد نوسازی روی آداپتر همین حساب.
            4. اعتبارسنجی ``AuthenticatedSession`` برگشتی و بررسی سازگاری
               نمای آداپتر، پیش از تغییر وضعیت مشترک.
            5. جایگزینی فقط توکن دسترسی همین حساب در ``SessionManager``.

        در شکست نوسازی، توکن ``SessionManager`` جایگزین نمی‌شود و وضعیت
        احرازشده دست‌نخورده می‌ماند. اگر پس از نوسازی موفق، همگام‌سازی
        نشست به‌دلیل یک خطای غیرمنتظره ممکن نشود، نگه‌داشتن حساب در وضعیت
        «واردشده» با سه نمای ناهماهنگ ناامن است: بنابراین آداپتر احرازشده
        **در هر صورت** و مستقل از موفقیتِ logout از دسترس سرویس خارج
        می‌شود، حساب از مسیر موجود logout از وضعیت واردشده خارج می‌گردد و
        خطا صریحاً به ورود مجدد اشاره می‌کند. اگر خود logout با خطا مواجه
        شود، از ``SessionManager.invalidate_session`` به‌عنوان مسیر
        اضطراریِ مستقل استفاده می‌شود تا نشست محلی همین حساب باطل شود و
        خطا صریح بگوید ورود مجدد لازم است. اگر ابطال اضطراری هم ممکن نشود،
        شکست صریحاً اعلام می‌شود و هیچ وضعیت امن‌سازی‌شده‌ای ادعا و هیچ
        توکن کهنه‌ای بازگردانده نمی‌شود؛ موفقیت کاذب هرگز اعلام نمی‌گردد.

        خروجی همیشه یک ``Session`` عمومی است و هرگز توکن در آن نیست.
        """
        # 1. رزولوشن حساب و بررسی سازگاری نشست با بروکر حساب.
        self._resolve_account(account_id)

        # 2. پیش‌نیازها، پیش از هر تماس با آداپتر یا درخواست HTTP.
        if not self._sessions.is_logged_in(account_id):
            raise AuthenticationServiceError(
                "این حساب در وضعیت واردشده نیست؛ نوسازی نشست مجاز نیست"
            )

        adapter = self._adapters.get(account_id)
        if adapter is None:
            raise AuthenticationServiceError(
                "آداپتر احرازشدهٔ این حساب موجود نیست؛ نوسازی نشست ممکن "
                "نیست"
            )

        if not adapter.is_authenticated():
            raise AuthenticationServiceError(
                "آداپتر این حساب احراز هویت نشده است؛ نوسازی نشست ممکن "
                "نیست"
            )

        # 3. فراخوانی قرارداد نوسازی روی آداپتر همین حساب. هر شکستی بدون
        #    هیچ تغییری به فراخواننده منتقل می‌شود.
        refreshed = adapter.refresh_authenticated_session()

        # 4. اعتبارسنجی نتیجهٔ برگشتی، پیش از تغییر وضعیت مشترک. سرویس
        #    فقط صورت‌بندی قرارداد را می‌سنجد (ساختار و سازگاری) و به نوع
        #    هیچ پیاده‌سازی بروکری وابسته نیست؛ از همین رو از ماژول
        #    احراز هویت چیزی import نمی‌کند.
        token = getattr(refreshed, "access_token", None)
        if not isinstance(token, str) or not token.strip():
            raise AuthenticationServiceError(
                "توکن نوسازی‌شدهٔ این حساب معتبر نیست"
            )

        current = adapter.get_authenticated_session()
        current_token = getattr(current, "access_token", None)
        if not isinstance(current_token, str) or current_token != token:
            raise AuthenticationServiceError(
                "نمای نشست آداپتر پس از نوسازی سازگار نیست"
            )

        # 5. جایگزینی فقط توکن دسترسی همین حساب در SessionManager.
        try:
            session = self._sessions.replace_token(account_id, token)
        except Exception:
            # بروکر و آداپتر همین حساب تازه شده‌اند، اما SessionManager نتوانست
            # توکن را جایگزین کند. نگه‌داشتن حساب در وضعیت «واردشده» با سه
            # نمای ناهماهنگ (توکن تازه‌ی بروکر/آداپتر و توکن کهنه‌ی نشست)
            # ناامن است؛ ضمن اینکه توکن قبلی پس از تمدید به‌احتمال زیاد در سمت
            # سرور دیگر معتبر نیست و نباید کورکورانه بازگردانده شود.
            #
            # آداپتر احرازشده **همیشه** و مستقل از موفقیتِ logout از دسترس
            # سرویس خارج می‌شود تا هیچ نمای احرازشده‌ای کهنه قابل دسترسی
            # نماند و حساب برای ادامه‌ی احراز/نوسازی یا ارسال سفارش قابل
            # استفاده تلقی نشود؛ سپس از مسیر موجود logout برای خروج از
            # وضعیت واردشده اقدام می‌شود. اگر این پاک‌سازی کامل نشود، شکست
            # صریحاً اعلام می‌شود و هیچ ادعای وضعیت امن‌سازی‌شده‌ای مطرح
            # نمی‌گردد.
            self._adapters.pop(account_id, None)
            try:
                self._sessions.logout(account_id)
            except Exception:
                # مسیر پاک‌سازی موجود شکست خورد. به‌عنوان مسیر اضطراریِ
                # مستقل، نشست محلی همین حساب مستقیماً باطل می‌شود.
                try:
                    self._sessions.invalidate_session(account_id)
                except Exception:
                    # حتی ابطال اضطراری هم ممکن نشد: هیچ ادعای امن‌شدن
                    # نمی‌شود و هیچ اطلاعات محرمانه‌ای افشا نمی‌گردد.
                    _raise_clean(
                        AuthenticationServiceError(
                            "نوسازی انجام شد اما همگام‌سازی توکن نشست این "
                            "حساب کامل نشد و ابطال اضطراری نشست محلی هم "
                            "ممکن نشد؛ وضعیت امن ادعا نمی‌شود و ورود "
                            "مجدد لازم است"
                        )
                    )
                _raise_clean(
                    AuthenticationServiceError(
                        "نوسازی انجام شد اما همگام‌سازی توکن نشست این "
                        "حساب کامل نشد؛ نشست محلی این حساب باطل شد و "
                        "ورود مجدد لازم است"
                    )
                )
            _raise_clean(
                AuthenticationServiceError(
                    "نوسازی انجام شد اما همگام‌سازی توکن نشست این حساب کامل "
                    "نشد؛ حساب از وضعیت واردشده خارج شد و به ورود مجدد نیاز "
                    "دارد"
                )
            )

        return session

    def is_logged_in(self, account_id: str) -> bool:
        """آیا این حساب در حال حاضر وارد شده است؟"""
        try:
            return self._sessions.is_logged_in(account_id)
        except SessionNotFoundError:
            return False

    def get_adapter(self, account_id: str) -> Optional["AuthenticationAdapter"]:
        """
        آداپتر احرازشده‌ی این حساب، یا None.

        فقط یک حسابِ واردشده آداپتر فعال دارد؛ بنابراین این متد None
        برمی‌گرداند تا زمانی که ورود کامل و تأییدشده باشد.
        """
        if not self.is_logged_in(account_id):
            return None
        return self._adapters.get(account_id)
