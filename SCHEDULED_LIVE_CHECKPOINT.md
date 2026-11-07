# Scheduled Live checkpoint

Status: LIVE USER TEST SUCCESSFUL; OFFLINE REGRESSION PARTIAL (2026-11-07)

## Current goal, position, and next step

**Goal:** complete the Scheduled Live path from Apply through the selected
millisecond dispatch cadence, while preserving explicit approval, immutable
per-order/per-turn tickets, no automatic retry, an unchanged closed legacy
broker lock, and correct aggregate capacity checks. Offline fake-transport
tests may verify handoff; they do not establish real broker acceptance.

**Position:** the owner decision is that the user checks account purchasing
power, the application schedules and submits orders, and the broker makes the
final acceptance decision based on purchasing power. The application does not
allocate capacity proportionally across symbols or prices and does not combine
capacity from different groups. Existing M6-C and `get_buy_capacity` controls
remain unchanged. Capacity is evaluated separately for each
`(account, broker, nsc_id, side, fund, price)` group. New offline test coverage
checks two symbol/price groups and that one insufficient group is not offset by
another. `_capture_batch_snapshot` no longer calls `get_purchase_power`: the
returned value was unused, and local revalidation must not call a balance or
capacity endpoint or trigger Refresh.

The owner performed a real Scheduled Live user test and reports that seven
orders were registered at the broker. The UI showed seven successful
ticket responses and four UNKNOWN outcomes in the same run; UNKNOWN means
the app cannot determine whether the broker recorded those tickets. The
owner should reconcile those four against the broker's order list before
retrying. This confirms the user-facing seven-order test path, but does not
establish universal reliability or production readiness.

Per-ticket results are displayed on the page through a Qt queued signal.
The UI distinguishes successful responses, broker rejections, malformed
responses, NOT_SENT, and UNKNOWN without showing response payloads.
Independent verification after transfer: 14 tests passed in
test_live_batch_authorization.py and 6 ticket-result/signal tests passed
in test_scheduled_live_lock_contract.py. The complete
test_schedule_send_table.py run did not complete in this environment and
was interrupted; final regression coverage remains partial. No automated
live connection or order was run by the developer.

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
  BUY capacity is queried from `get_buy_capacity` independently for each exact
  account, broker, `nsc_id`, side, fund, and price group; requested quantity
  per turn is checked without multiplying by future turns. Groups are not combined or proportionally
  allocated across symbols or prices. The user's purchasing-power check and
  the broker's final acceptance decision are outside this application check.
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
  revalidation skips balance/capacity endpoints and does not trigger Refresh.
  `_capture_batch_snapshot` no longer calls `get_purchase_power`, whose result
  was unused. Capacity remains separate for every
  `(account, broker, nsc_id, side, fund, price)` group.
- `ui/order_configuration_page.py`: adds safe per-ticket trace/result capture,
  fixed stop reason mapping, snapshot bindings, and millisecond cadence preview.
  The queue now carries TSETMC `ins_code` separately from broker `nsc_id` for
  correct pre-arm lookup. Unrelated manual Live import edits in this shared
  file remain unstaged.
- Offline tests cover ledger transition atomicity, direct-transport bypass,
  separate symbol/price capacity groups including an insufficient group, and a
  Windows-compatible external socket denial guard.
- `ui/manual_live_trace.py`: permits narrowly typed scheduled correlation
  fields for ticket result logging.
- `ui/schedule_settings.py` and `ui/schedule_dispatcher.py`: comments/status
  adjustments only; no second scheduler was introduced.

## Verification and blockers

- Kilo reported `pytest -q test_schedule_send_table.py test_live_batch_authorization.py test_ui11_stage4_prearm_workflow.py -k "not runtime_starts_every_ticket"` => **36 passed, 1 deselected**.
- Independent verification reported `test_live_batch_authorization.py` => **12 passed**, and `test_ui11_stage4_prearm_workflow.py` => **1 passed**.
- Independent execution of the grouped suite on this host did not complete: it stalled/timed out during asyncio `ScheduledFireRuntime` event-loop startup. This differs from Kilo's reported grouped-suite result and remains unresolved.
- Reported focused Apply-to-fake-POST acceptance: `test_apply_two_orders_two_turns_posts_all_tickets` passed, including four ticket/order/turn correlations and cleanup. Related UNKNOWN, Stop, queue-change, and session-invalidation cases were separately reported passing.
- Focused offline checks cover insufficient grouped capacity, no balance/capacity endpoint or Refresh during local revalidation, and snapshot mutation; see the independently reported test totals above.
- Schedule summary preview now uses millisecond cadence on Live; countdown derives its next Live point from the same cadence. `end < start` is rejected.
- Definite 4xx/API rejection is not UNKNOWN; timeout, 5xx and malformed response remain UNKNOWN and cannot retry.
- The reported Apply-to-fake-POST test covers two orders x two turns and
  records four POSTs/outcomes. UNKNOWN, Stop, queue-change, and target-session
  invalidation were also reported passing separately. No claim is made that
  these offline checks establish live behavior.
- The owner performed the Live schedule test reported above. No automated live
  broker test was performed by this agent. Offline checks do not establish
  universal reliability or production readiness. The interrupted full
  `test_schedule_send_table.py` run remains unverified.

## Worktree preservation

The workspace may contain unrelated edits and untracked files; they were left
untouched. Changes described elsewhere in this checkpoint are prior work, not
part of this documentation-only update.
