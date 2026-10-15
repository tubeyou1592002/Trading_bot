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
        ├── logout(account_id)                   -> None
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
    * ``logout(account_id)`` فقط وضعیت احراز هویت محلی همان حساب را پاک
      می‌کند و هرگز ادعای ابطال توکن در سمت کارگزاری ندارد؛ هیچ درخواست
      خروج اختصاصی به API کارگزاری وجود ندارد. موفقیت فقط وقتی اعلام
      می‌شود که جداسازی آداپتر انجام شده و وضعیت ``LOGGED_OUT`` بدون توکن
      محلی قابل تأیید باشد.
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

    def _install_recovery(self, account_id):
        """
        Install the account-scoped 401 recovery callback on this account's
        retained adapter through the generic authentication contract.

        The callback is a bound service method, so recovery flows through the
        existing adapter + AuthenticationService, never a direct broker token
        refresh. If the adapter does not support the hook, nothing is
        installed and a 401 fails closed (no unsynchronized refresh).

        Integration boundary (Stage 2C.1): the handler is installed on the
        account-owned broker reached through this account's adapter. That is
        the only broker instance on which Stage 2C.1 recovery is provided. It
        does NOT prove that the ``DispatchCore`` order path uses this same
        account-owned instance — the order path obtains its broker from
        ``BrokerManager`` (a separate instance). Account-aware routing is a
        separate task; no single mutable authenticated broker is shared across
        accounts to work around this.
        """
        adapter = self._adapters.get(account_id)
        if adapter is None:
            return

        def recovery_handler():
            self._recover_401(account_id)

        try:
            adapter.set_request_recovery_handler(recovery_handler)
        except Exception:
            # A failed installation must never crash a successful login/refresh;
            # the account simply falls back to fail-closed 401 handling.
            pass

    def _detach_account_authentication(self, adapter):
        """
        Best-effort, fail-safe removal of ONE account's retained authenticated
        state through the generic authentication contract.

        Detaches the 401 recovery handler and clears the adapter/broker's
        retained authenticated view so a failed recovery cannot leave a stale
        authenticated state usable on the account-owned broker instance. Never
        raises and never touches another account.
        """
        self._detach_account_authentication_checked(adapter)

    def _detach_account_authentication_checked(self, adapter) -> bool:
        """
        Same cleanup as ``_detach_account_authentication``, but REPORTS whether
        every step of the generic contract actually completed.

        Returns True only when the 401 recovery handler was detached,
        ``clear_authenticated_session()`` ran without raising, and the public
        adapter contract confirms ``is_authenticated() is False`` and
        ``get_authenticated_session() is None``. Missing or failing checks are
        treated as unconfirmed. Never raises and never touches another account.

        The generic contract declares ``clear_authenticated_session()`` as
        never-raising, but its postcondition is verified through the public
        authentication accessors. A False result means cleanup is unconfirmed
        and the caller must NOT report a confirmed clean logout.
        """
        if adapter is None:
            return True

        complete = True

        try:
            adapter.set_request_recovery_handler(None)
        except Exception:
            complete = False

        clear = getattr(adapter, "clear_authenticated_session", None)
        if callable(clear):
            try:
                clear()
            except Exception:
                complete = False
        else:
            complete = False

        is_authenticated = getattr(adapter, "is_authenticated", None)
        get_authenticated_session = getattr(
            adapter, "get_authenticated_session", None
        )
        if not callable(is_authenticated) or not callable(
            get_authenticated_session
        ):
            complete = False
        else:
            try:
                if is_authenticated() is not False:
                    complete = False
                if get_authenticated_session() is not None:
                    complete = False
            except Exception:
                complete = False

        return complete

    def _discard_pending_login(self, adapter) -> bool:
        """
        Best-effort release of ONE account's in-progress login attempt.

        A login attempt that was still open when the account is logged out must
        not be abandoned silently: its temporary adapter is removed from the
        service by the caller and any credentials it still holds are released
        here through the generic ``cancel_login()`` contract. A cancellation
        failure is reported to the caller as unsuccessful cleanup. Never raises.
        """
        if adapter is None:
            return True
        try:
            adapter.cancel_login()
        except Exception:
            return False
        return True

    def _session_is_logged_out(self, account_id):
        """
        True only when the account's LOCAL session is provably resolved to
        LOGGED_OUT with no SessionManager token. Never raises.
        """
        try:
            return (
                self._sessions.state(account_id) is SessionState.LOGGED_OUT
                and self._sessions.get_token(account_id) is None
            )
        except Exception:
            return False

    def _isolate_account(self, account_id, adapter):
        """
        Isolate exactly ONE account after a failed 401 recovery.

        Steps (each independent and fail-safe):

            1. Detach the recovery handler and clear the retained
               authenticated state on the account-owned adapter/broker.
            2. Remove the adapter from the service so it is unreachable.
            3. Resolve the local session to LOGGED_OUT via the existing
               ``logout`` path, falling back to the independent emergency
               ``invalidate_session``.
            4. VERIFY the resulting state is LOGGED_OUT with no token.

        Returns True ONLY when the safe local state is confirmed; False when it
        could not be confirmed, in which case the caller must NOT claim the
        session was invalidated. No other account is touched.
        """
        self._detach_account_authentication(adapter)
        self._adapters.pop(account_id, None)

        if self._session_is_logged_out(account_id):
            return True

        try:
            self._sessions.logout(account_id)
        except Exception:
            try:
                self._sessions.invalidate_session(account_id)
            except Exception:
                return False

        return self._session_is_logged_out(account_id)

    def _recover_401(self, account_id):
        """
        Account-scoped HTTP 401 recovery.

        Refresh the authenticated session through the retained adapter (so the
        broker, the adapter and the SessionManager stay consistent) and replace
        only this account's token. On any failure the affected account is
        isolated: its recovery handler is detached, its retained authenticated
        state is cleared, its adapter becomes unreachable, and its local
        session is resolved to LOGGED_OUT before any claim of successful
        invalidation is made. When that safe state cannot be CONFIRMED, a
        sanitized error states explicitly that the safe state is unconfirmed.
        No other account is touched and no token is exposed through the error.

        Integration boundary (Stage 2C.1, documented, not solved here)
        --------------------------------------------------------------
        This recovery runs against the account-owned broker instance that has
        this account's handler installed. It does not, by itself, prove that
        the current ``DispatchCore`` order path is wired to that account-owned
        instance (the order path obtains its broker from ``BrokerManager``,
        a different instance). Full account-aware routing is a separate task.
        """
        _UNCONFIRMED_PREFIX = (
            "وضعیت امن این حساب تأیید نشد؛ "
        )

        adapter = self._adapters.get(account_id)
        if adapter is None or not adapter.is_authenticated():
            resolved = self._isolate_account(account_id, adapter)
            if not resolved:
                _raise_clean(
                    AuthenticationServiceError(
                        _UNCONFIRMED_PREFIX
                        + "نوسازی نشست ممکن نبود و ابطال ایمن نشست محلی "
                        "هم تأیید نشد؛ ورود مجدد لازم است"
                    )
                )
            _raise_clean(
                AuthenticationServiceError(
                    "نوسازی نشست ممکن نبود؛ نشست این حساب باطل شد و ورود "
                    "مجدد لازم است"
                )
            )

        try:
            refreshed = adapter.refresh_authenticated_session()
        except Exception:
            resolved = self._isolate_account(account_id, adapter)
            if not resolved:
                _raise_clean(
                    AuthenticationServiceError(
                        _UNCONFIRMED_PREFIX
                        + "نوسازی توکن ناموفق بود و ابطال ایمن نشست محلی "
                        "هم تأیید نشد؛ ورود مجدد لازم است"
                    )
                )
            _raise_clean(
                AuthenticationServiceError(
                    "نوسازی توکن ناموفق بود؛ نشست این حساب باطل شد و ورود "
                    "مجدد لازم است"
                )
            )

        token = getattr(refreshed, "access_token", None)
        if not isinstance(token, str) or not token.strip():
            resolved = self._isolate_account(account_id, adapter)
            if not resolved:
                _raise_clean(
                    AuthenticationServiceError(
                        _UNCONFIRMED_PREFIX
                        + "توکن نوسازی‌شده معتبر نبود و ابطال ایمن نشست "
                        "محلی هم تأیید نشد؛ ورود مجدد لازم است"
                    )
                )
            _raise_clean(
                AuthenticationServiceError(
                    "توکن نوسازی‌شده معتبر نبود؛ نشست این حساب باطل شد و "
                    "ورود مجدد لازم است"
                )
            )

        current = adapter.get_authenticated_session()
        current_token = getattr(current, "access_token", None)
        if not isinstance(current_token, str) or current_token != token:
            resolved = self._isolate_account(account_id, adapter)
            if not resolved:
                _raise_clean(
                    AuthenticationServiceError(
                        _UNCONFIRMED_PREFIX
                        + "نمای نشست آداپتر پس از نوسازی سازگار نبود و "
                        "ابطال ایمن نشست محلی هم تأیید نشد؛ ورود مجدد "
                        "لازم است"
                    )
                )
            _raise_clean(
                AuthenticationServiceError(
                    "نمای نشست آداپتر پس از نوسازی سازگار نبود؛ نشست این "
                    "حساب باطل شد و ورود مجدد لازم است"
                )
            )

        try:
            self._sessions.replace_token(account_id, token)
        except Exception:
            resolved = self._isolate_account(account_id, adapter)
            if not resolved:
                _raise_clean(
                    AuthenticationServiceError(
                        _UNCONFIRMED_PREFIX
                        + "همگام‌سازی توکن نشست کامل نشد و ابطال ایمن نشست "
                        "محلی هم تأیید نشد؛ ورود مجدد لازم است"
                    )
                )
            _raise_clean(
                AuthenticationServiceError(
                    "همگام‌سازی توکن نشست کامل نشد؛ نشست این حساب باطل شد "
                    "و ورود مجدد لازم است"
                )
            )

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
        self._install_recovery(account_id)
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
            try:
                self._install_recovery(account_id)
            except Exception:
                pass
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

    def logout(self, account_id: str) -> None:
        """
        خروج امن و مستقلِ یک حساب.

        این متد **فقط** وضعیت احراز هویت محلی همان حساب را پاک می‌کند و
        هرگز ادعا نمی‌کند توکن صادرشده در سمت کارگزاری از راه دور باطل شده
        است: هیچ درخواست خروج اختصاصی به API کارگزاری وجود ندارد و رفتار
        تأییدنشده‌ای هم حدس زده نمی‌شود.

        ترتیب کار (به‌همین ترتیب اهمیت امنیتی دارد):

            1. رزولوشن حساب و بررسی سازگاری نشست با بروکر حساب
               (fail-closed). حساب ناشناخته یا نشست ناسازگار **پیش از هر
               پاک‌سازی** رد می‌شود تا هیچ حساب یا بروکری حدس زده نشود.
            2. قطع دسترسی سرویس به آداپترهای همین حساب، مستقل از موفقیت یا
               شکست عملیات خروج در ``SessionManager``.
            3. مدیریت صریح تلاش ورودِ در حال انجام: آداپتر موقت از سرویس
               خارج و اعتبارنه‌ی باقیمانده‌اش آزاد می‌شود.
            4. جدا کردن handler بازیابی 401 و پاک‌سازی وضعیت احراز هویت از
               طریق قرارداد عمومی ``clear_authenticated_session()``.
            5. اجرای ``SessionManager.logout()`` و در صورت شکست، تلاش برای
               ``SessionManager.invalidate_session()`` به‌عنوان مسیر اضطراری.
            6. **بررسی** وضعیت نهایی: فقط وقتی ``LOGGED_OUT`` بودن و نبود
               توکن محلی قابل تأیید باشد، خروج موفق اعلام می‌شود.

        اگر پاک‌سازی آداپتر یا قطع handler شکست بخورد، صرفِ موفقیت خروج محلی
        برای اعلام موفقیت کامل کافی نیست و خطای پاک‌سازی‌شده صادر می‌شود.
        خروج از حسابی که از قبل خارج شده، تکرارپذیر و بی‌اثر است و خطا نمی‌دهد
        (قرارداد ``SessionManager`` تغییر نمی‌کند). هیچ حساب دیگری دست نمی‌خورد
        و متن خطا هرگز رمز عبور یا توکن را افشا نمی‌کند.
        """
        _UNCONFIRMED_PREFIX = "وضعیت امن این حساب تأیید نشد؛ "

        # 1. Fail-closed: an unknown account or a session that disagrees with
        #    the account's broker is rejected BEFORE anything is detached or
        #    cleared, so no account and no replacement broker is ever guessed.
        self._resolve_account(account_id)

        # 2. Cut the service's own access to this account's adapters first and
        #    unconditionally — this must not depend on SessionManager succeeding.
        current_state = self._sessions.state(account_id)
        adapter = self._adapters.pop(account_id, None)
        pending = self._pending_logins.pop(account_id, None)

        # A live session without its matching service-owned adapter cannot be
        # proven clean. Still attempt local logout below, but never report full
        # success because no adapter is available to clear and verify.
        cleanup_complete = not (
            (current_state is SessionState.LOGGED_IN and adapter is None)
            or (current_state is SessionState.LOGIN_PENDING and pending is None)
        )

        # 3. An open login attempt is handled explicitly: it is detached,
        #    removed from the service and its temporary credentials released,
        #    so nothing in-progress is left silently behind.
        if pending is not None:
            cleanup_complete = (
                self._detach_account_authentication_checked(pending)
                and cleanup_complete
            )
            cleanup_complete = (
                self._discard_pending_login(pending)
                and cleanup_complete
            )

        # 4. Detach the 401 recovery handler and clear the retained
        #    authenticated state through the generic contract. A contract
        #    violation here means "not clean", even if local logout succeeds.
        if adapter is not None:
            cleanup_complete = (
                self._detach_account_authentication_checked(adapter)
                and cleanup_complete
            )

        # 5. Resolve the local session to LOGGED_OUT through the existing
        #    logout path, with the independent emergency fallback.
        if not self._session_is_logged_out(account_id):
            try:
                self._sessions.logout(account_id)
            except Exception:
                try:
                    self._sessions.invalidate_session(account_id)
                except Exception:
                    cleanup_complete = False

        # 6. Verify. Success is claimed only when the adapter cleanup completed
        #    AND the safe local state is provable; otherwise the caller is told
        #    explicitly that no confirmed logout happened.
        resolved = self._session_is_logged_out(account_id)
        if not (cleanup_complete and resolved):
            _raise_clean(
                AuthenticationServiceError(
                    _UNCONFIRMED_PREFIX
                    + "خروج این حساب کامل نشد؛ ورود مجدد لازم است"
                )
            )

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
