"""
ui/test_runner.py — UI-5 Task 2: Controlled Dry-Run Execution runner.

The Test action (UI-5 Task 1 button) hands its ``QueueEntry`` objects to
this runner together with the ALREADY-RESOLVED ``Account`` object of the
active UI account. The runner drives them through the EXISTING execution
chain with no new layer and no modified artifact:

    QueueEntry (exact, never cloned)
        -> core.order_queue_adapter.build_execution_plan_from_selected_entries()
        -> ExecutionPlan                     (Block 0/1, unchanged)
        -> plan.accounts = [account]         (the existing integration-layer
                                              convention — Blocks 6/9/10
                                              attach resolved Account objects
                                              exactly like this)
        -> DispatchIntegration.dispatch()    (Block 5/6, unchanged)
        -> DispatchCore                      (Block 2, unchanged)
        -> OrderEngine.execute_by_ins_code() (M6-A..M6-E gates, unchanged)

Account source (this correction):

  * The ``Account`` object is supplied explicitly by the caller — the UI
    layer — and is NEVER created, inferred, resolved or fabricated by this
    runner. No ``broker.get_account()`` call, no network query, no
    first/default/global account, no rebuild from ``account_id``.
  * In production that object is the ``Account`` of the existing active
    ``ui.account_store.AccountRecord``; the page resolves it and passes it
    to ``run(entries, account=...)`` verbatim.
  * The runner validates, fail-closed BEFORE any build or dispatch:
      (1) entries are non-empty,
      (2) every entry carries the same ``account_id`` / ``broker_name``,
      (3) an ``Account`` object was supplied,
      (4) ``account.account_id`` equals the entries' ``account_id``.
    It then attaches that same object to ``plan.accounts``. The existing
    ``DispatchCore._plan_account`` consumes exactly this convention (the
    same one Blocks 6/9/10 already use), so the real core can execute
    rather than fail-closing on an id-only binding.

Dry-run contract enforced here:

  * ``live=False`` is never passed anywhere. The integration and the
    adapter accept no ``live`` argument at all; the only producer of a
    ``live`` envelope is the existing Block 10.3 SafetyGate bridge inside
    ``DispatchCore``, which this runner never touches (no gate is
    attached, so every dispatch stays the Block 2 Dry Run).
  * Exactly once per Test action: one call to ``run()`` issues exactly one
    dispatch (one plan, one execution, one ``DispatchResult``). There is
    no retry, no loop, no scheduler, no burst.
  * Account / broker identity comes ONLY from the entries plus the
    explicitly supplied Account object: every entry must carry the exact
    same ``account_id`` / ``broker_name`` (fail-closed), the Account must
    match that ``account_id``, and nothing is inferred from a symbol, an
    instrument, a default account or a global.
  * The queue entries are never modified, de-queued, cloned or rebuilt.

Why ``dispatch_selected_entries`` is not used here:

  ``core.order_queue_adapter.dispatch_selected_entries`` builds the plan
  and dispatches it in ONE call — there is no point between the build and
  the dispatch where the resolved ``Account`` object can be attached, so
  the plan would reach ``DispatchCore`` with ``plan.accounts`` as
  account_id strings only and a valid order would be BLOCKED fail-closed
  before the engine. The corrected path instead calls the two EXISTING
  public APIs separately — ``build_execution_plan_from_selected_entries``
  then ``integration.dispatch(plan)`` — and attaches the caller-supplied
  Account object in between (the same convention the existing Blocks 6/9/10
  fixtures already follow). No Core/Bridge/Engine file is touched.

How the pieces stay reusable:

  * ``TestRunner`` imports the Core chain LAZILY — inside ``run()``, never
    at module import time — so importing this module (or constructing the
    runner) performs no Core/Broker/Market access and no network call
    (UI-1 / UI-3.1 offline construction contracts preserved). This is the
    same lazy-seam pattern the page already uses for the resolver
    (``market.symbol_resolver``), the trading-state query
    (``core.trading_state_query``) and the queue (``core.order_queue``).
* ``dispatch_core`` is injectable so tests can substitute a test-double
      Dispatch Core (never a real broker); production leaves it at ``None``
      and the FIRST real run builds the existing ``core.dispatch_core.DispatchCore``.
    * The integration is built once and reused; each ``run()`` still gets its
      own ``plan_id`` (``ui5-test-<n>``) and its own registered execution, so
      re-running the Test action is never a re-execution of an old dispatch.

Why Task 3 results are read here (per-order, from the SAME dispatch):

  * A real ``DispatchCore`` exposes the EXISTING Task 8.2 contract
    ``dispatch_with_latency(plan)``: it runs the exact same single internal
    ``_dispatch`` implementation as ``dispatch(plan)`` and additionally
    returns a ``DispatchLatencyReport`` carrying one ``OrderLatency`` per
    dispatched sequence, each holding the SAME per-order
    ``core.order_engine.OrderExecutionResult`` the normal dispatch produced.
    Whenever that existing contract exists, this runner issues exactly ONE
    dispatch through it and collects the per-order results from the returned
    report (Task 3 asks for the actual result of that one Test execution —
    never a re-execution, never an invented verdict).
  * ``last_order_results`` is a list aligned 1:1 to the ``entries`` of the
    last successful run (queue order): each element is that order's real
    ``OrderExecutionResult`` or ``None`` when no per-order result exists for
    it (fail-closed). ``last_report`` is the measured dispatch's
    ``DispatchLatencyReport``, or ``None`` on the plain path. Neither value
    is ever displayed raw: the UI maps them through user-facing labels only.
  * Test doubles that expose only ``dispatch(plan)`` (no measured contract)
    keep the plain path unchanged — one dispatch, the integration's
    registered execution id — and carry ``last_order_results = None``.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple


class TestRunner:
    """
    Thin UI-side dry-run driver over the existing execution chain.

    With no Core import at module level and none at construction time, the
    runner itself is inert until a Test action actually calls ``run()``.
    """

    __test__ = False  # helper double imported by tests; not a pytest test class

    def __init__(self, dispatch_core: Any = None) -> None:
        """
        Build the runner around an optional Dispatch Core test-double.

        Args:
            dispatch_core: object exposing ``dispatch(plan)``. Tests inject
                a test-double here; production passes ``None`` and the real
                ``core.dispatch_core.DispatchCore`` is built lazily on the
                first real run (never at construction).
        """
        self._dispatch_core = dispatch_core
        self._integration: Optional[Any] = None
        self._run_counter = 0

        # Last successful run, kept for the caller (Task 3 consumes these).
        self.last_plan: Optional[Any] = None
        self.last_execution_id: Optional[str] = None
        self.last_result: Optional[Any] = None
        # Task 3: the per-order results of the last successful run, aligned
        # 1:1 to the entries passed to ``run()`` (queue order). Each element
        # is the real ``OrderExecutionResult`` of that order's own execution,
        # or ``None`` when no per-order result exists (fail-closed). ``None``
        # itself means "no measured path was used" (test-double dispatch).
        self.last_order_results: Optional[List[Optional[Any]]] = None
        self.last_report: Optional[Any] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        entries: List[Any],
        account: Any = None,
    ) -> Tuple[Any, str, Any]:
        """
        Run exactly one dry-run execution pass over ``entries`` for the
        explicitly supplied ``Account`` object.

        The ``Account`` object is provided by the caller (the UI layer:
        the ``Account`` of the existing active ``AccountRecord``). This
        runner never resolves, infers, fabricates or rebuilds an Account.

        Fail-closed validation, in order, before anything is built or
        dispatched:

          1. ``entries`` must be non-empty.
          2. All entries must share the same explicit ``account_id`` and
             ``broker_name`` (taken from the entries themselves, never
             inferred); mixed bindings are rejected.
          3. An ``Account`` object must actually be supplied.
          4. ``account.account_id`` must equal the entries' ``account_id``.

        Then the existing chain runs:

          5. ``build_execution_plan_from_selected_entries(...)`` builds the
             real ``ExecutionPlan`` (Block 0/1, unchanged).
          6. ``plan.accounts = [account]`` — the supplied Account object is
             attached, exactly as the existing integration layer (Blocks
             6/9/10) attaches resolved Account objects.
          7. The existing ``DispatchIntegration`` is created/reused.
          8. Exactly ONE dispatch is issued. A real ``DispatchCore`` runs
             the EXISTING ``dispatch_with_latency(plan)`` (Task 8.2 — the
             same single ``_dispatch`` implementation, so the per-order
             results of THIS execution are returned in its report); a
             test-double without that contract keeps the existing
             ``integration.dispatch(plan)`` path unchanged.
          9. The exact bridge triple ``(plan, execution_id, result)`` is
             returned: the plan bound to these entries, the execution id
             (the integration's registered id on the plain path, the
             runner's own ``exec-ui5-<n>`` on the measured path — never
             ``plan.plan_id``), and the ``DispatchResult`` from the dispatch.
             The per-order results of the run are exposed through
             ``last_order_results`` (aligned to ``entries``, Task 3).

        Args:
            entries: The pending ``QueueEntry`` objects of one Test action.
            account: The real ``models.account.Account`` object supplied by
                the UI (the active AccountRecord's existing Account). Never
                resolved here.

        Returns:
            ``(plan, execution_id, result)``.

        Raises:
            ValueError: empty selection, mixed Account/Broker binding, a
                missing Account, or a supplied Account whose ``account_id``
                does not match the entries (all fail-closed, before any
                dispatch); also raised when the dispatch did not register an
                execution (``integration.last_execution_id`` is ``None``).
        """
        if not entries:
            raise ValueError(
                "Test run skipped: no pending queue entries to execute "
                "(fail-closed, nothing is dispatched)"
            )

        first = entries[0]
        account_id = first.account_id
        broker_name = first.broker_name
        for entry in entries:
            if (
                entry.account_id != account_id
                or entry.broker_name != broker_name
            ):
                raise ValueError(
                    "Test run skipped: the selected entries mix accounts or "
                    "brokers; one Test action is exactly one single-batch "
                    "dispatch, no grouping/splitting is performed "
                    "(fail-closed)"
                )

        from models.account import Account

        if account is None:
            raise ValueError(
                "Test run skipped: no Account object was supplied for the "
                "selection (fail-closed, nothing is dispatched)"
            )
        if not isinstance(account, Account):
            raise ValueError(
                "Test run skipped: the supplied account is not a "
                "models.account.Account (fail-closed, nothing is dispatched)"
            )
        if account.account_id != account_id:
            raise ValueError(
                "Test run skipped: the supplied Account "
                f"({account.account_id!r}) does not match the entries' "
                f"account_id ({account_id!r}) — the resolved account must "
                "be the one bound to every selected entry (fail-closed, "
                "nothing is dispatched)"
            )

        # Lazy, first-run Core access: importing the existing bridge pulls
        # in the existing integration/core pieces. Nothing is imported when
        # the runner is merely constructed or toggled.
        from core.order_queue_adapter import (
            build_execution_plan_from_selected_entries,
        )

        self._run_counter += 1
        plan_id = f"ui5-test-{self._run_counter}"

        # Build the real plan exactly as the UI-5 chain does (Block 0/1,
        # unchanged), then attach the caller-supplied resolved Account
        # object — the documented integration-layer convention of Blocks
        # 6/9/10. With the Account attached, the real DispatchCore can
        # execute instead of fail-closing on an id-only binding.
        plan = build_execution_plan_from_selected_entries(
            entries,
            account_id=account_id,
            broker_name=broker_name,
            plan_id=plan_id,
        )
        plan.accounts = [account]

        # Exactly ONE dispatch per Test action. When the real ``DispatchCore``
        # exposes the existing Task 8.2 measured contract, it is the single
        # boundary used (the same single ``_dispatch`` implementation), so the
        # per-order ``OrderExecutionResult`` of each sequence is available in
        # the returned report (Task 3). A test-double without that contract
        # keeps the existing plain integration path unchanged.
        integration = self._ensure_integration()
        measured = callable(
            getattr(self._dispatch_core, "dispatch_with_latency", None)
        )
        if measured:
            result, report = self._dispatch_core.dispatch_with_latency(plan)
            execution_id = f"exec-ui5-{self._run_counter}"
            self.last_report = report
        else:
            result = integration.dispatch(plan)
            execution_id = integration.last_execution_id
            self.last_report = None

        if execution_id is None:
            raise ValueError(
                "dispatch did not issue an execution "
                "(dispatch_integration.last_execution_id is None); "
                "plan.plan_id is never used as an execution id"
            )

        self.last_order_results = self._order_results_for(entries, self.last_report)
        self.last_plan = plan
        self.last_execution_id = execution_id
        self.last_result = result
        return plan, execution_id, result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _order_results_for(self, entries, report):
        """
        Extract the per-order results of ONE dispatch, aligned 1:1 to the
        ``entries`` (queue order) of that successful run.

        The measured ``DispatchLatencyReport`` carries one ``OrderLatency``
        per dispatched sequence, each holding the SAME ``OrderExecutionResult``
        the normal ``_dispatch`` produced (a reference, never a copy). Each
        result owns its exact ``Order`` object, so a result is matched to a
        queue entry by object identity — never by index, sequence or text.

        ``None`` is returned when no report exists (plain/test-double path);
        within a report, an entry with no matching per-order result gets
        ``None`` (fail-closed: the caller must never guess a verdict).
        """
        if report is None:
            return None

        by_order = {}
        for record in getattr(report, "orders", None) or []:
            result = getattr(record, "execution_result", None)
            order = getattr(result, "order", None)
            if order is not None:
                by_order[id(order)] = result
        return [by_order.get(id(entry.order)) for entry in entries]

    def _ensure_integration(self) -> Any:
        """
        Build the existing DispatchIntegration once, around the existing
        DispatchCore (or the injected test-double). Any Core module import
        happens here, inside a real run — never at construction/import time.
        """
        if self._integration is not None:
            return self._integration

        if self._dispatch_core is None:
            from core.dispatch_core import DispatchCore

            self._dispatch_core = DispatchCore()

        from core.block5_task4 import DispatchIntegration

        self._integration = DispatchIntegration(dispatch_core=self._dispatch_core)
        return self._integration