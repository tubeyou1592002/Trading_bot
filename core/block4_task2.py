"""
Block 4 — Task 2: Connect TradingStateEventTrigger to ExecutionPlanner.

This module provides the connection between the Trading State Event Trigger
and the existing Execution Planner (Block 1). It is intentionally minimal
and does not modify any of:
 - TradingStateEventTrigger
 - ExecutionPlanner
 - DispatchCore
 - Any Block 3 or Block 5 components.

Behavior:
 - If TradingStateEventTrigger.evaluate(now) == False:
     ExecutionPlanner.build_plan() is NOT called.
     Returns a fail-closed indication that the event did not fire.
 - If TradingStateEventTrigger.evaluate(now) == True:
     The provided planner instance's build_plan() is called with the
     LogicalOrderInstruction.
     The resulting ExecutionPlan is returned.
"""

from __future__ import annotations

from datetime import datetime

from core.dispatch_contracts import ExecutionPlan
from core.trading_state_event_trigger import TradingStateEventTrigger


def connect_trigger_to_planner(
    trigger: TradingStateEventTrigger,
    planner: "ExecutionPlanner",
    instruction: "LogicalOrderInstruction",
    now: datetime,
) -> dict:
    """
    Connect a TradingStateEventTrigger to an existing ExecutionPlanner.

    Args:
        trigger: The TradingStateEventTrigger to evaluate.
        planner: The existing ExecutionPlanner instance (not created here).
        instruction: The LogicalOrderInstruction to plan.
        now: The evaluation datetime.

    Returns a dict with the result:
      {
          "fired": bool,              # True if trigger allowed passage
          "execution_plan": ExecutionPlan | None,  # Plan if fired, else None
          "trigger_result": bool,     # Result of trigger.evaluate(now)
          "planner_called": bool,     # Whether planner.build_plan() was invoked
      }
    """
    trigger_result = trigger.evaluate(now)

    if not trigger_result:
        # Event did not fire — fail-closed, do not invoke planner.
        return {
            "fired": False,
            "execution_plan": None,
            "trigger_result": False,
            "planner_called": False,
        }

    # Event fired — proceed to build the ExecutionPlan via the provided planner.
    execution_plan: ExecutionPlan = planner.build_plan(instruction)

    return {
        "fired": True,
        "execution_plan": execution_plan,
        "trigger_result": True,
        "planner_called": True,
    }