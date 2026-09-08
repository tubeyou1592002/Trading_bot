import base64

import requests

from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.order import Order
from models.trading_state import UNVERIFIED, TradingState
from market.tsetmc import TSETMC

from ..base import Broker
from ..device_info import ExternalDeviceInfoProvider


CETAVAL_ALLOWED = {"A ", "A", "AR"}

CETAVAL_BLOCKED = {
    "I ",
    "I",
    "AG",
    "AS",
    "IG",
    "IS",
    "IR",
}


BASE_URL = "https://tseonlineapi.agah.com/api/v1"
ORIGIN = "https://online.agah.com"
REFERER = "https://online.agah.com/"

CLIENT_KEY = "634e0572-a4a3-4fd6-b033-82211dba74f1"


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

        # ---------------------------------------------
        # Safety
        # ---------------------------------------------
        # False = هیچ POST /order ارسال نمی‌شود.
        self.live_trading_enabled = False

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
        """

        if not nsc_id:
            raise ValueError(
                "nsc_id نمی‌تواند خالی باشد."
            )

        try:
            broker_instrument = self.get_instrument(nsc_id)
        except Exception:
            return UNVERIFIED

        ins_code = getattr(broker_instrument, "tse_id", None)

        if not ins_code:
            return UNVERIFIED

        tsetmc = TSETMC()

        try:
            states = tsetmc.get_trading_state(ins_code)
        except Exception:
            return UNVERIFIED

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

        if c_etaval in CETAVAL_ALLOWED:
            return TradingState(
                is_order_entry_allowed=True,
                is_verified=True,
                source="tsetmc:cEtaval",
                reason=f"cEtaval={c_etaval}",
            )

        if c_etaval in CETAVAL_BLOCKED:
            return TradingState(
                is_order_entry_allowed=False,
                is_verified=True,
                source="tsetmc:cEtaval",
                reason=f"cEtaval={c_etaval}",
            )

        return TradingState(
            is_order_entry_allowed=False,
            is_verified=False,
            source="tsetmc:cEtaval",
            reason=(
                f"cEtaval ناشناخته: "
                f"({c_etaval!r})"
            ),
        )

    # =================================================
    # Helpers
    # =================================================

    def _url(self, path: str) -> str:
        return f"{BASE_URL}/{path.lstrip('/')}"

    def _auth_headers(self):
        if not self.access_token:
            raise RuntimeError(
                "کاربر به آگاه وارد نشده است."
            )

        if not self.user_identifier:
            raise RuntimeError(
                "UserIdentifier موجود نیست."
            )

        return {
            "Authorization": f"Bearer {self.access_token}",
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

        response = self.session.get(
            self._url("trades/calculatedquantity"),
            params={
                "nscId": nsc_id,
                "sideCode": side_code,
                "fund": fund,
                "price": price,
            },
            headers=self._auth_headers(),
            timeout=10,
        )

        response.raise_for_status()

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

    # =================================================
    # Account / Balance
    # =================================================

    def get_account(self) -> Account:
        """
        دریافت موجودی حساب آگاه.
        """

        response = self.session.get(
            self._url(
                "financialaccounts/balances"
            ),
            headers=self._auth_headers(),
            timeout=10,
        )

        response.raise_for_status()

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

        response = self.session.get(
            self._url("instruments"),
            params={
                "nscIds": nsc_id
            },
            headers=self._auth_headers(),
            timeout=10,
        )

        response.raise_for_status()

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
    # Cancel Order
    # =================================================

    def cancel_order(self, order_id):
        """
        هنوز endpoint لغو سفارش تأیید نشده است.
        """

        raise NotImplementedError(
            "لغو سفارش هنوز پیاده‌سازی نشده است."
        )
