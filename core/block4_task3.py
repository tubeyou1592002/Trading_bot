"""
Block 4 — Task 3: Connect ExecutionPlan to the Dispatch path.

This module provides the final Block 4 connection: it takes the
``ExecutionPlan`` produced by Task 2 (``core.block4_task2``) and passes it
through the existing Dispatch path — the Block 2 ``DispatchCore.dispatch``
entry point — so the plan can be consumed/executed exactly like any other
``ExecutionPlan`` in the project. It is intentionally minimal and does not
modify any of:
 - TradingStateEventTrigger
 - ExecutionPlanner
 - DispatchCore (its internal architecture/behavior is untouched)
 - Any Block 3 or Block 5 components.

Behavior:
 - If ``execution_plan`` is None (the Task 2 trigger gate did not fire),
   the Dispatch Core is NOT called. A fail-closed "skipped dispatch"
   indication is returned.
 - If ``execution_plan`` is a real ``ExecutionPlan``, it is passed to the
   existing entry point ``dispatch_core.dispatch(execution_plan)`` and the
   resulting ``DispatchResult`` is returned.

Dispatch boundary (Block 4, connection level):

    Valid Event (Task 1)
        │
        ▼
    Planner -> ExecutionPlan (Task 2)
        │
        ▼
    Dispatch Core (Block 2)   <-- existing entry point used here
        │
        ▼
    existing M6-A … M6-E  (OrderEngine.prepare / execute)
        │
        ▼
    Broker

Explicitly OUT of scope for this module:
  - Any scheduler, timer, polling loop, or real clock.
  - Any broker implementation, broker adapter, or broker API call.
  - Any new validation or order-generation logic.
  - Any modification to Dispatch Core, the Planner, Block 3, or Block 5.
  - Any new architectural layer.
"""

from __future__ import annotations

from typing import Optional

from core.dispatch_contracts import DispatchResult, ExecutionPlan


def connect_plan_to_dispatch(
    execution_plan: Optional[ExecutionPlan],
    dispatch_core: "DispatchCore",
) -> dict:
    """
    Connect the Task 2 ``ExecutionPlan`` to the existing Dispatch path.

    Args:
        execution_plan: The ``ExecutionPlan`` produced by Task 2's
            ``connect_trigger_to_planner(...)["execution_plan"]``. ``None``
            means the trigger gate did not fire and nothing is dispatched.
        dispatch_core: The existing Block 2 ``DispatchCore`` instance whose
            ``dispatch(plan)`` entry point is used unchanged.

    Returns a dict with the result:
      {
          "dispatched": bool,                    # True only if dispatch() ran
          "execution_plan": ExecutionPlan | None,  # plan passed to dispatch
          "dispatch_result": DispatchResult | None,  # dispatch() output
          "dispatch_called": bool,               # Whether dispatch() was invoked
      }
    """
    if execution_plan is None:
        # Gate did not fire (fail-closed) — the Dispatch Core is not invoked.
        return {
            "dispatched": False,
            "execution_plan": None,
            "dispatch_result": None,
            "dispatch_called": False,
        }

    # Pass the plan through the existing Dispatch Core entry point unchanged.
    dispatch_result: DispatchResult = dispatch_core.dispatch(execution_plan)

    return {
        "dispatched": True,
        "execution_plan": execution_plan,
        "dispatch_result": dispatch_result,
        "dispatch_called": True,
    }