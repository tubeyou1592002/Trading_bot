from dataclasses import dataclass
from datetime import datetime
import json
from time import perf_counter_ns
from typing import TYPE_CHECKING, Optional

from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.order import BUY, SELL, Order
from models.order_validator import (
    OrderValidationError,
    OrderValidator,
)
from models.trading_state import (
    TradingState,
    TradingStateUnavailable,
)


def _wall_clock_now() -> datetime:
    """
    The single wall-clock seam for the broker-receipt timestamp.

    Kept deliberately tiny and module-level so tests can inject a fixed
    clock. Returns the real wall clock with millisecond precision; no
    monotonic value is ever converted here.
    """
    return datetime.now()

if TYPE_CHECKING:
    from brokers.base import InstrumentProvider
    from core.latency_instrumentation import BrokerCallRecorder
else:
    from brokers.base import (
        InstrumentLookupError,
        InstrumentProvider,
    )

# Task 8.3 — Broker/API boundary measurement. These are used ONLY to time the
# existing broker/provider calls around their call sites; no broker contract,
# payload, credential or return value is touched.
from core.latency_instrumentation import (
    OP_GET_BUY_CAPACITY,
    OP_GET_INSTRUMENT,
    OP_GET_SELL_CAPACITY,
    OP_GET_TRADING_STATE,
    OP_PLACE_ORDER,
    measure_broker_call,
)


@dataclass
class OrderExecutionResult:
    success: bool
    sent: bool
    mode: str

    order: Order

    broker_name: str | None = None
    message: str | None = None

    response: dict | None = None

    # UI-5 Task 4 Stage 3 Task 2 — wall-clock receipt boundary.
    # Real local wall-clock moment the existing ``broker.place_order(...)
    # call returned to the application, with millisecond precision. Taken at
    # the return boundary, never derived from ``sent_at`` or the monotonic
    # ``broker_registered_at_ns``; ``None`` whenever no real broker receipt
    # moment exists (fail-closed).
    broker_received_at: datetime | None = None


@dataclass(frozen=True)
class PreparedOrder:
    """Immutable binding of a validated order to its final broker payload."""
    order: Order
    payload_json: str
    account_id: str
    broker_name: str
    prepared_at: datetime
    expires_at: datetime | None
    m6_results: tuple
    m6_completed_at: datetime
    freshness: tuple
    order_fingerprint: str
    account_fingerprint: str
    broker_identity: int
    instrument: BrokerInstrument
    evidence_order_fingerprint: str
    evidence_account_id: str
    evidence_broker_name: str
    checks_succeeded: bool
    scheduled_valid: bool

    @property
    def payload(self):
        return json.loads(self.payload_json)


@dataclass(frozen=True)
class PreparedBatch:
    orders: tuple
    valid: bool
    message: str = ""
    checks_succeeded: bool = False


class OrderEngine:
    # Filled only from a documented source policy. No source-specific M6
    # validity periods are currently documented in this repository.
    PREPARED_SOURCE_TTLS = {}

    def __init__(self):
        self.validator = OrderValidator()

    @staticmethod
    def _fingerprint(value):
        return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))

    def prepare_order(self, broker, provider, ins_code, order, account,
                      account_id, broker_name, max_age=None, broker_timing=None):
        if not callable(getattr(broker, "build_order_payload", None)):
            raise ValueError(f"Broker {broker_name} lacks scheduled prepared-order capability")
        try:
            _, instrument = measure_broker_call(
                broker_timing, OP_GET_INSTRUMENT,
                lambda: provider.get_instrument(ins_code),
            )
        except Exception as exc:
            return None, OrderExecutionResult(False, False, "BLOCKED", order,
                broker_name=broker_name, message=f"Instrument lookup failed: {exc}")
        evidence = []
        result = self.prepare(broker, order, instrument, account, broker_timing,
                              evidence=evidence)
        if not result.success:
            return None, result
        # The repository documents no elapsed-time validity limit for these
        # sources; do not invent one. Keep successful reads as evidence but
        # mark their scheduled-use validity unknown so submission fails closed.
        payload = broker.build_order_payload(order)
        now = datetime.now().astimezone()
        freshness = tuple(
            (item[3], item[4],
             item[4] + self.PREPARED_SOURCE_TTLS[item[3]]
             if item[3] in self.PREPARED_SOURCE_TTLS else None)
            for item in evidence
        )
        prepared = PreparedOrder(
            order=order, payload_json=self._fingerprint(payload),
            account_id=account_id, broker_name=broker_name,
            prepared_at=now,
            expires_at=min((item[2] for item in freshness if item[2] is not None),
                           default=None),
            m6_results=tuple(evidence), m6_completed_at=now,
            freshness=freshness,
            order_fingerprint=self._fingerprint(order.to_payload()),
            account_fingerprint=self._fingerprint(vars(account)),
            broker_identity=id(broker), instrument=instrument,
            evidence_order_fingerprint=self._fingerprint(order.to_payload()),
            evidence_account_id=account_id, evidence_broker_name=broker_name,
            checks_succeeded=True,
            scheduled_valid=bool(freshness) and all(expiry is not None for _, _, expiry in freshness),
        )
        return prepared, result

    def submit_prepared_order(self, prepared, broker, account, account_id,
                              broker_name, live=False):
        order = getattr(prepared, "order", None)
        def blocked(message):
            return OrderExecutionResult(False, False, "BLOCKED", order,
                broker_name=broker_name, message=message)
        if not isinstance(prepared, PreparedOrder):
            return blocked("Invalid prepared order")
        if not prepared.checks_succeeded or not prepared.scheduled_valid:
            return blocked("Preparation checks succeeded but scheduled validity is not established")
        if (not prepared.payload_json or not prepared.m6_results
                or prepared.m6_completed_at is None
                or not prepared.prepared_at
                or not prepared.order_fingerprint
                or not prepared.account_fingerprint):
            return blocked("Prepared order evidence is incomplete")
        if not prepared.freshness or any(
                not isinstance(item, tuple) or len(item) != 3
                or item[2] is None for item in prepared.freshness):
            return blocked("Scheduled validity is undocumented for one or more M6 sources")
        if not isinstance(prepared.expires_at, datetime):
            return blocked("Prepared batch expiry is missing")
        now = datetime.now().astimezone()
        if any(now > expires_at for _, _, expires_at in prepared.freshness):
            return blocked("A prepared source result has expired")
        if any(not isinstance(item, tuple) or len(item) != 6 or item[1] is not True
               or not isinstance(item[2], int) or item[2] < 0
               or not isinstance(item[3], str) or not item[3]
               or not isinstance(item[4], datetime)
               for item in prepared.m6_results):
            return blocked("Prepared order M6 evidence is invalid")
        capacity_gate = (
            "M6-C-buy-capacity" if order.side == BUY
            else "M6-D-sell-capacity" if order.side == SELL
            else None
        )
        required_gates = {
            "M6-A-identity", "M6-A-trading-state", "M6-B-validation",
            capacity_gate, "M6-E-capacity-check",
        }
        names = [item[0] for item in prepared.m6_results]
        if (None in required_gates or len(names) != len(set(names))
                or set(names) != required_gates):
            return blocked("Prepared order M6 evidence set is incomplete or inconsistent")
        expected_freshness = tuple((item[3], item[4],
            item[4] + self.PREPARED_SOURCE_TTLS[item[3]]
            if item[3] in self.PREPARED_SOURCE_TTLS else None)
            for item in prepared.m6_results)
        if prepared.freshness != expected_freshness:
            return blocked("Prepared freshness records do not match their M6 source evidence")
        if (prepared.account_id != account_id or prepared.broker_name != broker_name
                or prepared.broker_identity != id(broker)):
            return blocked("Prepared destination changed")
        if getattr(account, "account_id", None) != account_id:
            return blocked("Prepared account identity changed")
        if self._fingerprint(vars(account)) != prepared.account_fingerprint:
            return blocked("Prepared account changed")
        if self._fingerprint(order.to_payload()) != prepared.order_fingerprint:
            return blocked("Prepared order changed")
        if (prepared.evidence_order_fingerprint != prepared.order_fingerprint
                or prepared.evidence_account_id != prepared.account_id
                or prepared.evidence_broker_name != prepared.broker_name):
            return blocked("Prepared M6 evidence belongs to another order or destination")
        if self._fingerprint(prepared.payload) != prepared.payload_json:
            return blocked("Prepared payload changed")
        submit = getattr(broker, "submit_prepared_order", None)
        if not callable(submit):
            return blocked(f"Broker {broker_name} lacks prepared-order submission")
        if live and not getattr(broker, "live_trading_enabled", False):
            return blocked("ارسال زنده سفارش غیرفعال است")
        try:
            response = submit(prepared.payload, live=live)
        except Exception as exc:
            return OrderExecutionResult(False, False, "ERROR", order,
                broker_name=broker_name, message=str(exc))
        return OrderExecutionResult(True, live, "LIVE" if live else "DRY_RUN",
            order, broker_name=broker_name, response=response)

    def prepare_batch(self, requests):
        """Prepare all request tuples (kwargs to prepare_order), or reject all."""
        prepared = []
        for request in requests:
            try:
                item, result = self.prepare_order(**request)
            except Exception as exc:
                return PreparedBatch((), False, str(exc), False)
            if item is None or not result.success:
                return PreparedBatch((), False, result.message or "Batch preparation failed", False)
            if not item.scheduled_valid:
                return PreparedBatch((), False,
                    "Scheduled validity is undocumented for one or more preparation sources", True)
            prepared.append(item)
        return PreparedBatch(tuple(prepared), True, "", True)

    def execute_by_ins_code(
        self,
        broker,
        provider: "InstrumentProvider",
        ins_code: str,
        order: Order,
        account: Account,
        live: bool = False,
        broker_timing: Optional["BrokerCallRecorder"] = None,
        collector: Optional["LatencyCollector"] = None,
        sequence: Optional[int] = None,
    ) -> OrderExecutionResult:
        """
        اجرای سفارش با دریافت `ins_code` به‌جای BrokerInstrument.

        ``broker_timing`` (Task 8.3) is an optional, opt-in recorder that
        measures the round trip of the existing broker/provider calls. When
        it is None the behavior is exactly as before and no clock is read.

        ``collector`` and ``sequence`` (UI-5 Task 4 Stage 1) optionally capture
        order feedback timestamps. When None, no feedback timestamps are recorded.

        Pipeline:

            ins_code
                -> InstrumentProvider.get_instrument(ins_code)
                -> (Instrument, BrokerInstrument)
                -> بررسی nsc_id (بدون overwrite)
                -> OrderEngine.execute(...)

        اگر provider نتواند Instrument را resolve کند
        (InstrumentLookupError)، نتیجه BLOCKED با پیام
        ``Instrument lookup failed: {detail}`` برگردانده
        می‌شود و هیچ سفارشی ارسال نمی‌شود.

        اگر order.nsc_id با provider-resolved nsc_id
        یکسان نباشد، نتیجه BLOCKED می‌شود و مقدار
        order.nsc_id تغییر نمی‌کند (overwrite مجاز نیست).

        این متد هیچ وابستگی Agah-specific ندارد و فقط
        با abstraction `InstrumentProvider` کار می‌کند.
        """

        if broker is None:
            raise ValueError(
                "کارگزاری مشخص نشده است."
            )

        if provider is None:
            raise ValueError(
                "InstrumentProvider مشخص نشده است."
            )

        if not isinstance(order, Order):
            raise TypeError(
                "order باید از نوع Order باشد."
            )

        if not isinstance(account, Account):
            raise TypeError(
                "account باید از نوع Account باشد."
            )

        # ---------------------------------------------
        # Step 1: Resolve instrument via provider
        # ---------------------------------------------

        try:
            _, broker_instrument = measure_broker_call(
                broker_timing,
                OP_GET_INSTRUMENT,
                lambda: provider.get_instrument(ins_code),
            )
        except InstrumentLookupError as exc:
            return OrderExecutionResult(
                success=False,
                sent=False,
                mode="BLOCKED",
                order=order,
                broker_name=getattr(
                    broker, "name", None
                ),
                message=(
                    f"Instrument lookup failed: {exc}"
                ),
            )

        if not isinstance(
            broker_instrument,
            BrokerInstrument,
        ):
            return OrderExecutionResult(
                success=False,
                sent=False,
                mode="BLOCKED",
                order=order,
                broker_name=getattr(
                    broker, "name", None
                ),
                message=(
                    "InstrumentProvider خروجی نامعتبر "
                    "برگرداند."
                ),
            )

        # ---------------------------------------------
        # Step 2: nsc_id consistency check (no overwrite)
        # ---------------------------------------------

        if order.nsc_id != broker_instrument.nsc_id:
            return OrderExecutionResult(
                success=False,
                sent=False,
                mode="BLOCKED",
                order=order,
                broker_name=getattr(
                    broker, "name", None
                ),
                message=(
                    "nscId سفارش با nscId حل‌شده توسط "
                    "InstrumentProvider یکسان نیست؛ "
                    "overwrite مجاز نیست."
                ),
            )

        # ---------------------------------------------
        # Step 3: Delegate to existing execute()
        # ---------------------------------------------

        return self.execute(
            broker=broker,
            order=order,
            instrument=broker_instrument,
            account=account,
            live=live,
            broker_timing=broker_timing,
            collector=collector,
            sequence=sequence,
        )

    def prepare(
        self,
        broker,
        order: Order,
        instrument: BrokerInstrument,
        account: Account,
        broker_timing: Optional["BrokerCallRecorder"] = None,
        evidence=None,
    ) -> OrderExecutionResult:
        """
        آماده‌سازی سفارش بدون ارسال.

        ``broker_timing`` (Task 8.3) optionally measures the round trip of
        the existing ``get_trading_state`` / capacity reads. Measurement only:
        all M6-A … M6-E gates, their order, and their fail-closed behavior are
        unchanged.
        """

        if broker is None:
            raise ValueError(
                "کارگزاری مشخص نشده است."
            )

        if not isinstance(order, Order):
            raise TypeError(
                "order باید از نوع Order باشد."
            )

        if not isinstance(
            instrument,
            BrokerInstrument,
        ):
            raise TypeError(
                "instrument باید از نوع BrokerInstrument باشد."
            )

        if not isinstance(account, Account):
            raise TypeError(
                "account باید از نوع Account باشد."
            )

        # ---------------------------------------------
        # Instrument Identity (M6-A)
        # ---------------------------------------------
        # order.nsc_id باید با nsc_id BrokerInstrument
        # تطبیق داشته باشد. عدم تطابق باعث Block سفارش
        # می‌شود و overwrite مجاز نیست.

        gate_started = perf_counter_ns()
        if order.nsc_id != instrument.nsc_id:
            return OrderExecutionResult(
                success=False,
                sent=False,
                mode="BLOCKED",
                order=order,
                broker_name=broker.name,
                message=(
                    "nscId سفارش با nscId BrokerInstrument "
                    "یکسان نیست."
                ),
            )
        if evidence is not None:
            evidence.append(("M6-A-identity", True, perf_counter_ns() - gate_started,
                             "OrderEngine.order.nsc_id/BrokerInstrument.nsc_id",
                             datetime.now().astimezone(), None))

        # ---------------------------------------------
        # Trading State
        # ---------------------------------------------
        # فقط خطای واقعی «منبع در دسترس نیست» بلاک
        # می‌شود. خطاهای برنامه‌نویسی (AttributeError،
        # TypeError، NotImplementedError و ...) عمداً
        # منتشر می‌شوند تا باگ‌ها پنهان نشوند.

        gate_started = perf_counter_ns()
        try:
            state = measure_broker_call(
                broker_timing,
                OP_GET_TRADING_STATE,
                lambda: broker.get_trading_state(
                    instrument.nsc_id
                ),
            )
        except TradingStateUnavailable as exc:
            return OrderExecutionResult(
                success=False,
                sent=False,
                mode="BLOCKED",
                order=order,
                broker_name=broker.name,
                message=(
                    "منبع وضعیت معاملاتی نماد در دسترس "
                    f"نیست: {exc}"
                ),
            )

        if not isinstance(state, TradingState):
            return OrderExecutionResult(
                success=False,
                sent=False,
                mode="BLOCKED",
                order=order,
                broker_name=broker.name,
                message=(
                    "broker.get_trading_state مقدار نامعتبر "
                    "برگرداند."
                ),
            )

        if not state.is_verified:
            return OrderExecutionResult(
                success=False,
                sent=False,
                mode="BLOCKED",
                order=order,
                broker_name=broker.name,
                message=(
                    "وضعیت معاملاتی نماد هنوز از منبع معتبر "
                    "تأیید نشده است؛ ارسال سفارش بلاک شد."
                ),
            )

        if not state.is_order_entry_allowed:
            return OrderExecutionResult(
                success=False,
                sent=False,
                mode="BLOCKED",
                order=order,
                broker_name=broker.name,
                message=(
                    "ثبت سفارش در وضعیت فعلی "
                    "نماد مجاز نیست."
                ),
            )
        if evidence is not None:
            evidence.append(("M6-A-trading-state", True, perf_counter_ns() - gate_started,
                             "broker.get_trading_state", datetime.now().astimezone(), None))

        # ---------------------------------------------
        # Order Validation
        # ---------------------------------------------

        gate_started = perf_counter_ns()
        try:
            self.validator.validate(
                order,
                instrument,
                account,
            )
        except OrderValidationError as exc:
            return OrderExecutionResult(
                success=False,
                sent=False,
                mode="BLOCKED",
                order=order,
                broker_name=broker.name,
                message=str(exc),
            )
        if evidence is not None:
            evidence.append(("M6-B-validation", True, perf_counter_ns() - gate_started,
                             "OrderValidator.validate", datetime.now().astimezone(), None))

        # ---------------------------------------------
        # Capacity (M6-C BUY / M6-D SELL)
        # ---------------------------------------------
        # Unified capacity gate for both BUY and SELL sides.
        #
        # For BUY: fund = account.tradable_balance_t1
        #   (with pre-validation: None / non-numeric / negative)
        # For SELL: fund = None (not relevant per M6-D contract)
        #
        # Both paths share the same exception handling and
        # quantity comparison logic (fail-closed).
        #
        # Gate این‌جا قرار می‌گیرد؛ نه در Validator،
        # زیرا یک فراخوان API است.
        #
        # هر خطای API / شبکه / داده‌ نامعتبر باعث
        # BLOCKED می‌شود (fail-closed).

        if order.side == BUY:

            fund = account.tradable_balance_t1

            if fund is None:
                return OrderExecutionResult(
                    success=False,
                    sent=False,
                    mode="BLOCKED",
                    order=order,
                    broker_name=broker.name,
                    message=(
                        "fund (tradableBalanceT1) مشخص نیست؛ "
                        "ظرفیت خرید قابل‌محاسبه نیست."
                    ),
                )

            if isinstance(fund, bool) or not isinstance(
                fund, (int, float)
            ):
                return OrderExecutionResult(
                    success=False,
                    sent=False,
                    mode="BLOCKED",
                    order=order,
                    broker_name=broker.name,
                    message=(
                        "fund (tradableBalanceT1) معتبر نیست؛ "
                        "ظرفیت خرید قابل‌محاسبه نیست."
                    ),
                )

            if fund < 0:
                return OrderExecutionResult(
                    success=False,
                    sent=False,
                    mode="BLOCKED",
                    order=order,
                    broker_name=broker.name,
                    message=(
                        "fund (tradableBalanceT1) منفی است؛ "
                        "ظرفیت خرید قابل‌محاسبه نیست."
                    ),
                )

            capacity_fn = lambda: measure_broker_call(
                broker_timing,
                OP_GET_BUY_CAPACITY,
                lambda: broker.get_buy_capacity(
                    nsc_id=order.nsc_id,
                    side_code=order.side,
                    fund=fund,
                    price=order.price,
                ),
            )
            capacity_label = "خرید"

        else:

            capacity_fn = lambda: measure_broker_call(
                broker_timing,
                OP_GET_SELL_CAPACITY,
                lambda: broker.get_sell_capacity(
                    nsc_id=order.nsc_id,
                    side_code=order.side,
                    fund=None,
                    price=order.price,
                ),
            )
            capacity_label = "فروش"

        gate_started = perf_counter_ns()
        result = self._check_capacity(
            order=order,
            broker_name=broker.name,
            capacity_fn=capacity_fn,
            capacity_label=capacity_label,
        )

        if not result.success:
            return result
        if evidence is not None:
            gate_name = "M6-C-buy-capacity" if order.side == BUY else "M6-D-sell-capacity"
            capacity_source = "broker.get_buy_capacity" if order.side == BUY else "broker.get_sell_capacity"
            ended = datetime.now().astimezone()
            duration = perf_counter_ns() - gate_started
            evidence.append((gate_name, True, duration, capacity_source, ended, None))
            evidence.append(("M6-E-capacity-check", True, duration,
                             "OrderEngine._check_capacity", ended, None))

        # ---------------------------------------------
        # Ready
        # ---------------------------------------------

        return OrderExecutionResult(
            success=True,
            sent=False,
            mode="READY",
            order=order,
            broker_name=broker.name,
            message="سفارش برای ارسال آماده است.",
        )

    @staticmethod
    def _check_capacity(
        order: Order,
        broker_name: str,
        capacity_fn,
        capacity_label: str,
    ) -> OrderExecutionResult:
        """
        منطق مشترک بررسی ظرفیت خرید/فروش.

        - capacity_fn: یک تابع بدون‌آرگومان که ظرفیت
          محاسبه‌شده توسط broker را برمی‌گرداند.
          هر استثنا → fail-closed BLOCKED.
        - capacity_label: برچسب نمایشی ("خرید" یا "فروش")
          برای پیام خطا.
        """
        try:
            capacity = capacity_fn()
        except Exception as exc:
            return OrderExecutionResult(
                success=False,
                sent=False,
                mode="BLOCKED",
                order=order,
                broker_name=broker_name,
                message=str(exc),
            )

        if order.quantity > capacity:
            return OrderExecutionResult(
                success=False,
                sent=False,
                mode="BLOCKED",
                order=order,
                broker_name=broker_name,
                message=(
                    f"ظرفیت {capacity_label} آگاه "
                    f"کافی نیست "
                    f"(حداکثر {capacity}، "
                    f"درخواستی {order.quantity})."
                ),
            )

        return OrderExecutionResult(
            success=True,
            sent=False,
            mode="READY",
            order=order,
            broker_name=broker_name,
            message="سفارش برای ارسال آماده است.",
        )

    def execute(
        self,
        broker,
        order: Order,
        instrument: BrokerInstrument,
        account: Account,
        live: bool = False,
        broker_timing: Optional["BrokerCallRecorder"] = None,
        collector: Optional["LatencyCollector"] = None,
        sequence: Optional[int] = None,
    ) -> OrderExecutionResult:
        """
        آماده‌سازی و اجرای سفارش.

        ``broker_timing`` (Task 8.3) optionally measures the round trip of the
        existing ``place_order`` call. It is measurement only: ``live``,
        the engine-level safety check, and the existing exception handling are
        unchanged.

        ``collector`` and ``sequence`` (UI-5 Task 4 Stage 1) optionally capture
        order feedback timestamps (sent_at, broker_registered_at,
        matching_engine_registered_at) using the collector's clock. When None,
        no feedback timestamps are recorded.

        live=False:
            فقط Dry Run.

        live=True:
            درخواست ارسال را به Broker می‌دهد.
            خود Broker نیز باید قفل ایمنی خودش را بررسی کند.
        """

        prepared = self.prepare(
            broker=broker,
            order=order,
            instrument=instrument,
            account=account,
            broker_timing=broker_timing,
        )

        if not prepared.success:
            return prepared

        # ---------------------------------------------
        # Engine-level safety
        # ---------------------------------------------
        # حتی اگر broker قفل داخلی داشته باشد، موتور نیز
        # از ارسال واقعی بدون فعال‌سازی صریح جلوگیری می‌کند.

        if live:
            enabled = getattr(
                broker,
                "live_trading_enabled",
                False,
            )
            if not enabled:
                return OrderExecutionResult(
                    success=False,
                    sent=False,
                    mode="BLOCKED",
                    order=order,
                    broker_name=broker.name,
                    message=(
                        "ارسال زنده سفارش غیرفعال است "
                        "(live_trading_enabled=False)."
                    ),
                )

        # Record sent_at timestamp at the actual send point.
        if collector is not None and sequence is not None:
            collector.record_sent_at(sequence)

        try:
            broker_result = measure_broker_call(
                broker_timing,
                OP_PLACE_ORDER,
                lambda: broker.place_order(
                    order,
                    live=live,
                ),
            )

        except Exception as exc:
            return OrderExecutionResult(
                success=False,
                sent=False,
                mode="ERROR",
                order=order,
                broker_name=broker.name,
                message=str(exc),
            )

        # UI-5 Task 4 Stage 3 Task 2 — broker receipt boundary (wall clock).
        # Read exactly once, on the statement IMMEDIATELY after place_order()
        # returned and BEFORE any inspection of the broker response, purely
        # from the real wall clock. The value is only surfaced when a REAL,
        # verified broker receipt exists: a live order whose response is
        # isSuccess=true with a usable, non-empty string decisionId.
        # Fail-closed: everything else leaves broker_received_at None —
        # including dry runs, non-dict responses and this ERROR path.
        broker_received_at: datetime | None = _wall_clock_now()

        # Response inspection starts HERE — strictly after the clock read.
        is_dict_response = isinstance(broker_result, dict)
        is_success = (
            broker_result.get("isSuccess", False)
            if is_dict_response
            else False
        )
        data = (
            broker_result.get("data")
            if is_dict_response
            else None
        )

        receipt_is_verified = (
            is_success is True
            and isinstance(data, dict)
            and isinstance(
                data.get("decisionId"),
                str,
            )
            and data["decisionId"].strip() != ""
        )
        if not receipt_is_verified or not live:
            broker_received_at = None

        # Record broker_registered_at only for live orders with successful
        # initial broker registration (response contains isSuccess=true and data.decisionId).
        # Dry-run does not represent real broker registration.
        if live and isinstance(broker_result, dict):
            is_success = broker_result.get("isSuccess", False)
            data = broker_result.get("data")
            has_decision_id = isinstance(data, dict) and "decisionId" in data

            if is_success and has_decision_id:
                decision_id = data["decisionId"]

                if collector is not None and sequence is not None:
                    collector.record_broker_registered_at(sequence)

                if hasattr(broker, "on_order_placed"):
                    broker.on_order_placed(
                        decision_id,
                        order.nsc_id,
                    )

        # ---------------------------------------------
        # Live
        # ---------------------------------------------

        if live:
            return OrderExecutionResult(
                success=True,
                sent=True,
                mode="LIVE",
                order=order,
                broker_name=broker.name,
                message=(
                    "درخواست سفارش به کارگزاری "
                    "ارسال شد."
                ),
                response=broker_result,
                broker_received_at=broker_received_at,
            )

        # ---------------------------------------------
        # Dry Run
        # ---------------------------------------------

        return OrderExecutionResult(
            success=True,
            sent=False,
            mode="DRY_RUN",
            order=order,
            broker_name=broker.name,
            message="Dry Run با موفقیت انجام شد.",
            response=broker_result,
        )
