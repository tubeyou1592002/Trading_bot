# Scheduled Live checkpoint

Status: PARTIAL / NOT READY FOR ARCHITECTURAL REVIEW (2026-11-06)

## Current goal, position, and next step

**Goal:** complete the Scheduled Live path from Apply through the selected
millisecond dispatch cadence, while preserving explicit approval, immutable
per-order/per-turn tickets, no automatic retry, an unchanged closed legacy
broker lock, and correct aggregate capacity checks. Offline fake-transport
tests may verify handoff; they do not establish real broker acceptance.

**Position:** the reported offline Apply-to-fake-POST acceptance covers two
orders across two turns (four distinct tickets), UNKNOWN after a started POST,
Stop, queue mutation, and target-session invalidation. The ticket ledger and
broker-owned handoff are in place. BUY capacity is checked against Agaah's
existing `get_buy_capacity` endpoint before authorization is issued. Its check
is now excluded from local authorization revalidation, so that revalidation
does not call the endpoint or trigger refresh. The latest focused verification
reported **3 passed in 0.66s** for insufficient capacity, local revalidation
without endpoint/refresh, and snapshot mutation. These are agent-reported
results, not a fresh run in this documentation update.

**Remaining blocker:** the current BUY aggregation groups requests by account,
broker, instrument, side, fund, and price. It proves the repeated-order case
for identical endpoint parameters, but it does not yet prove account-wide
capacity when one account's scheduled queue contains different instruments or
prices that each reuse the same available fund. The next implementation task
is to define and test that account-wide aggregation using the existing broker
capacity contract, without introducing endpoint calls during local
revalidation. Keep the change limited to this gap and its offline tests.

**After that:** rerun the focused Scheduled Live suite and review the complete
diff. Only then decide whether the offline implementation is ready for
architectural review. No real broker qualification or production-readiness
claim is implied.

The owner selected the existing Dispatch interval in milliseconds as the
scheduled Live cadence. The current arithmetic is inclusive-start with an
inclusive end ceiling: `floor((end - start) / interval_ms) + 1`. Thus an end
exactly on a cadence point is included; a final remainder shorter than one
interval does not create a turn at the end. The other Schedule interval field
is whole seconds and continues to feed the existing Block 3 schedule display.

## Source findings

- `ui/order_configuration_page.py` already captures the queue, prepares M6,
  asks for explicit approval, requests a full reserved ticket table, and arms
  `ScheduledFireRuntime` before starting countdown.
- `core/live_order_authorization.py` has immutable batch authorization,
  one ticket per order/turn, and a single-use ticket ledger.
- `brokers/agaah/broker.py` defaults `live_trading_enabled` to false. Manual
  prepared submission requires this global lock to remain closed, while the
  normal/legacy Live APIs require it open. Opening it globally would either
  weaken legacy paths or break manual Live.
- `core/order_engine.py` M6-B/C/D/E checks each order independently. Aggregate
  SELL capacity is checked before authorization with the existing
  `get_sell_capacity` contract and total requested quantity across turns.
  BUY capacity is queried from `get_buy_capacity` for each exact account,
  broker, instrument, side, fund, and price group; requested quantity is
  multiplied by planned turns. This does not yet prove account-wide capacity
  across distinct prices or instruments using the same funds.
- No evidence shows architectural approval of a new broker capability or
  a capacity/limit for safe ticket-table size. Do not infer approval from
  tests or this checkpoint.

## Partial implementation in this worktree

- `brokers/agaah/broker.py`: scheduled reserved tickets may pass the internal
  prepared async transport while the global/legacy Live lock stays closed;
  ticket authorization and immutable payload binding are rechecked. Manual
  Live and `place_order` were not intentionally changed.
- `core/live_order_authorization.py`: serializes UNKNOWN stop and POST-start
  transitions under one lock. A ticket is preserved only after actual handoff.
- `ui/scheduled_fire_runtime.py`: records transport-start timing and classifies
  definite API rejections separately from ambiguous outcomes.
- `ui/live_order_gate.py`: enforces grouped aggregate BUY and SELL exposure.
  BUY capacity is checked during readiness only; local authorization
  revalidation skips the endpoint and does not refresh credentials.
- `ui/order_configuration_page.py`: adds safe per-ticket trace/result capture,
  fixed stop reason mapping, snapshot bindings, and millisecond cadence preview.
  The queue now carries TSETMC `ins_code` separately from broker `nsc_id` for
  correct pre-arm lookup. Unrelated manual Live import edits in this shared
  file remain unstaged.
- Offline tests cover ledger transition atomicity, direct-transport bypass,
  aggregate capacity, and a Windows-compatible external socket denial guard.
- `ui/manual_live_trace.py`: permits narrowly typed scheduled correlation
  fields for ticket result logging.
- `ui/schedule_settings.py` and `ui/schedule_dispatcher.py`: comments/status
  adjustments only; no second scheduler was introduced.

## Verification and blockers

- Baseline before edits: `python -m pytest -q test_schedule_send_table.py test_live_batch_authorization.py test_ui11_stage4_prearm_workflow.py -k "not runtime_starts_every_ticket"` => 29 passed, 1 deselected.
- Reported focused Apply-to-fake-POST acceptance: `test_apply_two_orders_two_turns_posts_all_tickets` passed, including four ticket/order/turn correlations and cleanup. Related UNKNOWN, Stop, queue-change, and session-invalidation cases were separately reported passing.
- Latest reported BUY-capacity selection: `test_live_batch_authorization.py` targeted cases => 3 passed in 0.66s, covering insufficient grouped capacity, no endpoint/refresh during local revalidation, and snapshot mutation. These results were not rerun while updating this checkpoint.
- Schedule summary preview now uses millisecond cadence on Live; countdown derives its next Live point from the same cadence. `end < start` is rejected.
- Definite 4xx/API rejection is not UNKNOWN; timeout, 5xx and malformed response remain UNKNOWN and cannot retry.
- The reported Apply-to-fake-POST test covers two orders x two turns and
  records four POSTs/outcomes. UNKNOWN, Stop, queue-change, and target-session
  invalidation were also reported passing separately. A complete final
  regression run after all current edits, all resource-close exits, and the
  account-wide BUY-capacity case remain unverified.
- This is not complete and is not yet approved for architectural review. No real broker network, authentication, order, Live run, or real schedule was performed. No production-readiness claim is made.

## Worktree preservation

The workspace was already dirty before this task. Unrelated edits and untracked
files were left untouched. This commit includes the `ins_code`/`nsc_id`
separation needed by the Scheduled Live pre-arm path. Other symbol diagnostics,
limit-hint work, temporary review files, and unrelated manual Live import edits
remain outside the commit.
