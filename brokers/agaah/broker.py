import base64
import logging
import math
import threading
from typing import TYPE_CHECKING, Optional

import requests

from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.order import Order
from models.trading_state import (
    CETAVAL_ALLOWED,
    CETAVAL_BLOCKED,
    UNVERIFIED,
    TradingState,
    TradingStateUnavailable,
    market_status_from_code,
)
from market.tsetmc import TSETMC

from ..base import Broker
from ..device_info import ExternalDeviceInfoProvider

if TYPE_CHECKING:
    from .nats_transport import AgahQueuePositionService
    from .queue_position import AgahQueuePositionProvider


BASE_URL = "https://tseonlineapi.agah.com/api/v1"
ORIGIN = "https://online.agah.com"
REFERER = "https://online.agah.com/"

CLIENT_KEY = "634e0572-a4a3-4fd6-b033-82211dba74f1"


class PreparedOrderSender:
    """One-shot order sender backed by a transport private to this sender."""

    def __init__(self, *, owner, account_id, user_identifier, access_token,
                 transport):
        self._owner = owner
        self._account_id = account_id
        self._user_identifier = user_identifier
        self._access_token = access_token
        self._transport = transport
        self._lock = threading.Lock()
        self._used = False
        self._closed = False

    @property
    def owner(self):
        return self._owner

    @property
    def account_id(self):
        return self._account_id

    def _submit_once(self, payload):
        with self._lock:
            if self._closed:
                raise RuntimeError("Prepared sender is closed")
            if self._used:
                raise RuntimeError("Prepared sender is single-use")
            self._used = True
            transport = self._transport
            headers = {
                "Authorization": f"Bearer {self._access_token}",
                "UserIdentifier": self._user_identifier,
            }
            # Keep close() from closing an in-flight transport. This lock is
            # per sender; separate senders never contend or share a Session.
            response = transport.post(
                self._owner._url("order"), headers=headers, json=payload,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            if not data.get("isSuccess"):
                raise RuntimeError(data.get("message", "ارسال سفارش ناموفق بود."))
            return data

    def _close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            transport, self._transport = self._transport, None
            self._access_token = None
            self._user_identifier = None
        close = getattr(transport, "close", None)
        if callable(close):
            close()


class AsyncPreparedOrderTransport:
    """Account-private aiohttp session shared safely by scheduled ticket tasks."""

    def __init__(self, *, owner, account_id, user_identifier, access_token,
                 session):
        self._owner = owner
        self._account_id = account_id
        self._user_identifier = user_identifier
        self._access_token = access_token
        self._session = session
        self._closed = False
        self._used_ticket_ids = set()
        self._used_lock = threading.Lock()
        self.supports_post_start_callback = True

    @property
    def account_id(self):
        return self._account_id

    async def submit(self, payload, *, on_post_start=None):
        if self._closed:
            raise RuntimeError("Prepared transport is closed")
        if not self._owner.live_trading_enabled:
            raise RuntimeError(
                "ارسال زنده سفارش غیرفعال است. live_trading_enabled=False"
            )
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "UserIdentifier": self._user_identifier,
        }
        if callable(on_post_start):
            on_post_start()
        async with self._session.post(
            self._owner._url("order"), headers=headers, json=payload,
            timeout=10,
        ) as response:
            response.raise_for_status()
            data = await response.json()
        if not data.get("isSuccess"):
            raise RuntimeError(data.get("message", "ارسال سفارش ناموفق بود."))
        return data

    async def close(self):
        if self._closed:
            return
        self._closed = True
        session, self._session = self._session, None
        self._access_token = None
        self._user_identifier = None
        await session.close()

    async def submit_ticket(self, ticket, authorization, broker, payload=None,
                            on_post_start=None):
        from core.live_order_authorization import LiveBatchAuthorization
        from core.live_order_authorization import ScheduleTicketLedger
        ledger = getattr(authorization, "ticket_ledger", None)
        prepared = getattr(ticket, "prepared_order", None)
        if (not isinstance(authorization, LiveBatchAuthorization)
                or ticket.authorization_id != authorization.authorization_id
                or ticket.execution_id != authorization.snapshot.execution_id
                or ticket.account_id != getattr(prepared, "account_id", None)
                or ticket.broker_name != getattr(prepared, "broker_name", None)
                or getattr(prepared, "broker_identity", None) != id(self)
                or ticket.payload_json != getattr(prepared, "payload_json", None)
                or not isinstance(ledger, ScheduleTicketLedger)
                or (reserved := ledger._reserved.get(ticket.ticket_id)) is None
                or reserved.execution_id != ticket.execution_id
                or reserved.account_id != ticket.account_id
                or reserved.broker_name != ticket.broker_name
                or reserved.turn_index != ticket.turn_index
                or reserved.payload_json != ticket.payload_json
                or reserved.prepared_fingerprint != ticket.prepared_fingerprint
                or broker is not self):
            raise RuntimeError("ticket payload or destination binding is invalid")
        body = ticket.payload if payload is None else payload
        with self._used_lock:
            if ticket.ticket_id in self._used_ticket_ids:
                raise RuntimeError("Scheduled ticket is single-use")
            self._used_ticket_ids.add(ticket.ticket_id)
        return await self.submit(body, on_post_start=on_post_start)


class AgaahBroker(Broker):

    def __init__(self):
        self.session = requests.Session()

        self.device_info_provider = (
            ExternalDeviceInfoProvider()
        )

        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/151.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Origin": ORIGIN,
            "Referer": REFERER,
        })

        self.access_token = None
        self.refresh_token = None
        self.user_identifier = None
        self.username = None

        # 401 recovery support (Stage 2C.1)
        self._unauthorized_recovery = None
        self._token_lock = threading.Lock()
        # Prepared order senders own independent HTTP sessions. They are
        # deliberately created only through this broker so authentication
        # material never crosses the broker boundary.
        self._prepared_senders = set()
        self._async_prepared_transports = set()
        self._prepared_sender_lock = threading.Lock()
        self._account_id = None

        # ---------------------------------------------
        # Safety
        # ---------------------------------------------
        # False = هیچ POST /order ارسال نمی‌شود.
        self.live_trading_enabled = False

        # Queue position provider (Stage 2) - lazy init to avoid circular import
        self._queue_position_provider: Optional["AgahQueuePositionProvider"] = None

        # Listener lists for feedback/queue-position tracking (Stage 3 bridge)
        self._order_registered_listeners = []
        self._queue_position_listeners = []
        self._order_error_listeners = []
        self._feedback_unavailable_listeners = []

        self._logger = logging.getLogger(__name__)

    @property
    def name(self):
        return "آگاه"

    # =================================================
    # Trading State
    # =================================================

    def get_trading_state(
        self,
        nsc_id: str,
    ) -> TradingState:
        """
        وضعیت معاملاتی نماد از TSETMC.

        بر اساس Decision 020، منبع وضعیت معاملاتی
        TSETMC است و فیلد `cEtaval` مبنای Mapping است.

        نحوه کار:
        1. nsc_id از طریق broker.get_instrument(nsc_id)
           به BrokerInstrument تبدیل می‌شود.
        2. tse_id آن (که برابر TSETMC ins_code است)
           برای درخواست به TSETMC استفاده می‌شود.
        3. لیست وضعیت‌ها از TSETMC دریافت می‌شود؛
           آخرین وضعیت (بیشترین dEven و hEven) انتخاب می‌شود.
        4. identity بررسی می‌شود: insCode پاسخ باید با
           ins_code درخواستی تطبیق داشته باشد.
        5. cEtaval مطابق Decision 020 نگاشت می‌شود.

        وضعیت‌های `A ` و `AR` اجازه ارسال سفارش دارند.
        سایر وضعیت‌ها و هر وضعیت ناشناخته/خطا باعث
        Block شدن می‌شوند.

        Contract:
        - موفقیت (منبع معتبر موجود و پاسخ‌دهی می‌کند) → ``TradingState``
          با ``is_verified=True`` یا ``is_verified=False`` (منبع موجود ولی
          وضعیت ناشناخته/مجاز نیست).
        - منبع واقعی وضعیت معاملاتی در دسترس نیست (خطای شبکه،
          قطعی سرویس، پاسخ نامعتبر، timeout) → پرتاب
          ``TradingStateUnavailable``.
        - Programming errors (``TypeError``، ``AttributeError``،
          ``NotImplementedError``، ...) → **propagate**.
        """

        if not nsc_id:
            raise ValueError(
                "nsc_id نمی‌تواند خالی باشد."
            )

        try:
            broker_instrument = self.get_instrument(nsc_id)
        except requests.RequestException as exc:
            raise TradingStateUnavailable(
                f"Failed to resolve instrument for nsc_id={nsc_id}: {exc}"
            ) from exc

        ins_code = getattr(broker_instrument, "tse_id", None)

        if not ins_code:
            return UNVERIFIED

        tsetmc = TSETMC()

        try:
            states = tsetmc.get_trading_state(ins_code)
        except requests.RequestException as exc:
            raise TradingStateUnavailable(
                f"Failed to get trading state for ins_code={ins_code}: {exc}"
            ) from exc

        if not isinstance(states, list) or not states:
            return UNVERIFIED

        # Filter to states matching our ins_code (identity verification)
        matching = [
            s for s in states
            if isinstance(s, dict)
            and str(s.get("insCode")) == str(ins_code)
        ]

        if not matching:
            return UNVERIFIED

        # Select latest state (highest dEven, then hEven)
        latest = max(
            matching,
            key=lambda s: (
                s.get("dEven", 0),
                s.get("hEven", 0),
            ),
        )

        c_etaval = latest.get("cEtaval") if isinstance(
            latest, dict
        ) else None

        c_etaval = (
            c_etaval.strip()
            if isinstance(c_etaval, str)
            else c_etaval
        )

        c_etaval_title = latest.get("cEtavalTitle")
        c_etaval_title = (
            c_etaval_title.strip()
            if isinstance(c_etaval_title, str)
            and c_etaval_title.strip()
            else None
        )

        market_status = market_status_from_code(c_etaval)

        if c_etaval in CETAVAL_ALLOWED:
            return TradingState(
                is_order_entry_allowed=True,
                is_verified=True,
                source="tsetmc:cEtaval",
                reason=f"cEtaval={c_etaval}",
                market_status=market_status,
                market_status_title=c_etaval_title,
            )

        if c_etaval in CETAVAL_BLOCKED:
            return TradingState(
                is_order_entry_allowed=False,
                is_verified=True,
                source="tsetmc:cEtaval",
                reason=f"cEtaval={c_etaval}",
                market_status=market_status,
                market_status_title=c_etaval_title,
            )

        return TradingState(
            is_order_entry_allowed=False,
            is_verified=False,
            source="tsetmc:cEtaval",
            reason=(
                f"cEtaval ناشناخته: "
                f"({c_etaval!r})"
            ),
            market_status=market_status,
            market_status_title=c_etaval_title,
        )

    # =================================================
    # Helpers
    # =================================================

    def _url(self, path: str) -> str:
        return f"{BASE_URL}/{path.lstrip('/')}"

    def set_unauthorized_recovery(self, handler):
        """
        Install (or, with ``None``, detach) the generic account-scoped HTTP 401
        recovery callback for THIS broker instance.

        Integration boundary (Stage 2C.1, documented, not solved here)
        --------------------------------------------------------------
        Stage 2C.1 guarantees recovery only on the broker instance that has
        this account-specific handler installed — the account-owned broker
        created by the account's authentication adapter. It does NOT, by
        itself, prove that the current order path (``DispatchCore``) is wired
        to that account-owned instance: the order path currently obtains its
        broker from ``BrokerManager``, which is a different broker instance.
        Sharing one mutable authenticated broker across accounts is explicitly
        NOT the solution, and changing the order path is out of scope for this
        task. Full account-aware routing — making the order path use the same
        account-owned broker on which the 401 handler lives — remains a
        separate task.
        """
        self._unauthorized_recovery = handler

    def _authed_get_with_recovery(self, path, params=None):
        """
        Perform an authenticated read-only GET with bounded HTTP 401 recovery.

        - The actual HTTP status code is inspected BEFORE ``raise_for_status()``
          so only a real 401 triggers recovery.
        - The exact access token represented by the Authorization header of the
          original request is captured BEFORE the request is sent. Reading it
          again after the response would be racy: a concurrent request may
          already have refreshed the token while this request was in flight.
        - Recovery is delegated to the installed account-scoped callback (which
          synchronizes broker + adapter + SessionManager); this helper never
          calls ``refresh_tokens()`` directly.
        - The original GET is retried at most once with the refreshed token.
          A second 401 fails closed with no further retry or refresh.
        - With no recovery callback installed the HTTP failure is surfaced
          unchanged (fail closed; no unsynchronized refresh).
        - The per-instance lock deduplicates concurrent refreshes: a request
          refreshes only if the broker still holds the SAME token that this
          request was authorized with. If a concurrent request already replaced
          it, this request reuses the replaced token instead of refreshing
          again (exactly one refresh for overlapping 401s on one account).
        """
        # Capture the token that will actually authorize this request, then
        # build the header from THAT captured value, so the value compared
        # under the lock is provably the one the 401 applies to.
        failed_token = self.access_token
        headers = self._auth_headers_for(failed_token)
        response = self.session.get(
            self._url(path),
            params=params,
            headers=headers,
            timeout=10,
        )

        if getattr(response, "status_code", None) != 401:
            response.raise_for_status()
            return response

        # A real HTTP 401 was received.
        handler = self._unauthorized_recovery

        if handler is None:
            # Fail closed: surface the HTTP failure without an unsynchronized
            # token refresh.
            response.raise_for_status()
            raise RuntimeError("درخواست ناموفق بود.")

        with self._token_lock:
            if self.access_token == failed_token:
                # This request performs the single, account-scoped refresh for
                # the token it was actually authorized with.
                handler()
            # Otherwise another in-flight request already replaced the token;
            # reuse it instead of refreshing again.

        headers = self._auth_headers()
        response = self.session.get(
            self._url(path),
            params=params,
            headers=headers,
            timeout=10,
        )

        if getattr(response, "status_code", None) == 401:
            # The retry was rejected as well: no loop, no extra refresh.
            response.raise_for_status()
            raise RuntimeError("درخواست ناموفق بود.")

        response.raise_for_status()
        return response

    def _auth_headers(self):
        return self._auth_headers_for(self.access_token)

    def _auth_headers_for(self, access_token):
        if not access_token:
            raise RuntimeError(
                "کاربر به آگاه وارد نشده است."
            )

        if not self.user_identifier:
            raise RuntimeError(
                "UserIdentifier موجود نیست."
            )

        return {
            "Authorization": f"Bearer {access_token}",
            "UserIdentifier": self.user_identifier,
        }

    # =================================================
    # Captcha
    # =================================================

    def get_captcha(self):
        """
        دریافت کپچا از آگاه.
        """

        response = self.session.get(
            self._url("captcha/getcaptcha"),
            timeout=10,
        )

        response.raise_for_status()

        data = response.json()

        if not data.get("isSuccess"):
            raise RuntimeError(
                data.get(
                    "message",
                    "دریافت کپچا ناموفق بود."
                )
            )

        captcha_data = data.get("data")

        if not captcha_data:
            raise RuntimeError(
                "پاسخ کپچا فاقد data است."
            )

        captcha_id = captcha_data.get("captchaId")
        captcha = captcha_data.get("captcha")

        if not captcha_id or not captcha:
            raise RuntimeError(
                "captchaId یا captcha در پاسخ وجود ندارد."
            )

        return {
            "captchaId": captcha_id,
            "captcha": captcha,
        }

    def save_captcha_image(
        self,
        captcha_data,
        file_path="captcha.png",
    ):
        """
        تبدیل Base64 کپچا به فایل تصویر.
        """

        captcha_base64 = captcha_data.get("captcha")

        if not captcha_base64:
            raise ValueError(
                "اطلاعات Base64 کپچا موجود نیست."
            )

        try:
            image_bytes = base64.b64decode(
                captcha_base64
            )
        except Exception as exc:
            raise ValueError(
                "Base64 کپچا معتبر نیست."
            ) from exc

        with open(file_path, "wb") as file:
            file.write(image_bytes)

        return file_path

    # =================================================
    # Login
    # =================================================

    def login(
        self,
        username,
        password,
        captcha,
        captcha_id,
        device_info=None,
    ):
        """
        ورود به حساب آگاه.
        """

        if device_info is None:
            device_info = (
                self.device_info_provider.get()
            )

        payload = {
            "userName": username,
            "password": password,
            "captcha": captcha,
            "captchaId": captcha_id,
            "clientKey": CLIENT_KEY,
            "deviceInfo": device_info,
        }

        response = self.session.post(
            self._url("users/authenticate"),
            json=payload,
            timeout=10,
        )

        response.raise_for_status()

        data = response.json()

        if not data.get("isSuccess"):
            message = data.get(
                "message",
                "ورود به آگاه ناموفق بود."
            )

            error_code = data.get("errorCode")

            details = []

            if message:
                details.append(
                    f"message={message}"
                )

            if error_code:
                details.append(
                    f"errorCode={error_code}"
                )

            error_data = data.get("data")

            if isinstance(error_data, dict):
                for key in (
                    "message",
                    "errorCode",
                    "errors",
                ):
                    value = error_data.get(key)

                    if value:
                        details.append(
                            f"{key}={value}"
                        )

            if not details:
                details.append(
                    "پاسخ ناموفق بدون جزئیات دریافت شد."
                )

            raise RuntimeError(
                " | ".join(details)
            )

        auth_data = data.get("data")

        if not isinstance(auth_data, dict):
            raise RuntimeError(
                "پاسخ ورود فاقد data معتبر است."
            )

        access_token = auth_data.get(
            "accessToken"
        )

        refresh_token = auth_data.get(
            "refreshToken"
        )

        user_identifier = auth_data.get(
            "userIdentifier"
        )

        if not access_token:
            raise RuntimeError(
                "accessToken در پاسخ ورود وجود ندارد."
            )

        if not user_identifier:
            raise RuntimeError(
                "userIdentifier در پاسخ ورود وجود ندارد."
            )

        self.access_token = access_token
        self.refresh_token = refresh_token
        self.user_identifier = user_identifier
        self.username = username

        return {
            "userName": auth_data.get(
                "userName",
                username,
            ),
            "userIdentifier": user_identifier,
            "hasRefreshToken": bool(
                refresh_token
            ),
        }

    # =================================================
    # Token Refresh
    # =================================================
    # POST /api/v1/users/refresh-token
    #
    # Confirmed client behavior (Block 9, Task 5, Stage 1 audit):
    #   request JSON: {"accessToken": <current>, "refreshToken": <current>}
    #   success response: isSuccess=true and
    #       data.accessToken / data.refreshToken are the replacement tokens.
    #
    # این متد فقط «primitives» نوسازی توکن است: هیچ interception خودکار
    # 401، هیچ retry، هیچ ذخیره‌سازی و هیچ ادغامی با SessionManager یا UI
    # ندارد. پیش از ارسال درخواست، وجود هر دو توکن فعلی الزامی است؛ هر دو
    # توکن جایگزین پیش از تغییر وضعیت در متغیرهای محلی اعتبارسنجی می‌شوند
    # و تنها پس از اعتبارسنجی کامل با هم جایگزین می‌گردند؛ بنابراین هر خطا
    # جفت توکن اصلی را دست‌نخورده باقی می‌گذارد.
    #
    # امنیت: هیچ مقدار توکن، بدنه پاسخ یا زمینه‌ی استثنای حساس در پیام خطا
    # یا خروجی تشخیصی افشا نمی‌شود.

    @staticmethod
    def _raise_clean(error):
        """
        پرتاب یک خطای پاک‌سازی‌شده بدون زنجیره‌ی استثنای محرمانه.

        حتی وقتی متد از داخل یک بلوک ``except`` بیرونی صدا زده شود،
        ``__context__``/``__cause__`` پاک می‌مانند تا هیچ استثنای حاوی
        توکن در زنجیره باقی نماند.
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

    def refresh_tokens(self):
        """
        نوسازی توکن دسترسی و توکن تازه‌سازی آگاه.

        Endpoint: ``POST /api/v1/users/refresh-token``
        Request JSON: ``{"accessToken": ..., "refreshToken": ...}``
        Response: ``isSuccess=true`` و ``data.accessToken`` /
        ``data.refreshToken`` به‌عنوان مقادیر جایگزین.

        - پیش از درخواست، وجود هر دو توکن فعلی بررسی می‌شود؛ در غیر این
          صورت هیچ درخواستی ارسال نمی‌شود.
        - در صورت موفقیت، هر دو توکن با هم جایگزین می‌شوند.
        - در صورت هر خطای HTTP / شبکه / پاسخ ناقص یا نامعتبر، هر دو توکن
          اصلی بدون تغییر باقی می‌مانند و یک خطای پاک‌سازی‌شده پرتاب
          می‌شود که هیچ توکنی را افشا نمی‌کند.
        - توکن‌ها فقط در حافظه نگه داشته می‌شوند.
        """

        current_access = self.access_token
        current_refresh = self.refresh_token

        if not isinstance(current_access, str) or not current_access.strip():
            self._raise_clean(
                RuntimeError(
                    "توکن دسترسی فعلی در دسترس نیست؛ "
                    "نوسازی توکن انجام نشد."
                )
            )

        if not isinstance(current_refresh, str) or not current_refresh.strip():
            self._raise_clean(
                RuntimeError(
                    "توکن تازه‌سازی فعلی در دسترس نیست؛ "
                    "نوسازی توکن انجام نشد."
                )
            )

        error = None
        data = None

        try:
            response = self.session.post(
                self._url("users/refresh-token"),
                json={
                    "accessToken": current_access,
                    "refreshToken": current_refresh,
                },
                timeout=10,
            )

            response.raise_for_status()

            data = response.json()
        except Exception as exc:
            error = exc

        if error is not None:
            self._raise_clean(
                RuntimeError(
                    "درخواست نوسازی توکن آگاه ناموفق بود."
                )
            )

        if not isinstance(data, dict) or data.get("isSuccess") is not True:
            self._raise_clean(
                RuntimeError(
                    "پاسخ نوسازی توکن آگاه ناموفق بود."
                )
            )

        payload = data.get("data")

        if not isinstance(payload, dict):
            self._raise_clean(
                RuntimeError(
                    "پاسخ نوسازی توکن آگاه فاقد data معتبر است."
                )
            )

        new_access = payload.get("accessToken")
        new_refresh = payload.get("refreshToken")

        if not isinstance(new_access, str) or not new_access.strip():
            self._raise_clean(
                RuntimeError(
                    "accessToken جایگزین در پاسخ نوسازی "
                    "معتبر نیست."
                )
            )

        if not isinstance(new_refresh, str) or not new_refresh.strip():
            self._raise_clean(
                RuntimeError(
                    "refreshToken جایگزین در پاسخ نوسازی "
                    "معتبر نیست."
                )
            )

        self.access_token = new_access
        self.refresh_token = new_refresh

    # =================================================
    # BUY Capacity
    # =================================================
    # GET /api/v1/trades/calculatedquantity

    def get_buy_capacity(
        self,
        nsc_id: str,
        side_code: int,
        fund,
        price: int,
    ) -> int:
        """
        دریافت حداکثر تعداد خرید (ظرفیت) از API آگاه.

        Endpoint: GET /api/v1/trades/calculatedquantity
        Parameters: nscId, sideCode, fund, price
        Response: data = calculated BUY capacity (int)

        هر خطای HTTP / شبکه / پاسخ نامعتبر باعث
        پرتاب استثنا می‌شود تا موتور سفارش سفارش را
        بلاک کند.
        """

        if not nsc_id:
            raise ValueError(
                "nsc_id نمی‌تواند خالی باشد."
            )

        response = self._authed_get_with_recovery(
            "trades/calculatedquantity",
            params={
                "nscId": nsc_id,
                "sideCode": side_code,
                "fund": fund,
                "price": price,
            },
        )

        data = response.json()

        if not data.get("isSuccess", True):
            raise RuntimeError(
                data.get(
                    "message",
                    "درخواست ظرفیت خرید ناموفق بود."
                )
            )

        capacity = data.get("data")

        if capacity is None:
            raise RuntimeError(
                "پاسخ ظرفیت خرید فاقد data است."
            )

        if isinstance(capacity, bool) or not isinstance(
            capacity, (int, float)
        ):
            raise RuntimeError(
                "data پاسخ ظرفیت خرید عددی نیست."
            )

        if capacity < 0:
            raise RuntimeError(
                "ظرفیت خرید منفی است."
            )

        return int(capacity)

    def get_commission_info(self, nsc_id: str, price: int, quantity: int, side_code: int):
        """Return validated commissioninfo payload for a read-only preview."""
        if not nsc_id:
            raise ValueError("nsc_id نمی‌تواند خالی باشد.")
        for name, value in (("price", price), ("quantity", quantity),
                            ("side_code", side_code)):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} باید عدد صحیح و مثبت باشد.")
        response = self._authed_get_with_recovery(
            "trades/commissioninfo",
            params={"nscId": nsc_id, "price": price,
                    "quantity": quantity, "sideCode": side_code},
        ).json()
        if not isinstance(response, dict) or response.get("isSuccess") is not True:
            raise RuntimeError("دریافت اطلاعات کارمزد ناموفق بود.")
        data = response.get("data")
        commission = data.get("commissionSum") if isinstance(data, dict) else None
        if isinstance(commission, bool) or not isinstance(commission, int) or commission < 0:
            raise RuntimeError("commissionSum پاسخ آگاه معتبر نیست.")
        return data

    # =================================================
    # SELL Capacity (Portfolio Quantity)
    # =================================================
    # GET /api/v1/portfolio
    #
    # M6-D contract (Architect-approved):
    #   endpoint: GET /api/v1/portfolio
    #   quantity field: portfolio.numberOfShares
    #   SELL rule: requested quantity <= numberOfShares
    #   missing/invalid/API failure -> raise (fail-closed)
    #
    # NOTE: numberOfShares is used only as the
    # sellable quantity bound. It is NOT claimed to be
    # an independent "sellable quantity".

    def get_sell_capacity(
        self,
        nsc_id: str,
        side_code: int,
        fund,
        price: int,
    ) -> int:
        """
        دریافت حداکثر تعداد قابل‌فروش (ظرفیت) از API
        آگاه.

        Endpoint: GET /api/v1/portfolio
        Response: portfolio.numberOfShares

        هر خطای HTTP / شبکه / پاسخ نامعتبر باعث
        پرتاب استثنا می‌شود تا موتور سفارش سفارش را
        بلاک کند.
        """

        if not nsc_id:
            raise ValueError(
                "nsc_id نمی‌تواند خالی باشد."
            )

        response = self._authed_get_with_recovery(
            "portfolio",
            params={
                "nscId": nsc_id,
                "sideCode": side_code,
                "fund": fund,
                "price": price,
            },
        )

        data = response.json()

        if not data.get("isSuccess", True):
            raise RuntimeError(
                data.get(
                    "message",
                    "دریافت ظرفیت فروش ناموفق بود."
                )
            )

        portfolio = data.get("portfolio")

        if portfolio is None:
            raise RuntimeError(
                "پاسخ ظرفیت فروش فاقد portfolio است."
            )

        if not isinstance(portfolio, dict):
            raise RuntimeError(
                "portfolio پاسخ ظرفیت فروش یک "
                "object نیست."
            )

        number_of_shares = portfolio.get(
            "numberOfShares"
        )

        if number_of_shares is None:
            raise RuntimeError(
                "portfolio فاقد numberOfShares است."
            )

        if isinstance(number_of_shares, bool) or not (
            isinstance(number_of_shares, (int, float))
        ):
            raise RuntimeError(
                "numberOfShares پاسخ ظرفیت فروش "
                "عددی نیست."
            )

        if number_of_shares < 0:
            raise RuntimeError(
                "ظرفیت فروش منفی است."
            )

        return int(number_of_shares)

    # =================================================
    # Account / Balance
    # =================================================

    def get_account(self) -> Account:
        """
        دریافت موجودی حساب آگاه.
        """

        response = self._authed_get_with_recovery(
            "financialaccounts/balances",
        )

        data = response.json()

        if not data.get("isSuccess", True):
            raise RuntimeError(
                data.get(
                    "message",
                    "دریافت موجودی حساب ناموفق بود."
                )
            )

        account_data = data.get("data")

        if not isinstance(account_data, dict):
            raise RuntimeError(
                "پاسخ موجودی فاقد data معتبر است."
            )

        return Account(
            last_balance=account_data.get(
                "lastBalance"
            ),
            adjusted_balance_t2=account_data.get(
                "adjustedBalanceT2"
            ),
            tradable_balance_t1=account_data.get(
                "tradableBalanceT1"
            ),
            tradable_balance_t2=account_data.get(
                "tradableBalanceT2"
            ),
            payable_balance_with_agah_credit_t0=(
                account_data.get(
                    "payableBalanceWithAgahCreditT0"
                )
            ),
            payable_balance_with_agah_credit_t1=(
                account_data.get(
                    "payableBalanceWithAgahCreditT1"
                )
            ),
            payable_balance_with_agah_credit_t2=(
                account_data.get(
                    "payableBalanceWithAgahCreditT2"
                )
            ),
            payable_balance_without_agah_credit_t0=(
                account_data.get(
                    "payableBalanceWithoutAgahCreditT0"
                )
            ),
            block=account_data.get("block"),
            credit=account_data.get("credit"),
            settlement_date_t0=account_data.get(
                "settlementDateT0"
            ),
            settlement_date_t1=account_data.get(
                "settlementDateT1"
            ),
            settlement_date_t2=account_data.get(
                "settlementDateT2"
            ),
        )

    def get_tradable_balance(self):
        """
        موجودی قابل‌معاملهٔ سطح حساب آگاه (قدرت خرید).

        همان endpoint مستند موجودی حساب را می‌خواند و فقط فیلد
        ``tradableBalanceT1`` را برمی‌گرداند. این مقدار با ظرفیت خرید
        نمادمحور (``trades/calculatedquantity``) یکی نیست و نباید
        جایگزین آن شود.
        """
        account = self.get_account()
        value = account.tradable_balance_t1

        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise RuntimeError(
                "tradableBalanceT1 در پاسخ موجودی معتبر نیست."
            )

        return value

    # =================================================
    # Instrument
    # =================================================

    def get_instrument(
        self,
        nsc_id: str,
    ) -> BrokerInstrument:
        """
        دریافت اطلاعات معاملاتی نماد از آگاه.
        """

        if not nsc_id:
            raise ValueError(
                "nsc_id نمی‌تواند خالی باشد."
            )

        response = self._authed_get_with_recovery(
            "instruments",
            params={
                "nscIds": nsc_id
            },
        )

        data = response.json()

        if not data.get("isSuccess", True):
            raise RuntimeError(
                data.get(
                    "message",
                    "دریافت اطلاعات نماد ناموفق بود."
                )
            )

        instruments = data.get("data")

        if not isinstance(
            instruments,
            list,
        ):
            raise RuntimeError(
                "پاسخ instruments فاقد لیست معتبر است."
            )

        if not instruments:
            raise LookupError(
                f"نماد با nscId={nsc_id} پیدا نشد."
            )

        item = instruments[0]

        return BrokerInstrument(
            name=item.get("name"),
            company_name=item.get(
                "companyName"
            ),
            nsc_id=item.get("nscId"),
            tse_id=item.get("tseId"),
            market_title=item.get(
                "marketTitle"
            ),
            state_code=item.get(
                "stateCode"
            ),
            group_state_code=item.get(
                "groupStateCode"
            ),
            last_trade_price=item.get(
                "lastTradePrice"
            ),
            final_price=item.get(
                "finalPrice"
            ),
            previous_day_price=item.get(
                "previousDayPrice"
            ),
            upper_price_threshold=item.get(
                "upperPriceThreshold"
            ),
            lower_price_threshold=item.get(
                "lowerPriceThreshold"
            ),
            minimum_order_quantity=item.get(
                "minimumOrderQuantity"
            ),
            lot_size=item.get(
                "lotSize"
            ),
            fixed_price_tick=item.get(
                "fixedPriceTick"
            ),
            maximum_order_quantity_for_buy=(
                item.get(
                    "maximumOrderQuantityForBuy"
                )
            ),
            maximum_order_quantity_for_sell=(
                item.get(
                    "maximumOrderQuantityForSell"
                )
            ),
            bid_ask_list=item.get(
                "bidAskList"
            ),
            is_fund=item.get(
                "isFund",
                False,
            ),
        )

    def get_instrument_by_instrument_id(
        self,
        instrument_id: str,
    ) -> BrokerInstrument:
        """
        دریافت اطلاعات نماد آگاه با استفاده از
        TSETMC instrumentID.
        """

        if not instrument_id:
            raise ValueError(
                "instrument_id نمی‌تواند خالی باشد."
            )

        return self.get_instrument(
            instrument_id
        )

    def get_instrument_by_isin(
        self,
        isin: str,
    ) -> BrokerInstrument:
        """
        متد قدیمی برای سازگاری.
        برای مسیر اصلی پروژه از instrument_id استفاده شود.
        """

        if not isin:
            raise ValueError(
                "ISIN نمی‌تواند خالی باشد."
            )

        return self.get_instrument(isin)

    # =================================================
    # Order
    # =================================================

    def build_order_payload(
        self,
        order: Order,
    ) -> dict:
        """
        ساخت Payload نهایی سفارش.
        هیچ درخواست شبکه‌ای ارسال نمی‌کند.
        """

        if not isinstance(order, Order):
            raise TypeError(
                "order باید از نوع Order باشد."
            )

        return order.to_payload()

    def submit_prepared_order(self, payload: dict, live: bool = False):
        """Submit an already-built request without rebuilding its payload."""
        if not isinstance(payload, dict):
            raise TypeError("payload باید از نوع dict باشد.")
        if not live:
            return {"mode": "DRY_RUN", "sent": False, "payload": payload}
        if not self.live_trading_enabled:
            raise RuntimeError(
                "ارسال زنده سفارش غیرفعال است. live_trading_enabled=False"
            )
        response = self.session.post(
            self._url("order"),
            headers=self._auth_headers(),
            json=payload,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("isSuccess"):
            raise RuntimeError(data.get("message", "ارسال سفارش ناموفق بود."))
        return data

    def prepare_order_sender(self, account_id, transport_factory=None):
        """Create a single-use, account-labeled sender with an isolated session.

        The sender captures this broker's current authenticated identity and
        uses a fresh transport. It is single-use so its requests.Session is
        never concurrently shared. The broker retains ownership and enforces
        its existing Live lock for every hand-off.

        ``transport_factory`` is an internal/test seam; production defaults to
        ``requests.Session``. The supplied account ID is retained only as a
        binding label because this broker's historical authentication contract
        does not itself receive the application's account ID.
        """
        if not isinstance(account_id, str) or not account_id.strip():
            raise ValueError("A non-empty account_id is required")
        with self._prepared_sender_lock:
            if self._account_id != account_id:
                message = ("Broker is already bound to another account"
                           if self._account_id is not None
                           else "Broker is not bound to this account")
                raise RuntimeError(message)
        access_token = self.access_token
        user_identifier = self.user_identifier
        if not access_token or not user_identifier:
            raise RuntimeError("Broker has no complete authenticated identity")
        factory = transport_factory or requests.Session
        transport = factory()
        try:
            # Match the broker's API client defaults without sharing its
            # mutable Session, cookies, adapters, or connection pool.
            transport.headers.update(dict(self.session.headers))
            sender = PreparedOrderSender(
                owner=self,
                account_id=account_id,
                user_identifier=user_identifier,
                access_token=access_token,
                transport=transport,
            )
        except Exception:
            close = getattr(transport, "close", None)
            if callable(close):
                close()
            raise
        with self._prepared_sender_lock:
            self._prepared_senders.add(sender)
        return sender

    async def prepare_async_order_transport(self, account_id, session_factory, *, connector_limit=1, connector_factory=None):
        """Create one account-isolated async transport before schedule firing."""
        if not isinstance(account_id, str) or not account_id.strip():
            raise ValueError("A non-empty account_id is required")
        with self._prepared_sender_lock:
            if self._account_id != account_id:
                raise RuntimeError("Broker is not bound to this account")
        if not self.access_token or not self.user_identifier:
            raise RuntimeError("Broker has no complete authenticated identity")
        if not isinstance(connector_limit, int) or connector_limit < 1:
            raise ValueError("connector_limit must be a positive integer")
        from aiohttp import ClientTimeout
        if connector_factory is None:
            from aiohttp import TCPConnector
            connector_factory = TCPConnector
        session = session_factory(
            headers=dict(self.session.headers),
            timeout=ClientTimeout(total=10),
            connector=connector_factory(limit=connector_limit),
        )
        transport = AsyncPreparedOrderTransport(
            owner=self, account_id=account_id,
            user_identifier=self.user_identifier,
            access_token=self.access_token, session=session,
        )
        with self._prepared_sender_lock:
            self._async_prepared_transports.add(transport)
        return transport

    async def submit_from_async_prepared_transport(
        self, transport, account_id, payload, *, ticket=None,
        authorization=None, broker=None, on_post_start=None,
    ):
        """Broker-owned Live hand-off; the broker lock is checked at POST time."""
        if not isinstance(payload, dict):
            raise TypeError("payload باید از نوع dict باشد.")
        with self._prepared_sender_lock:
            valid_owner = (
                transport in self._async_prepared_transports
                and transport._owner is self
                and transport.account_id == account_id
                and self._account_id == account_id
            )
        if not valid_owner:
            raise RuntimeError("Prepared transport does not belong to this broker/account")
        if not self.live_trading_enabled:
            raise RuntimeError(
                "ارسال زنده سفارش غیرفعال است. live_trading_enabled=False"
            )
        if ticket is None:
            raise RuntimeError("A reserved scheduled ticket is required")
        if not self.live_trading_enabled:
            raise RuntimeError(
                "ارسال زنده سفارش غیرفعال است. live_trading_enabled=False"
            )
        return await transport.submit_ticket(
            ticket, authorization, broker, payload=payload,
            on_post_start=on_post_start,
        )

    async def close_async_prepared_transport(self, transport):
        with self._prepared_sender_lock:
            self._async_prepared_transports.discard(transport)
        await transport.close()

    async def close_async_prepared_transports(self):
        with self._prepared_sender_lock:
            transports = tuple(self._async_prepared_transports)
            self._async_prepared_transports.clear()
        for transport in transports:
            await transport.close()

    def bind_account_identity(self, account_id):
        """Bind a newly account-scoped broker to its owning account once.

        Account composition must call this when it creates the account-owned
        broker. Rebinding is rejected, including after sender closure.
        """
        if not isinstance(account_id, str) or not account_id.strip():
            raise ValueError("A non-empty account_id is required")
        with self._prepared_sender_lock:
            if self._account_id is not None and self._account_id != account_id:
                raise RuntimeError("Broker is already bound to another account")
            self._account_id = account_id

    def submit_from_prepared_sender(self, sender, account_id, payload):
        """Broker-owned one-shot hand-off from an already prepared sender."""
        if not isinstance(payload, dict):
            raise TypeError("payload باید از نوع dict باشد.")
        if not self.live_trading_enabled:
            raise RuntimeError(
                "ارسال زنده سفارش غیرفعال است. live_trading_enabled=False"
            )
        if (not isinstance(sender, PreparedOrderSender)
                or sender.owner is not self
                or self._account_id != account_id
                or sender.account_id != account_id
                or sender not in self._prepared_senders):
            raise RuntimeError("Prepared sender does not belong to this broker/account")
        return sender._submit_once(payload)

    def close_prepared_sender(self, sender):
        """Close and release one sender; safe to call repeatedly."""
        with self._prepared_sender_lock:
            if sender not in self._prepared_senders:
                return
            self._prepared_senders.remove(sender)
        sender._close()

    def close_prepared_senders(self):
        """Close all outstanding prepared senders owned by this broker."""
        with self._prepared_sender_lock:
            senders = tuple(self._prepared_senders)
            self._prepared_senders.clear()
        for sender in senders:
            sender._close()

    def place_order(
        self,
        order: Order,
        live: bool = False,
    ):
        """
        ارسال سفارش.

        به‌صورت پیش‌فرض هیچ سفارش واقعی ارسال نمی‌شود.

        live=True فقط زمانی مجاز است که:
            self.live_trading_enabled == True
        باشد.
        """

        if not isinstance(order, Order):
            raise TypeError(
                "order باید از نوع Order باشد."
            )

        payload = self.build_order_payload(
            order
        )

        # ---------------------------------------------
        # Safety lock
        # ---------------------------------------------

        if not live:
            return {
                "mode": "DRY_RUN",
                "sent": False,
                "payload": payload,
            }

        if not self.live_trading_enabled:
            raise RuntimeError(
                "ارسال زنده سفارش غیرفعال است. "
                "live_trading_enabled=False"
            )

        # ---------------------------------------------
        # Live order
        # ---------------------------------------------

        response = self.session.post(
            self._url("order"),
            headers=self._auth_headers(),
            json=payload,
            timeout=10,
        )

        response.raise_for_status()

        data = response.json()

        if not data.get("isSuccess"):
            raise RuntimeError(
                data.get(
                    "message",
                    "ارسال سفارش ناموفق بود."
                )
            )

        return data

    # =================================================
    # Queue Position (Stage 2)
    # =================================================
    # Feedback / Queue Position Listeners (Stage 3 bridge)
    # =================================================

    def add_order_registered_listener(self, callback) -> None:
        """Register a callback for AcceptedByBourse order registration events."""
        self._order_registered_listeners.append(callback)

    def add_queue_position_listener(self, callback) -> None:
        """Register a callback for queue position updates."""
        self._queue_position_listeners.append(callback)

    def add_order_error_listener(self, callback) -> None:
        """Register a callback for order tracking errors."""
        self._order_error_listeners.append(callback)

    def add_feedback_unavailable_listener(self, callback) -> None:
        """Register a display-only listener for NATS transport loss."""
        self._feedback_unavailable_listeners.append(callback)

    def _on_feedback_unavailable_forward(self, reason: str) -> None:
        """Forward NATS status without touching the order-send lifecycle."""
        for callback in tuple(self._feedback_unavailable_listeners):
            try:
                callback(reason)
            except Exception:
                self._logger.warning("Feedback status listener failed")

    def _on_order_registered_forward(self, decision_id: str, order_info) -> None:
        """Forward AcceptedByBourse registration to all registered listeners."""
        for cb in self._order_registered_listeners:
            try:
                cb(decision_id, order_info)
            except Exception:
                self._logger.warning(
                    "Order registered listener failed for %s", decision_id
                )

    def _on_queue_position_forward(self, decision_id: str, position: int) -> None:
        """Forward queue position updates to all registered listeners."""
        for cb in self._queue_position_listeners:
            try:
                cb(decision_id, position)
            except Exception:
                self._logger.warning(
                    "Queue position listener failed for %s", decision_id
                )

    def _on_order_error_forward(self, decision_id: str, error: str) -> None:
        """Forward order errors to all registered listeners."""
        for cb in self._order_error_listeners:
            try:
                cb(decision_id, error)
            except Exception:
                self._logger.warning(
                    "Order error listener failed for %s", decision_id
                )

    def _ensure_queue_position_provider(self) -> "AgahQueuePositionProvider":
        """Lazy initialization of queue position provider."""
        if self._queue_position_provider is None:
            from .queue_position import AgahQueuePositionProvider
            self._queue_position_provider = AgahQueuePositionProvider(
                self,
                on_order_registered=self._on_order_registered_forward,
                on_queue_position=self._on_queue_position_forward,
                on_error=self._on_order_error_forward,
                on_unavailable=self._on_feedback_unavailable_forward,
            )
        return self._queue_position_provider

    async def start_queue_position_tracking(self) -> None:
        """Start queue position tracking via NATS/OMS."""
        provider = self._ensure_queue_position_provider()
        await provider.start()

    async def stop_queue_position_tracking(self) -> None:
        """Stop queue position tracking."""
        if self._queue_position_provider:
            await self._queue_position_provider.stop()

    def on_order_placed(self, decision_id: str, nsc_id: str) -> None:
        """Called when order is placed to register for queue position tracking."""
        provider = self._ensure_queue_position_provider()
        provider.on_order_placed(decision_id, nsc_id)

    def get_queue_position(self, decision_id: str) -> Optional[int]:
        """Get queue position for an order by decisionId."""
        if self._queue_position_provider:
            return self._queue_position_provider.get_queue_position(decision_id)
        return None

    # =================================================
    # Cancel Order
    # =================================================

    def cancel_order(self, order_id):
        """
        هنوز endpoint لغو سفارش تأیید نشده است.
        """

        raise NotImplementedError(
            "لغو سفارش هنوز پیاده‌سازی نشده است."
        )
