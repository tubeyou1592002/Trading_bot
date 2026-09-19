"""
Block 9 — Task 9.1: Offline Simulation Harness.

A small, offline, deterministic harness that runs one real order-execution
attempt through the REAL existing dispatch path:

    ExecutionPlan  ->  DispatchCore.dispatch()  ->  BrokerManager
        ->  Simulation Broker  ->  DispatchResult

Design rules (Task 9.1):

  * This module is a TEST ENVIRONMENT ONLY. It does not redesign or change
    DispatchCore, OrderEngine, the Broker contract, or any M6-A … M6-E
    logic. Everything below the DispatchCore boundary is the real code;
    the ONLY substituted component is the Broker + InstrumentProvider pair
    registered in a private ``BrokerManager`` (the exact seam Block 2
    already exposes, and the same seam every offline test of Blocks 6-8
    already uses).
  * No network access of any kind. The simulation broker/provider keep all
    state in memory and never construct any HTTP session, socket, or
    request. The real Agaah broker (``requests.Session``) is never
    instantiated: the private ``BrokerManager`` registers ONLY the
    simulation pair, so the production ``BrokerManager.__init__`` binding
    is not touched.
  * No credentials, no real orders, no ``live_trading_enabled``: the
    harness always dispatches with ``live=False`` and the simulation
    broker refuses live orders fail-closed.
  * Deterministic: no sleeps, no random values, no wall-clock dependence
    in results (each run with the same inputs produces the same outcome
    and the same recorded calls).

Explicitly OUT of scope for Task 9.1 (later Block 9 tasks):
    High volume, severe burst, multi-account/multi-broker stress, failure
    injection, timeout, retry, queue, concurrency, load, performance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from brokers.base import Broker, InstrumentLookupError, InstrumentProvider
from brokers.manager import BrokerManager
from core.dispatch_contracts import DispatchResult, ExecutionPlan
from core.dispatch_core import DispatchCore
from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.instrument import Instrument
from models.order import Order
from models.trading_state import VERIFIED_TRADABLE, TradingState


# ---------------------------------------------------------------------------
# Deterministic instrument catalog (pure data, no network)
# ---------------------------------------------------------------------------


def build_simulation_catalog(
    ins_codes: Tuple[str, ...] = ("INS-SIM-1",),
) -> Dict[str, Tuple[Instrument, BrokerInstrument]]:
    """
    Build the fixed (Instrument, BrokerInstrument) catalog the simulation
    broker serves. Deterministic: same ins_code -> same record every run.

    The produced ``BrokerInstrument`` satisfies every M6-B validator rule
    (minimum quantity, lot size, price tick, price band) with wide bounds
    so a basic valid order passes unchanged through the real OrderEngine.
    """
    catalog: Dict[str, Tuple[Instrument, BrokerInstrument]] = {}
    for ins_code in ins_codes:
        catalog[ins_code] = (
            Instrument(
                symbol=ins_code,
                name=f"SIM:{ins_code}",
                ins_code=ins_code,
            ),
            BrokerInstrument(
                name=f"SIM:{ins_code}",
                company_name=f"Simulation Co {ins_code}",
                # Contract convention of this harness: the broker-side
                # nsc_id equals the TSETMC ins_code, so order.nsc_id always
                # matches (M6-A) without any mapping logic.
                nsc_id=ins_code,
                tse_id=ins_code,
                market_title="SIM",
                minimum_order_quantity=1,
                lot_size=1,
                fixed_price_tick=1,
                lower_price_threshold=1,
                upper_price_threshold=1_000_000,
                maximum_order_quantity_for_buy=1_000_000,
                maximum_order_quantity_for_sell=1_000_000,
            ),
        )
    return catalog


def make_simulation_account(
    account_id: str = "ACC-SIM-1",
    tradable_balance_t1: int = 10_000_000_000,
) -> Account:
    """A plain offline Account with an identity and a positive T1 balance."""
    return Account(
        account_id=account_id,
        last_balance=tradable_balance_t1,
        adjusted_balance_t2=tradable_balance_t1,
        tradable_balance_t1=tradable_balance_t1,
        tradable_balance_t2=tradable_balance_t1,
    )


def make_simulation_order(
    ins_code: str = "INS-SIM-1",
    side: int = 1,  # BUY
    price: int = 10_000,
    quantity: int = 10,
) -> Order:
    """A plain offline Order for the simulation instrument."""
    return Order(
        nsc_id=ins_code,
        side=side,
        price=price,
        quantity=quantity,
    )


# ---------------------------------------------------------------------------
# Simulation Broker + InstrumentProvider (the only substituted components)
# ---------------------------------------------------------------------------


@dataclass
class SimulationCallRecord:
    """One observable, inspectable call made on the simulation broker."""

    op: str
    payload: Any


class SimulationBroker(Broker):
    """
    In-memory Broker implementing the existing ``Broker`` contract.

    It only ever serves the fixed simulation catalog, records every call
    for inspection, and is fail-closed for live orders. It holds no
    session, no socket, no credential, and no real-API code.
    """

    def __init__(
        self,
        name: str = "SIM",
        catalog: Optional[Dict[str, Tuple[Instrument, BrokerInstrument]]] = None,
        max_capacity: int = 1_000_000,
    ):
        self._name = name
        self.catalog = catalog or build_simulation_catalog()
        self.max_capacity = max_capacity
        self.live_trading_enabled = False  # hard-off, like production today
        self.calls: List[SimulationCallRecord] = []
        self.place_order_calls: List[Tuple[Order, bool]] = []
        # Task 9.6 — controlled, deterministic failure injection knobs.
        # Only THIS simulation broker ever fails; nothing in the engine,
        # core, or contracts changes behavior.
        self.fail_on_nsc_id: Optional[str] = None
        self.fail_on_sequence: Optional[int] = None
        self.fail_mode: str = "exception"  # "exception" | "failed_response" | "timeout"
        self.failure_exception: Exception = RuntimeError("SIM broker failure")
        self.fail_response: Optional[dict] = None  # default built in _fail_response
        self.timeout_after_n_calls: int = 1
        self.timeout_calls_seen = 0
        self.timeouts_raised = 0
        # One-shot semantics: an armed failure fires on the FIRST matching
        # place_order, records itself, and disarms (no retry, no repeat).
        self.fired_count = 0
        # Per-broker counter of incoming place_order calls (used to scope a
        # sequence-targeted failure; deterministic within one broker).
        self._place_seq_seen = 0

    # -- contract methods ---------------------------------------------------

    @property
    def name(self):
        """Contract identity of this broker (abstract property in Broker)."""
        return self._name

    def login(self, username, password, **kwargs):
        """Offline: no session, no credential handling — recorded only."""
        self.calls.append(
            SimulationCallRecord(
                op="login",
                payload={"username": username},
            )
        )
        return {
            "success": True,
            "mode": "SIMULATION",
            "username": username,
        }

    def get_account(self):
        self.calls.append(SimulationCallRecord(op="get_account", payload=None))
        return make_simulation_account()

    def place_order(self, order, live: bool = False):
        """
        Record the call and return the broker-side result envelope.

        Dry-run (live=False): returns the same ``{"mode": "DRY_RUN",
        "sent": False, ...}`` envelope shape the real dry-run path returns,
        so the engine's ``DRY_RUN`` result is produced unchanged.

        Live (live=True): fail-closed. The harness never calls this with
        live=True, and the broker itself refuses it independently.
        """
        self.calls.append(
            SimulationCallRecord(op="place_order", payload=order.to_payload())
        )
        self.place_order_calls.append((order, live))

        if live:
            raise RuntimeError(
                "SimulationBroker: live orders are forbidden in simulation."
            )

        # Task 9.6 — controlled failure injection, recorded and deterministic.
        # The failure is strictly scoped by identity and the live flag is
        # checked BEFORE it, so a live refusal always wins.
        if self._should_fail(order):
            return self._fail_response(order)

        return {
            "mode": "DRY_RUN",
            "sent": False,
            "order_id": f"SIM-{order.nsc_id}",
            "payload": order.to_payload(),
        }

    # -- Task 9.6: controlled failure injection (simulation only) ------------

    def configure_failure(
        self,
        fail_on_nsc_id: Optional[str] = None,
        fail_on_sequence: Optional[int] = None,
        fail_mode: str = "exception",
        failure_exception: Optional[Exception] = None,
        fail_response: Optional[dict] = None,
        timeout_after_n_calls: int = 1,
    ) -> None:
        """
        Arm exactly ONE controlled failure on this simulation broker.

        Deterministic and identity-scoped: the failure fires on the FIRST
        matching ``place_order`` (by nsc_id, or by the per-broker sequence
        of incoming place_order calls), records itself in ``calls`` as an
        ``injected_failure`` op, and disarms itself — the engine's own
        handling (no retry) sees exactly one failure.
        """
        self.fail_on_nsc_id = fail_on_nsc_id
        self.fail_on_sequence = fail_on_sequence
        self.fail_mode = fail_mode
        if failure_exception is not None:
            self.failure_exception = failure_exception
        self.fail_response = fail_response
        self.timeout_after_n_calls = timeout_after_n_calls
        self.timeout_calls_seen = 0
        self.timeouts_raised = 0
        self.fired_count = 0
        self._place_seq_seen = 0

    def clear_failure(self) -> None:
        """Remove any armed failure (broker returns to the healthy path)."""
        self.fail_on_nsc_id = None
        self.fail_on_sequence = None
        self.fail_mode = "exception"
        self.fail_response = None
        self.timeout_after_n_calls = 1
        self.timeout_calls_seen = 0
        self.timeouts_raised = 0
        self.fired_count = 0
        self._place_seq_seen = 0

    def _should_fail(self, order) -> bool:
        """True when the armed failure applies to this place_order call."""
        nsc_match = (
            self.fail_on_nsc_id is not None
            and order.nsc_id == self.fail_on_nsc_id
        )
        return nsc_match or self._sequence_matched(order)

    def _sequence_matched(self, order) -> bool:
        """True when the sequence-scoped failure applies to this call."""
        if self.fail_on_sequence is None:
            return False
        self._place_seq_seen += 1
        return self._place_seq_seen == self.fail_on_sequence

    def _record_injected(self, kind: str, order) -> None:
        self.calls.append(
            SimulationCallRecord(
                op="injected_failure",
                payload={"kind": kind, "nsc_id": order.nsc_id},
            )
        )
        self.fired_count += 1

    def _disarm(self) -> None:
        self.fail_on_nsc_id = None
        self.fail_on_sequence = None

    def _fail_response(self, order):
        """Produce the configured failure outcome for one place_order call."""
        if self.fail_mode == "exception":
            self._record_injected("exception", order)
            self._disarm()
            raise self.failure_exception
        if self.fail_mode == "failed_response":
            envelope = self.fail_response or {
                "mode": "FAILED",
                "sent": False,
                "success": False,
                "error": "SIM: broker rejected the order",
                "order_id": f"SIM-{order.nsc_id}",
            }
            # Record the exact envelope the broker returned so the broker-side
            # fact is observable (the current engine contract carries a
            # non-exception response through as the per-order ``response``
            # without re-interpreting it — see the Task 9.6 report).
            self.calls.append(
                SimulationCallRecord(
                    op="injected_failure",
                    payload={
                        "kind": "failed_response",
                        "nsc_id": order.nsc_id,
                        "response": envelope,
                    },
                )
            )
            self.fired_count += 1
            self._disarm()
            return envelope
        if self.fail_mode == "timeout":
            self.timeout_calls_seen += 1
            if self.timeout_calls_seen >= self.timeout_after_n_calls:
                self._record_injected("timeout", order)
                self.timeouts_raised += 1
                self._disarm()
                raise TimeoutError(
                    f"SIM: simulated timeout after {self.timeout_calls_seen} calls"
                )
        return {
            "mode": "DRY_RUN",
            "sent": False,
            "order_id": f"SIM-{order.nsc_id}",
            "payload": order.to_payload(),
        }

    def cancel_order(self, order_id):
        self.calls.append(
            SimulationCallRecord(op="cancel_order", payload=order_id)
        )
        return {"canceled": True, "order_id": order_id}

    def get_trading_state(self, nsc_id: str) -> TradingState:
        """
        Deterministic M6-A input: the simulation instrument is always
        verified and tradable (the same ``VERIFIED_TRADABLE`` constant the
        production tests use).
        """
        self.calls.append(
            SimulationCallRecord(op="get_trading_state", payload=nsc_id)
        )
        return VERIFIED_TRADABLE

    def get_buy_capacity(self, nsc_id, side_code, fund, price) -> int:
        self.calls.append(
            SimulationCallRecord(
                op="get_buy_capacity",
                payload={
                    "nsc_id": nsc_id,
                    "side_code": side_code,
                    "fund": fund,
                    "price": price,
                },
            )
        )
        return self.max_capacity

    def get_sell_capacity(self, nsc_id, side_code, fund, price) -> int:
        self.calls.append(
            SimulationCallRecord(
                op="get_sell_capacity",
                payload={
                    "nsc_id": nsc_id,
                    "side_code": side_code,
                    "fund": fund,
                    "price": price,
                },
            )
        )
        return self.max_capacity


class SimulationInstrumentProvider(InstrumentProvider):
    """
    In-memory InstrumentProvider implementing the existing contract.

    It resolves ins_code -> (Instrument, BrokerInstrument) purely from the
    fixed catalog and raises the contract's ``InstrumentLookupError`` for
    anything else — the exact behavior the real provider path expects.
    """

    def __init__(self, broker: SimulationBroker):
        self._broker = broker
        self.calls: List[str] = []

    def get_instrument(self, ins_code: str) -> Tuple[Instrument, BrokerInstrument]:
        self.calls.append(f"get_instrument:{ins_code}")
        if ins_code not in self._broker.catalog:
            raise InstrumentLookupError(
                f"Simulation catalog has no instrument for ins_code={ins_code}"
            )
        return self._broker.catalog[ins_code]

    def get_nsc_id(self, ins_code: str) -> Optional[str]:
        self.calls.append(f"get_nsc_id:{ins_code}")
        if ins_code not in self._broker.catalog:
            raise InstrumentLookupError(
                f"Simulation catalog has no instrument for ins_code={ins_code}"
            )
        return self._broker.catalog[ins_code][1].nsc_id

    def refresh_cache(self) -> None:
        self.calls.append("refresh_cache")


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


@dataclass
class SimulationRunRecord:
    """
    Everything observable about one harness run — the inspectable outcome
    Task 9.1 requires ("نتیجه اجرای هر سفارش قابل مشاهده و بررسی").
    """

    dispatch_result: DispatchResult
    broker: SimulationBroker
    provider: SimulationInstrumentProvider
    plan: ExecutionPlan
    # Optional multi-broker view (Task 9.5): name -> broker / provider, both
    # resolved through the REAL BrokerManager. Single-broker scenarios
    # (Tasks 9.1-9.4) leave these unset.
    brokers: Optional[Dict[str, SimulationBroker]] = None
    providers: Optional[Dict[str, SimulationInstrumentProvider]] = None

    @property
    def success(self) -> bool:
        return self.dispatch_result.success

    @property
    def reached_simulation_broker(self) -> bool:
        """True when the dispatch actually arrived at the simulation broker."""
        return len(self.broker.place_order_calls) > 0

    @property
    def place_order_calls(self) -> List[Tuple[Order, bool]]:
        return list(self.broker.place_order_calls)


class SimulationHarness:
    """
    Offline harness around the REAL dispatch path.

    Usage:

        harness = SimulationHarness()
        run = harness.run_basic_scenario()
        run.dispatch_result.mode == "ALL_PROCESSED"
        run.reached_simulation_broker is True
        run.place_order_calls == [(order, False)]

    What is REAL in this path:

        ExecutionPlan (built by the real Block 1 ExecutionPlanner)
        DispatchCore.dispatch() (the real Block 2 core)
        BrokerManager.get / get_instrument_provider (the real manager)
        OrderEngine.execute_by_ins_code (the real engine, M6-A … M6-E)

    What is SIMULATED (the only seam):

        Broker + InstrumentProvider, replaced by the offline in-memory
        pair registered in the harness's own private ``BrokerManager``.
    """

    DEFAULT_BROKER_NAME = "SIM"
    # Task 9.3: deterministic burst severity — larger than every Task 9.2
    # volume (10 / 50 / 100).
    DEFAULT_BURST_VOLUME = 250

    def __init__(
        self,
        broker_name: str = DEFAULT_BROKER_NAME,
        catalog: Optional[Dict[str, Tuple[Instrument, BrokerInstrument]]] = None,
    ):
        self.broker_name = broker_name
        self.catalog = catalog or build_simulation_catalog()
        self.broker = SimulationBroker(name=broker_name, catalog=self.catalog)
        self.provider: SimulationInstrumentProvider = None  # set below

        # Private manager: registers ONLY the simulation pair, so the
        # production binding (AgaahBroker) is never constructed here.
        self.manager = BrokerManager.__new__(BrokerManager)
        self.manager.brokers = {}
        self.manager.providers = {}
        self.manager._provider_classes = {}
        self.manager.register(
            broker_name, self.broker, SimulationInstrumentProvider
        )
        # The provider is resolved exactly the way production resolves it:
        # lazily built by the real BrokerManager (provider_class(broker))
        # and cached on the manager, so the instance used on the dispatch
        # path is the manager's own, not a parallel one.
        self.provider = self.manager.get_instrument_provider(broker_name)

        # The REAL DispatchCore over that manager. live trading stays off
        # (DispatchCore hard-codes live=False; nothing here changes it).
        self.dispatch_core = DispatchCore(broker_manager=self.manager)

    # -- scenario runner -----------------------------------------------------

    def run_basic_scenario(
        self,
        order: Optional[Order] = None,
        account: Optional[Account] = None,
        plan_id: str = "task9.1-sim-plan",
    ) -> SimulationRunRecord:
        """
        Run the one base scenario of Task 9.1:

            valid ExecutionPlan -> DispatchCore -> BrokerManager
                -> Simulation Broker -> DispatchResult

        The plan is built by the real Block 1 planner and the bound
        ``Account`` object is attached exactly the way the existing
        integration layer does (same pattern as Blocks 6-8 tests).
        """
        # Import here to keep the module import surface at the dispatch
        # contracts only; the planner is real project code either way.
        from core.execution_planner import (
            ExecutionPlanner,
            LogicalOrderInstruction,
            PlannedOrder,
        )

        order = order or make_simulation_order()
        account = account or make_simulation_account()

        planned = PlannedOrder(
            order=order,
            account_id=account.account_id,
            broker_name=self.broker_name,
            sequence=1,
        )
        plan = ExecutionPlanner().build_plan(
            LogicalOrderInstruction(plan_id=plan_id, orders=[planned])
        )
        # Attach the resolved Account object (integration-layer convention;
        # without it DispatchCore fail-closes with an id-only binding).
        plan.accounts = [account]

        result = self.dispatch_core.dispatch(plan)

        return SimulationRunRecord(
            dispatch_result=result,
            broker=self.broker,
            provider=self.provider,
            plan=plan,
        )

    # -- volume scenario runner (Task 9.2) ------------------------------------

    def volume_order_fields(self, sequence: int) -> Tuple[str, int, int]:
        """
        Deterministic (ins_code, price, quantity) for the order bound to
        ``sequence`` in a volume plan (Task 9.2).

        Every order is uniquely identifiable (distinct price) so any lost,
        duplicated, swapped, or cross-routed execution is detectable on the
        real dispatch path. All values stay inside the simulation catalog's
        M6-B validator bounds and the broker capacity.
        """
        return (
            next(iter(self.catalog)),
            1_000 + sequence,
            10 + (sequence % 10),
        )

    def build_volume_plan(
        self,
        volume: int,
        plan_id: str = "task9.2-volume-plan",
    ) -> ExecutionPlan:
        """
        Build ONE ``ExecutionPlan`` carrying ``volume`` planned orders
        (sequences 1..volume) through the REAL Block 1 planner (Task 9.2).

        Reuses the exact Task 9.1 components: the same simulation catalog,
        the same single simulation account, the same broker binding. One
        account -> one broker, so the existing Block 6 binding / Block 7
        routing contracts hold unchanged. Sequences are unique by
        construction and the planner rejects duplicates fail-closed.
        """
        if not isinstance(volume, int) or isinstance(volume, bool) or volume < 1:
            raise ValueError("volume must be a positive integer")

        # Same local import convention as ``run_basic_scenario``: the real
        # project planner, no new architecture.
        from core.execution_planner import (
            ExecutionPlanner,
            LogicalOrderInstruction,
            PlannedOrder,
        )

        account = make_simulation_account()
        planned = []
        for sequence in range(1, volume + 1):
            ins_code, price, quantity = self.volume_order_fields(sequence)
            planned.append(
                PlannedOrder(
                    order=make_simulation_order(
                        ins_code=ins_code,
                        side=1,  # BUY (single-side: multi-side/multi-account is later tasks)
                        price=price,
                        quantity=quantity,
                    ),
                    account_id=account.account_id,
                    broker_name=self.broker_name,
                    sequence=sequence,
                )
            )

        plan = ExecutionPlanner().build_plan(
            LogicalOrderInstruction(plan_id=plan_id, orders=planned)
        )
        # Attach the resolved Account object exactly like the Task 9.1 base
        # scenario (integration-layer convention).
        plan.accounts = [account]
        return plan

    def run_volume_scenario(
        self,
        volume: int,
        plan_id: str = "task9.2-volume-plan",
    ) -> SimulationRunRecord:
        """
        Run one High Volume scenario (Task 9.2) on the REAL dispatch path:

            ExecutionPlanner -> ExecutionPlan -> DispatchCore.dispatch()
                -> BrokerManager -> OrderEngine -> SimulationBroker
                -> DispatchResult

        No shortcut is taken: the plan is dispatched through the same real
        ``DispatchCore`` entry point as the base scenario; the only
        substituted components remain the Task 9.1 simulation pair.
        """
        plan = self.build_volume_plan(volume, plan_id=plan_id)
        result = self.dispatch_core.dispatch(plan)
        return SimulationRunRecord(
            dispatch_result=result,
            broker=self.broker,
            provider=self.provider,
            plan=plan,
        )

    # -- multi-account isolation scenario runner (Task 9.4) --------------------

    def multi_account_plan(
        self,
        volume: int = 4,
        plan_id: str = "task9.4-multi-account-plan",
    ) -> ExecutionPlan:
        """
        Build ONE ``ExecutionPlan`` that interleaves two accounts across two
        distinct instruments, on the REAL Block 1 planner and the existing
        Block 6 binding architecture (Task 9.4):

            odd  sequences -> ACC-SIM-1 -> STOCK-A
            even sequences -> ACC-SIM-2 -> STOCK-B

        The two accounts carry deliberately distinct
        ``tradable_balance_t1`` values, so the identity of the account that
        actually drove each execution is observable in the real engine's
        ``get_buy_capacity(fund=...)`` call (M6-D passes
        ``account.tradable_balance_t1`` as ``fund``).

        Both accounts route to the same single registered simulation broker
        via ``plan.account_routes`` (multi-broker isolation is Task 9.5 and
        is intentionally NOT exercised here). Deterministic: same inputs
        produce the same plan.
        """
        if not isinstance(volume, int) or isinstance(volume, bool) or volume < 1:
            raise ValueError("volume must be a positive integer")

        # Same local-import convention as the other scenario builders: the
        # real project planner, no new architecture.
        from core.execution_planner import (
            ExecutionPlanner,
            LogicalOrderInstruction,
            PlannedOrder,
        )

        acc1 = make_simulation_account(
            "ACC-SIM-1", tradable_balance_t1=1_000_000_000
        )
        acc2 = make_simulation_account(
            "ACC-SIM-2", tradable_balance_t1=2_000_000_000
        )

        planned = []
        for sequence in range(1, volume + 1):
            if sequence % 2 == 1:
                account, ins_code, price = acc1, "STOCK-A", 10_000 + sequence
            else:
                account, ins_code, price = acc2, "STOCK-B", 20_000 + sequence
            planned.append(
                PlannedOrder(
                    order=make_simulation_order(
                        ins_code=ins_code,
                        side=1,  # BUY (single-side: multi-side is out of scope)
                        price=price,
                        quantity=10 + (sequence % 10),
                    ),
                    account_id=account.account_id,
                    broker_name=self.broker_name,
                    sequence=sequence,
                )
            )

        plan = ExecutionPlanner().build_plan(
            LogicalOrderInstruction(plan_id=plan_id, orders=planned)
        )
        # Attach the resolved Account objects exactly like the Task 9.1 base
        # scenario (integration-layer convention); _plan_account matches each
        # sequence's binding to the right object by account_id.
        plan.accounts = [acc1, acc2]
        return plan

    def run_multi_account_scenario(
        self,
        volume: int = 4,
        plan_id: str = "task9.4-multi-account-plan",
    ) -> SimulationRunRecord:
        """
        Run one Multi-Account Isolation scenario (Task 9.4) on the REAL
        dispatch path:

            ExecutionPlanner -> ExecutionPlan -> DispatchCore.dispatch()
                -> BrokerManager -> OrderEngine -> SimulationBroker
                -> DispatchResult

        No shortcut is taken: the interleaved two-account plan is dispatched
        through the same real ``DispatchCore`` entry point; the only
        substituted components remain the Task 9.1 simulation pair.
        """
        plan = self.multi_account_plan(volume, plan_id=plan_id)
        result = self.dispatch_core.dispatch(plan)
        return SimulationRunRecord(
            dispatch_result=result,
            broker=self.broker,
            provider=self.provider,
            plan=plan,
        )

    # -- multi-broker isolation scenario runner (Task 9.5) ---------------------

    def multi_broker_plan(
        self,
        volume: int = 8,
        plan_id: str = "task9.5-multi-broker-plan",
        broker_a_name: str = "SIM-A",
        broker_b_name: str = "SIM-B",
    ) -> ExecutionPlan:
        """
        Build ONE ``ExecutionPlan`` that interleaves two accounts across two
        distinct instruments AND two distinct brokers, on the REAL Block 1
        planner and the existing Block 6 binding / Block 7 routing
        architecture (Task 9.5):

            odd  sequences -> ACC-SIM-1 -> STOCK-A -> SIM-A
            even sequences -> ACC-SIM-2 -> STOCK-B -> SIM-B

        Prices/quantities/balances are deliberately distinct per path so
        any account/broker/instrument swap is detectable from the real
        broker trails alone (M6-D passes ``account.tradable_balance_t1``
        as ``fund``). Deterministic.
        """
        if not isinstance(volume, int) or isinstance(volume, bool) or volume < 1:
            raise ValueError("volume must be a positive integer")

        # Same local-import convention as the other scenario builders: the
        # real project planner, no new architecture.
        from core.execution_planner import (
            ExecutionPlanner,
            LogicalOrderInstruction,
            PlannedOrder,
        )

        acc1 = make_simulation_account(
            "ACC-SIM-1", tradable_balance_t1=1_000_000_000
        )
        acc2 = make_simulation_account(
            "ACC-SIM-2", tradable_balance_t1=2_000_000_000
        )

        planned = []
        for sequence in range(1, volume + 1):
            if sequence % 2 == 1:
                account, ins_code, broker_name = acc1, "STOCK-A", broker_a_name
                price, quantity = 10_000 + sequence, 100 + sequence
            else:
                account, ins_code, broker_name = acc2, "STOCK-B", broker_b_name
                price, quantity = 20_000 + sequence, 200 + sequence
            planned.append(
                PlannedOrder(
                    order=make_simulation_order(
                        ins_code=ins_code,
                        side=1,  # BUY (single-side: multi-side is out of scope)
                        price=price,
                        quantity=quantity,
                    ),
                    account_id=account.account_id,
                    broker_name=broker_name,
                    sequence=sequence,
                )
            )

        plan = ExecutionPlanner().build_plan(
            LogicalOrderInstruction(plan_id=plan_id, orders=planned)
        )
        # Attach the resolved Account objects exactly like the Task 9.1 base
        # scenario (integration-layer convention).
        plan.accounts = [acc1, acc2]
        return plan

    def run_multi_broker_scenario(
        self,
        volume: int = 8,
        plan_id: str = "task9.5-multi-broker-plan",
        broker_a_name: str = "SIM-A",
        broker_b_name: str = "SIM-B",
    ) -> SimulationRunRecord:
        """
        Run one Multi-Broker Isolation scenario (Task 9.5) on the REAL
        dispatch path:

            ExecutionPlanner -> ExecutionPlan -> DispatchCore.dispatch()
                -> BrokerManager (per-sequence broker + provider resolution)
                -> OrderEngine -> SimulationBroker A / SimulationBroker B
                -> DispatchResult

        The broker/provider pairs recorded on the run are resolved through
        the REAL manager seam (``get`` / ``get_instrument_provider``), not
        stashed in parallel attributes.
        """
        plan = self.multi_broker_plan(
            volume,
            plan_id=plan_id,
            broker_a_name=broker_a_name,
            broker_b_name=broker_b_name,
        )
        result = self.dispatch_core.dispatch(plan)
        return SimulationRunRecord(
            dispatch_result=result,
            broker=self.broker,
            provider=self.provider,
            plan=plan,
            brokers={
                name: self.manager.get(name)
                for name in (broker_a_name, broker_b_name)
            },
            providers={
                name: self.manager.get_instrument_provider(name)
                for name in (broker_a_name, broker_b_name)
            },
        )

    # -- failure-injection scenario runner (Task 9.6) --------------------------

    def run_failure_scenario(
        self,
        volume: int = 8,
        plan_id: str = "task9.6-failure-plan",
        broker_a_name: str = "SIM-A",
        broker_b_name: str = "SIM-B",
        fail_broker_name: str = "SIM-B",
        fail_nsc_id: Optional[str] = "STOCK-B",
        fail_on_broker_sequence: Optional[int] = None,
        fail_mode: str = "exception",
        failure_exception: Optional[Exception] = None,
        fail_response: Optional[dict] = None,
    ) -> SimulationRunRecord:
        """
        Run one controlled Failure-Injection scenario (Task 9.6) on the REAL
        dispatch path:

            ExecutionPlanner -> ExecutionPlan -> DispatchCore.dispatch()
                -> BrokerManager (per-sequence broker + provider)
                -> OrderEngine -> SimulationBroker A / SimulationBroker B
                -> DispatchResult

        Deterministic interleaved plan (8 orders by default), two accounts,
        two brokers, three instruments:

            odd  sequences -> ACC-SIM-1 -> SIM-A -> STOCK-A (seq % 4 == 1)
                                                   STOCK-C (seq % 4 == 3)
            even sequences -> ACC-SIM-2 -> SIM-B -> STOCK-B

        The failure is armed ONLY on the named simulation broker (SIM-B by
        default) and is scoped to exactly one cause: either the first
        ``place_order`` of ``fail_nsc_id`` on that broker, or its
        ``fail_on_broker_sequence``-th incoming ``place_order`` call. The
        broker produces the configured outcome (exception / failed response
        / simulated timeout) inside the REAL engine path; the engine's own
        exception handling turns it into the per-order result the current
        architecture defines. Nothing else in the path changes: no retry,
        no failover, no queue — isolation of the other executions is proven,
        not engineered.

        Only fail_nsc_id OR fail_on_broker_sequence may be armed per run;
        when ``fail_nsc_id`` is given it takes precedence (single cause).
        """
        if not isinstance(volume, int) or isinstance(volume, bool) or volume < 1:
            raise ValueError("volume must be a positive integer")

        # Same local-import convention as the other scenario builders.
        from core.execution_planner import (
            ExecutionPlanner,
            LogicalOrderInstruction,
            PlannedOrder,
        )

        acc1 = make_simulation_account(
            "ACC-SIM-1", tradable_balance_t1=1_000_000_000
        )
        acc2 = make_simulation_account(
            "ACC-SIM-2", tradable_balance_t1=2_000_000_000
        )

        planned = []
        for sequence in range(1, volume + 1):
            if sequence % 2 == 1:
                # A path: alternate the two Account-1 instruments.
                if sequence % 4 == 1:
                    ins_code, price, quantity = (
                        "STOCK-A", 10_000 + sequence, 100 + sequence
                    )
                else:
                    ins_code, price, quantity = (
                        "STOCK-C", 30_000 + sequence, 300 + sequence
                    )
                account, broker_name = acc1, broker_a_name
            else:
                ins_code, price, quantity = (
                    "STOCK-B", 20_000 + sequence, 200 + sequence
                )
                account, broker_name = acc2, broker_b_name
            planned.append(
                PlannedOrder(
                    order=make_simulation_order(
                        ins_code=ins_code,
                        side=1,
                        price=price,
                        quantity=quantity,
                    ),
                    account_id=account.account_id,
                    broker_name=broker_name,
                    sequence=sequence,
                )
            )

        plan = ExecutionPlanner().build_plan(
            LogicalOrderInstruction(plan_id=plan_id, orders=planned)
        )
        plan.accounts = [acc1, acc2]

        # Arm the controlled failure on exactly ONE simulation broker.
        fail_broker = self.manager.get(fail_broker_name)
        if fail_nsc_id is not None:
            fail_broker.configure_failure(
                fail_on_nsc_id=fail_nsc_id,
                fail_mode=fail_mode,
                failure_exception=failure_exception,
                fail_response=fail_response,
            )
        elif fail_on_broker_sequence is not None:
            fail_broker.configure_failure(
                fail_on_sequence=fail_on_broker_sequence,
                fail_mode=fail_mode,
                failure_exception=failure_exception,
                fail_response=fail_response,
            )

        result = self.dispatch_core.dispatch(plan)
        return SimulationRunRecord(
            dispatch_result=result,
            broker=self.broker,
            provider=self.provider,
            plan=plan,
            brokers={
                name: self.manager.get(name)
                for name in (broker_a_name, broker_b_name)
            },
            providers={
                name: self.manager.get_instrument_provider(name)
                for name in (broker_a_name, broker_b_name)
            },
        )

    # -- burst scenario runner (Task 9.3) --------------------------------------

    def run_burst_scenario(
        self,
        volume: int = DEFAULT_BURST_VOLUME,
        plan_id: str = "task9.3-burst-plan",
    ) -> SimulationRunRecord:
        """
        Run one Severe Burst scenario (Task 9.3) on the REAL dispatch path:

            ExecutionPlanner -> ExecutionPlan -> DispatchCore.dispatch()
                -> BrokerManager -> OrderEngine -> SimulationBroker
                -> DispatchResult

        A burst here is severity, not concurrency: ``volume`` orders (more
        than any Task 9.2 volume) arrive compressed into ONE ExecutionPlan
        and are executed strictly sequentially by the real engine inside a
        single ``dispatch()`` call. The Task 9.2 plan builder is reused
        unchanged — no queue, no threading, no batching, no new
        architecture, and no production component is touched.
        """
        plan = self.build_volume_plan(volume, plan_id=plan_id)
        result = self.dispatch_core.dispatch(plan)
        return SimulationRunRecord(
            dispatch_result=result,
            broker=self.broker,
            provider=self.provider,
            plan=plan,
        )


def build_dual_broker_harness(
    broker_a_name: str = "SIM-A",
    broker_b_name: str = "SIM-B",
    ins_codes: Tuple[str, ...] = ("STOCK-A", "STOCK-B"),
) -> SimulationHarness:
    """
    Task 9.5 test-environment factory (still NO production code touched).

    Returns a ``SimulationHarness`` whose private BrokerManager registers
    TWO independent simulation pairs — (SIM-A broker, its own provider
    class) and (SIM-B broker, its own provider class) — through the
    EXISTING ``BrokerManager.register()`` seam: the exact Block 7
    registration path production uses for multiple brokers. Both providers
    are managed entirely by the real BrokerManager: each is an independent
    instance built by the manager from the registered provider class,
    bound to that broker's own instance, and cached per broker name in
    ``manager.providers``. Their materialization timing is per-broker,
    exactly as the existing seam behaves: SIM-A's provider is already
    resolved at factory exit (the harness constructor resolves it via
    ``get_instrument_provider``), while SIM-B's provider is built on its
    first ``get_instrument_provider(broker_b_name)`` call (as DispatchCore
    does on the dispatch path). Provider isolation therefore follows from
    the existing architecture, not from any new wiring.
    """
    harness = SimulationHarness(
        broker_name=broker_a_name,
        catalog=build_simulation_catalog(ins_codes=ins_codes),
    )
    broker_b = SimulationBroker(name=broker_b_name, catalog=harness.catalog)
    # Existing Block 7 seam — no new registration mechanism:
    harness.manager.register(
        broker_b_name, broker_b, SimulationInstrumentProvider
    )
    return harness
