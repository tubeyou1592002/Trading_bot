# Task 8.1 — Existing Latency Instrumentation Audit

**Source of Truth:** `HEAD = 7f3bf00` (`docs: update project memory through Block 7`)
**Date:** 2026-09-18
**Scope:** Read-only audit. No code modifications.

---

## 1. Existing Timing Sources

| Symbol | File | Line(s) | Type | Value at runtime | Produced by |
|--------|------|---------|------|-----------------|-------------|
| `DispatchTrace.start_time` | `core/dispatch_core.py` | 100, 149, 230 | `datetime` (naive) | `datetime.now()` at dispatch entry | `DispatchCore.dispatch()` |
| `DispatchTrace.end_time` | `core/dispatch_core.py` | 101, 231, 246 | `Optional[datetime]` (naive) | `datetime.now()` at dispatch exit | `DispatchCore.dispatch()` (success & failure paths) |
| `Order.creation_date` | `models/order.py` | 24, 32-34 | `datetime` (UTC) | `datetime.now(timezone.utc)` on Order construction | `Order.__post_init__()` |
| `DispatchTiming.start_time` | `core/timing_contracts.py` | 88 | `datetime` (caller-supplied) | Provided by caller; validated as real datetime | External caller (Block 3 scheduling) |
| `DispatchTiming.end_time` | `core/timing_contracts.py` | 89 | `datetime` (caller-supplied) | Provided by caller; validated as real datetime | External caller (Block 3 scheduling) |
| `ExecutionPlan.created_at` | `core/dispatch_contracts.py` | 138 | `Optional[datetime]` | Always `None` at runtime (`execution_planner.py:233`) | `ExecutionPlanner.build_plan()` |
| `ExecutionRecord.created_at` | `core/execution_tracker.py` | 102 | `Optional[datetime]` | Always `None` (never set) | Not set anywhere |
| `ExecutionRecord.updated_at` | `core/execution_tracker.py` | 103 | `Optional[datetime]` | Always `None` (never set) | Not set anywhere |

**Clocks used:** `datetime.now()` (wall-clock, naive/local time) — used exclusively in `core/dispatch_core.py`. No `perf_counter`, `monotonic`, or `time.time` anywhere in the repository.

**No logging timestamps:** Logger calls in `dispatch_core.py` (lines 237, 530) include no timestamp in log output. No `logging.basicConfig` or formatter configuration exists in the repository.

---

## 2. What Can Be Measured Now

| What | How | Reliability |
|------|-----|-------------|
| **Dispatch start timestamp** | `DispatchTrace.start_time = datetime.now()` at `core/dispatch_core.py:149` | Measurable — wall-clock capture |
| **Dispatch end timestamp** | `DispatchTrace.end_time = datetime.now()` at `core/dispatch_core.py:231` (success) / `:246` (failure) | Measurable — wall-clock capture |
| **Dispatch wall-clock duration** | `end_time - start_time` (implicit; not computed) | Available in data but never computed or exposed |
| **Order creation timestamp** | `Order.creation_date = datetime.now(timezone.utc)` at `models/order.py:32` | Measurable — UTC wall-clock at Order construction |
| **trace_id** | `uuid4()` at `core/dispatch_core.py:148` | Always available; propagates to `DispatchResult.trace_id` |

**What cannot be measured now:**
- Per-order processing duration (no timing data in `OrderExecutionResult`)
- Per-stage timing (plan/binding resolution, instrument resolution, OrderEngine processing, broker invocation, response handling)
- Broker/API/network latency separation
- Per-account or per-broker timing distinction
- Elapsed duration computation anywhere in the codebase

---

## 3. Measurement Gaps

1. **No per-order timing:** `OrderExecutionResult` (`core/order_engine.py:26-36`) has no timing fields (success, sent, mode, order, broker_name, message, response only).
2. **Dispatch timing not surfaced in `DispatchResult`:** `_build_result` (`core/dispatch_core.py:465-511`) and `_fail_result` (`core/dispatch_core.py:513-527`) extract only `trace_id` and `results` from `DispatchTrace`; `start_time`/`end_time` are discarded.
3. **No latency/duration computation:** No code computes `end_time - start_time` or any elapsed time from the timestamps that *are* captured.
4. **No high-resolution timers:** Zero occurrences of `perf_counter`, `monotonic`, or `time.time` in the entire repository.
5. **No timestamps in log output:** Logger calls (`dispatch_core.py:237`, `:530`) dispatch events without timestamps; no logging formatter config exists.
6. **Dead timestamp fields in `ExecutionRecord`:** `created_at` and `updated_at` (`core/execution_tracker.py:102-103`) are defined but never populated by `register()`, `update_status()`, or `update_order_status()`.
7. **No broker/API timing:** `AgaahBroker` has request timeouts (`timeout=10`) but no timing measurements or latency tracking.
8. **No per-stage measurement:** No code measures duration of plan/binding resolution, account resolution, instrument resolution, OrderEngine execution, or broker invocation.
9. **No correlation of timing with orders/accounts/brokers:** No existing data associates timing with specific orders, accounts, or brokers.

---

## 4. Multi-Order / Multi-Account / Multi-Broker Correlation Findings

- `DispatchTrace` is per-dispatch, not per-order: one `start_time`/`end_time` pair covers all orders in a single dispatch. Multiple orders share the same timestamps.
- `OrderExecutionResult` has no timing fields, so per-order timing correlation is impossible.
- `trace_id` propagates from `DispatchCore` → `BrokerDispatchRequest` → Broker, but no timestamps accompany it.
- `ExecutionRecord.created_at`/`updated_at` are dead fields — they do not provide any multi-order/account/broker timing correlation.
- `ExecutionPlan.created_at` is always `None` at runtime (planner explicitly sets it to None); it is distinct from any dispatch-level timestamp.
- No existing data reliably distinguishes timing by account, broker, or instrument within a single dispatch or across dispatches.

---

## 5. Technical Risks / Accuracy Concerns

1. **Wall-clock vs monotonic:** `datetime.now()` is a wall-clock timestamp subject to system clock adjustments (NTP, manual changes). Not suitable for precise elapsed duration measurement. `monotonic`/`perf_counter` are not used anywhere.
2. **Mixed timezone awareness:** `Order.creation_date` uses `datetime.now(timezone.utc)` (UTC-aware), while all `DispatchTrace` timestamps are naive local time. Mixing these would be incorrect.
3. **Timing data discarded:** The only timestamps in the dispatch path (`DispatchTrace.start_time`/`end_time`) are never propagated to `DispatchResult`, meaning any consumer of `DispatchResult` cannot access dispatch duration.
4. **No logging timestamps:** If auditing relies on log output for timing, there are no timestamps in the logs — the repository does not configure `asctime` in any logger format.
5. **Timestamps are naive:** `datetime.now()` without `timezone` argument returns local time, which can be ambiguous during DST transitions and makes cross-system comparison difficult.

---

## 6. Required Inputs for Task 8.2

To implement Task 8.2 (Internal Dispatch Latency Analysis), the following inputs are required:

1. **Clock selection decision:** Choose between `datetime.now()` (wall-clock, currently used) vs `perf_counter()` / `time.monotonic()` (high-resolution monotonic). Cannot mix without clear rationale.
2. **Per-order timing mechanism:** Add timing fields to `OrderExecutionResult` or create a parallel timing capture path that records per-order start/end timestamps.
3. **Timing propagation to `DispatchResult`:** Modify `_build_result` and/or `_fail_result` in `DispatchCore` to include dispatch timing (start_time, end_time, duration) in the returned `DispatchResult`, or create a separate `DispatchLatencyReport` data structure.
4. **Per-stage measurement hooks:** Decide which stages to instrument (plan_item, plan_account, instrument_resolution, order_engine_execute, broker_invocation, response_handling) and add `measure_stage` context managers or equivalent.
5. **Broker/API timing separation:** Design for distinguishing application-side processing time from Broker execution/invocation time from API/network request-response time — currently impossible since no timing is captured at the Broker boundary.
6. **Multi-account/broker correlation:** Design for associating timing with specific orders, accounts, and brokers — currently no mechanism exists.
7. **Avoid changing execution behavior:** Any instrumentation must not alter the existing dispatch path, M6-A through M6-E gates, fail-closed behavior, or dry-run-only constraint.

---

**Files Inspected:**
- `core/dispatch_core.py` (entire file)
- `core/dispatch_contracts.py` (entire file)
- `core/execution_tracker.py` (entire file)
- `core/execution_planner.py` (entire file)
- `core/order_engine.py` (entire file)
- `core/timing_contracts.py` (entire file)
- `models/order.py` (entire file)
- `brokers/base.py` (entire file)
- `brokers/manager.py` (entire file)
- `brokers/agaah/broker.py` (first 100 lines + timeout pattern)
- `test_dispatch_core.py` (relevant test sections)
- `test_execution_tracker.py` (entire file)
- `test_execution_planner.py` (relevant sections)
- `test_block0_dispatch_contracts.py` (relevant sections)
- `test_timing_contracts.py` (entire file)
- `test_timed_dispatch_trigger.py` (entire file)
- `test_timed_dispatch_scheduler.py` (entire file)
- `AI_HANDOFF.md` (Block 8 section, roadmap summary)
- `AI_PROJECT_MEMORY.md` (latency-related sections)
- `DECISIONS.md` (contract definitions)

**Exact Findings:**
- 4 sources of timing data in the repository (DispatchTrace start/end, Order creation_date, DispatchTiming caller-supplied, ExecutionPlan/Record dead fields)
- 0 high-resolution timers anywhere
- 0 latency/duration computations
- 0 timestamps in log output
- Dispatch timing dropped from DispatchResult
- Dead fields in ExecutionTracker

**Tests Run:** `python -m pytest test_dispatch_core.py test_execution_tracker.py test_execution_planner.py test_block0_dispatch_contracts.py test_timing_contracts.py test_timed_dispatch_trigger.py test_timed_dispatch_scheduler.py`
**Results:** 95 passed, 0 failed. No test modifications required. No behavioral changes.

**Files Changed:** None. Audit was 100% read-only.