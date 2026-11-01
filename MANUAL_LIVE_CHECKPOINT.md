# Manual Live investigation checkpoint — 2026-11-01

## Current position
Block 11.7-A is implemented and offline-tested within scope; owner-operated real-order qualification is not established. The owner reported confirmation followed by no visible broker order. Internal queue acceptance is not broker acceptance. The initial incident cause remains unproven.

This checkpoint supersedes older completion/readiness statements for this investigation. It does not enable production Live or scheduled Live.

## Work recorded so far
- Package 1: local JSONL logger, UUID trace IDs, health APIs and project-root default path.
- Package 2: UI/Engine/broker/sender correlation, pre-POST and HTTP/API/UNKNOWN events; offline fake-transport tests.
- Package 3: per-order confirmation and UI/preflight gate events, repeated-check stages and preservation of partial/unknown results.
- Package 4: per-order final UI result and prevention of duplicate events on display refresh.
- Agent-reported latest focused run: `python -m pytest -q test_manual_live_ui_gate_trace.py test_manual_live_trace_instrumentation.py test_manual_live_unknown.py test_live_preflight_t1_balance.py` => 51 passed. Compile and diff checks were reported successful. These results were not independently rerun by the architectural reviewer.
- Four reported baseline failures remain in `test_live_mode_feedback_optional.py`: `test_default_mode_is_dry_run_and_live_requires_confirmation`, `test_live_missing_preparation_fails_closed_before_prompt`, `test_snapshot_mutation_during_live_confirmation_aborts`, `test_live_is_rejected_while_schedule_is_active`. The agent reported reproduction against HEAD; this is not a declaration that the complete suite passes.

## Findings and evidence limits
- Missing sender trace/index parameters suppressed the transport event without necessarily preventing POST. Thus absence of that event did not prove absence of handoff.
- During instrumentation, an indentation defect reportedly placed sender submission under the logger exception branch; it was corrected. Its presence in the original owner-run version is unproven.
- A duplicate timeout event named transport_call_started was corrected to transport_result. One handoff must not appear as two.
- Independent source review found remaining gaps: logger health APIs have no confirmed UI consumer; some Engine early returns lack terminal results/reason codes; sanitizer allows arbitrary values under permitted keys; relative trace-directory overrides remain CWD-dependent; valid non-object JSON can become ERROR rather than UNKNOWN.
- Earlier package acceptance was based on agent reports and was premature for these remaining requirements. Passing focused tests does not prove complete branch coverage or broker receipt.

## Pending task A — clarify order outcomes
Status: OPEN. Do not mark complete until implementation, offline tests and independent review are recorded.
- Treat uninterpretable responses, including valid JSON arrays/null/scalars, as UNKNOWN without retry.
- Record fixed reasons and terminal Engine results for every pre-POST rejection, including SafetyGate/ack rejection.
- Preserve completed outcomes and existing permit/account/safety checks.
- Offline acceptance: fake responses for all malformed shapes; zero POST on pre-POST rejection; exactly one POST on ambiguous transport outcomes; correlated trace/index and terminal events.
Completion record: date / commit / changed files / exact test commands and results / reviewer findings: PENDING.

## Pending task B — make diagnostics reliable and visible
Status: OPEN. Do not mark complete until implementation, offline tests and independent review are recorded.
- Show active absolute log path and logger write failures through a nonblocking UI diagnostic consumer; logger/display failures must not affect order behavior.
- Restrict metadata values by type and allowed enum/range; reject arbitrary nested values and sensitive free text.
- Resolve configured relative TRADING_BOT_TRACE_DIR once against a documented stable base; trace_path must always return the effective absolute path.
- Offline acceptance: logger I/O failures and recovery, UI visibility, CWD changes with default/relative/absolute overrides, secret exclusion, unchanged fake-order outcomes.
Completion record: date / commit / changed files / exact test commands and results / reviewer findings: PENDING.

## Trace location and safety boundary
Default: `C:\Users\hp\Documents\Trading_bot\traces\manual_live_trace.jsonl`. TRADING_BOT_TRACE_DIR can override it at import. The actual owner-process environment/path has not been verified.
No broker login/refresh, network request, real order, Dry Run, Live run or scheduling was performed in the architectural review/documentation work. Agent test reports describe offline fakes only. No real-order qualification is authorized by this checkpoint. Git push is repository publication, not a broker request.

## Version-control boundary
This checkpoint documents work currently present in a dirty worktree. The documentation commit does not include or certify the uncommitted production/test changes. Preserve unrelated changes; commit task implementations separately after review.
