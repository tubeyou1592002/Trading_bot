# Scheduled Live checkpoint

## Current diagnostic status

The diagnostic table with Block 8, Block 11, and Agah evidence, and the
Persian XLSX export are implemented offline. Kilo reported that three selected
export tests and the scheduled report test passed; these tests were not
independently rerun for this documentation update. Live behavior and the UI
visual check remain pending; offline results do not establish live behavior.

Status: PARTIAL / NOT READY FOR ARCHITECTURAL REVIEW (2026-11-15)

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

The ticket ledger and broker-owned handoff are in place. Offline fake-transport
tests and reported results do not establish real broker acceptance. No live
test or production-readiness claim is made.

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
  account, broker, `nsc_id`, side, fund, and price group; requested quantity is
  multiplied by planned turns. Groups are not combined or proportionally
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
- No live broker test, authentication, order, Live run, or real schedule was
  performed. Offline checks do not establish real acceptance or production
  readiness. The independent grouped-suite startup timeout remains unresolved.

## Worktree preservation

The workspace may contain unrelated edits and untracked files; they were left
untouched. Changes described elsewhere in this checkpoint are prior work, not
part of this documentation-only update.

## Scheduled Live order-log behavior

The lower existing OrderLog is the sole UI for scheduled ticket rows. A row is
appended when the actual POST starts, using the real local timestamp and safe
account display name/symbol. Completion updates only that row's description via
its private ticket key. Ticket IDs and payloads are never rendered. The
temporary upper scheduled-ticket results table has been removed.

Latest focused offline verification: `test_scheduled_live_lock_contract.py` —
26 passed. This is not a full regression pass and does not establish broker
acceptance or production readiness.

## Cross-broker latency measurement roadmap (owner-approved direction)

This roadmap records the owner's approved measurement requirements and next
steps. These are not claims that the design or implementation is complete.
Any additional architecture choices remain subject to explicit owner approval.

### Approved measurement contract

- Use monotonic time for duration measurement, with nanoseconds (`ns`) as the
  base duration unit. Keep wall-clock timestamps separate for human-readable
  event time; do not use wall-clock values in duration calculations.
- Provide one shared table across brokers. A shared event vocabulary may
  include a milestone such as “registered in trading core”; an adapter may
  normalize its own native message to that event only when there is sufficient
  evidence. Do not assume that broker-specific messages are equivalent.
- Correlate only through trustworthy identifiers and mappings, such as order,
  ticket, turn, or decision identifiers. Never guess a match from symbol or
  timestamp alone.
- Record the application's monotonic-nanosecond event-receipt time. Keep any
  broker-side timestamp separate: it uses an external clock and must not be
  subtracted from the application's clock to claim latency.
- Optional broker feedback/capability is genuinely optional. If a broker does
  not provide a message or capability, leave that value empty/unavailable and
  report that the stage is incomplete; do not fail the entire report.
- Keep preparation, submission, API response, and OMS latency as independent
  stages, each labeled with its source and clock. Excel output must contain
  numeric values, with separate rows for each order/turn and each event.

### Current status and owner decisions

**Stage 1 — measurement contract and decisions: COMPLETE.** The following
decisions are explicit; completion means this planning stage is settled, not
that the design has been implemented or approved as a complete architecture:

1. Preparation is defined using the existing internal Block 8 stages. Keep
   `plan_item`, `plan_account`, `instrument_resolution`, and
   `order_engine_path` as separate stages. Do not collapse them into an
   ambiguous preparation total.
2. The broker's initial API response and the `AcceptedByBourse` event are
   separate milestones. One must not be treated as evidence of the other.
3. Multi-broker feedback capability belongs in a separate service/adapter;
   do not change the base `Broker` contract for feedback.
4. The approved measurement contract above applies: monotonic-nanosecond
   durations, separate wall-clock timestamps, monotonic event-receipt time,
   trustworthy correlation without guessing, and optional missing/unavailable
   values when a broker does not provide feedback.

### Existing evidence and known unknowns

These are current-state findings, not claims of complete implementation or
verified live behavior:

| Broker / component | Evidence currently identified | Unknown / limitation |
| --- | --- | --- |
| Agah | OMS action-5 event receipt is captured with a monotonic timestamp at transport and correlated by exact registered decision/account scope through the feedback service, preserving legacy feedback. | Full live latency behavior is unverified. The Agah API response remains Block 8 broker-call timing; it is not represented as a normalized API-response event when safe identity is unavailable. |
| Mofid | An authentication adapter exists. | Order feedback is unsupported/unknown; do not infer feedback support or trustworthy correlation from the authentication adapter. |
| Base `Broker` | No feedback contract is present in the base Broker. | Keep it unchanged; cross-broker feedback remains the responsibility of the separately scoped service/adapter. |

### Roadmap — next steps

**Stage 2 — instrumentation and reporting: IMPLEMENTED OFFLINE.** The
instrumentation and data paths are implemented and covered by offline tests:

1. A normalized feedback contract module provides the shared feedback model.
2. Agah OMS action-5 event monotonic receipt is captured at transport and
   correlated through the service by exact registered decision/account scope;
   legacy feedback is preserved.
3. Block 8 reports are retained in periodic turn results and consumed by the
   diagnostic table through GUI-thread refresh.
4. One shared eight-column Persian diagnostic table renders manual Block 8,
   periodic Block 8, Block 11, and normalized Agah OMS feedback only when
   correlation is exact.
5. Excel provides Persian summary/detail schemas, numeric nanosecond duration
   cells, consistent account aliases, and privacy filtering.

Latest exact verified offline groups after the normalized OMS UI test
correction: `66 passed` for the contract/Agah/service group, `70 passed` for
the UI6/trace/export group, `79 passed` for periodic dispatch, and `26 passed`
for scheduled Live. These are the group results; the recorded commands are:

- Contract/Agah/service group: `pytest -q test_cross_broker_latency_contract.py test_cross_broker_latency_service.py`
- UI6/trace/export group: `pytest -q test_cross_broker_latency_ui.py`
- Periodic dispatch group: `pytest -q test_periodic_dispatch.py`
- `pytest -q test_scheduled_live_lock_contract.py`

These are reported offline results; they do not establish live behavior. The
following limitations remain explicit: Mofid order feedback is
unsupported/unknown; an Agah API response is kept as Block 8 broker-call timing
and is not emitted as a normalized API-response event if safe identity is
unavailable; no live/network/order qualification has occurred; and app visual
verification has not been performed. `git diff --check` was not independently
run.

**Stage 3 — UI/Excel implementation and offline testing: IMPLEMENTED OFFLINE.**
The approved diagnostic table and Excel export action are implemented. Kilo
reported three selected export tests and the scheduled report test passing;
they were not independently rerun for this documentation update. Practical
owner confirmation is pending; visual and live verification remain pending.
Exported nanosecond cells
retain integer values, while external wall-clock timestamps remain separately
labeled and are not used in duration arithmetic. Missing values remain blank.

**Stage 4 — multi-broker offline test coverage: IMPLEMENTED.** Fake-adapter
tests cover Agah-like exact OMS action-5 feedback and a Mofid-like unavailable
feedback case while Block 8 remains renderable. This is test coverage using a
fake adapter, not real Mofid feedback support. Practical owner confirmation
remains pending; no live, network, or order qualification is claimed.

**Stage 5 — live qualification: PARTIALLY PERFORMED; NOT COMPLETE.** The owner
ran burst scheduled Live on 2026-11-15 using `python -m ui` from this exact
worktree. This is observed qualification activity, not a successful end-to-end
feedback qualification. The workbook exported during that investigation had
presentation defects, and
the exact application feedback path remains unverified with prior failed
evidence. No full end-to-end real-broker timing verification is claimed.

### 2026-11-15 investigation evidence (observations, not root-cause findings)

- The owner's exported `scheduled-live-trace3.xlsx` has eight populated Block
  11 ticket rows and a ninth empty ticket row. HTTP round-trip values are
  numeric; all `POST تا NATS` values are empty; the status column is blank;
  summary columns are mislabeled/misaligned because Block 11 values occupy
  Block 8-style headers such as `plan_item`; and `duration_5` / broker-call
  summary columns are empty. Workbook presentation is faulty; these observations
  do not by themselves locate the feedback failure.
- In the Agah UI, four active orders were visibly marked `ثبت شده در بورس`.
  No payload or identity was inspected for correlation. Do not claim these
  orders map to the eight tickets or any particular ticket.
- Chrome DevTools showed Agah UI requests `GET /api/v1/Pusher/message-types`
  and `GET /api/v1/pusher/nats`, both HTTP 200. This proves browser HTTP calls
  only; it does not prove the application established its own NATS TCP
  connection or subscription.
- Previously observed app log: `OrderFeedbackService feedback startup failed
  (error_type=RuntimeError)`. A safe diagnostic for `/Pusher/message-types`
  indicated top-level/data dictionaries with numeric keys including `100`,
  but no `groups`. The current parser expects `groups` or a `messageTypes`
  list, then a dictionary with integer `code=100`. This is a concrete suspected
  contract mismatch, not today's same-session re-verification and not a proven
  root cause.
- A code-level race candidate is that OMS events arriving before the HTTP
  `decisionId` is bound are discarded by
  `AgahOrderCorrelator._handle_oms_event` when untracked. This is a candidate,
  not an observed cause.

Remaining stages to distinguish are UI bootstrap contract parsing, app-side
NATS connect/subscribe, native message decode, `decisionId` registration and
correlation, scheduled-runtime correlation, and final UI/Excel projection.

### Ordered next steps

1. Capture safe app-side lifecycle status for each bootstrap, parse, connect,
   subscribe, disconnect, message, decode, and correlation step. Record status
   only; do not log secrets or payloads.
2. Verify the permitted actual response schema and adapt the parser only to
   observed evidence; create offline fixtures from its redacted shape.
3. Safely buffer narrowly scoped unmatched OMS decision IDs for a bounded
   interval, then correlate only exact account/broker/decision identities.
4. Ensure the scheduled runtime's HTTP response `decisionId` and NATS receipt
   are joined using monotonic nanoseconds only within the same clock domain;
   preserve absent/unknown values.
5. Make per-ticket outcome state explicit, including all planned, unstarted,
   and started tickets, without blank rows.
6. Separate Block 8 and Block 11 summary columns and use accurate Persian
   headers.
7. Run offline tests, then owner-supervised live verification.

Preserve the approved time contract: monotonic-nanosecond durations, separate
wall-clock timestamps, no matching by symbol/time, and optional multi-broker
feedback. These steps do not presume a new architecture. The Kilo worktree
remains dirty with extensive prior changes; no commit or push was done.

Stage 1 decisions do not assert a complete implementation. No live broker
behavior or production readiness is claimed; later implementation details not
settled above remain subject to their applicable approval.

## 2026-11-15 — ترتیب مصوب بررسی بازخورد بورس/OMS آگاه

این ترتیب بررسی جایگزین ترتیب قبلی roadmap است که با instrumentation کد یا
تغییر parser شروع می‌شد. یافته‌ها و پیشنهادهای پیشین برای حفظ سابقه باقی
می‌مانند و تا تأیید با شواهد جدید، تاریخی/تأییدنشده‌اند؛ هیچ‌کدام علت قطعی
یا مجوز تغییر implementation نیستند.

### چک‌لیست مراحل، به ترتیب

1. **مشاهده امن کلاینت وب آگاه:** با حضور مالک و در حالی که خود او وارد حساب
   است، در Chrome DevTools فقط metadata/status امن درخواست‌ها و ساختار پیام‌ها
   و رویدادهای لازم را بررسی کنید تا معلوم شود کلاینت‌های مرتبط با کارگزاری
   چگونه از ثبت در بورس مطلع می‌شوند و تأییدها یا وضعیت‌های برگشتی چگونه
   ظاهر می‌شوند. هیچ credential، cookie، token، داده شخصی یا payload حساس خام
   را نخوانید، کپی یا ثبت نکنید. سفارش ایجاد یا لغو نکنید و هیچ اقدام حسابی
   را فعال نکنید. برای هر مشاهده endpoint، method، status، نوع transport، شکل
   schema پاک‌سازی‌شده، شناسه‌های event/type و نام شناسه‌های correlation را
   ثبت و موارد نامعلوم را صریحاً مشخص کنید. endpointهای HTTP/bootstrap مرورگر
   مانند `message-types` و `pusher/nats` را از اتصال NATS خود Trading_bot جدا
   بدانید: HTTP 200 در مرورگر اثبات اتصال یا subscription برنامه نیست.
2. **قرارداد پروتکل مشاهده‌شده:** فقط از مستندات رسمی/عمومی مجاز و مشاهدات
   DevTools یک قرارداد مبتنی بر شواهد استخراج کنید. هر گزاره را observed،
   inferred یا unknown برچسب بزنید و منبع امن آن را ثبت کنید؛ حدس نزنید.
3. **تطبیق با کد فعلی:** هر جزء قرارداد مشاهده‌شده را با مسیر کد مربوط به
   parser، transport bootstrap/connect/subscribe، decoder، event correlation،
   feedback service و trace/UI/Excel تطبیق دهید. برای هر جزء، مسیرهای کد و
   وضعیت match، mismatch یا unverified را ثبت کنید؛ استاندارد بودن کد فعلی را
   پیش‌فرض نگیرید.
4. **ردیابی چرخه رویداد:** تنها پس از مراحل بالا، چرخه رویداد را دنبال کنید
   و مرز دقیق absent، lost، mismatched یا not projected بودن پیام را مشخص
   کنید. فقط diagnostics امن چرخه حیات، بدون اسرار یا payload حساس، جمع‌آوری
   کنید؛ نبود شواهد را علت قطعی تلقی نکنید.
5. **علت و طرح اصلاح کوچک:** علت را با شواهد و عدم‌قطعیت‌های باقی‌مانده و یک
   طرح اصلاح محدود ارائه کنید. تا توافق شواهد و بازبینی مالک، هیچ
   implementation انجام نشود.

### معیار خروج

- هر مرحله به ترتیب با شواهد امن و موارد unknown مستند شده باشد؛ قرارداد و
  تطبیق کد شامل منبع، مسیر کد و وضعیت‌های فوق باشند.
- مرز مسئله با شواهد مشخص شده باشد یا صریحاً unverified و blocker آن ثبت شود؛
  مشاهده مرورگر به‌جای اثبات اتصال برنامه استفاده نشود.
- علت و طرح کوچک برای بازبینی مالک ارائه و پیش از هر implementation تأیید
  شوند؛ در نبود شواهد کافی، بررسی باز بماند.

### قالب ثبت شواهد

- تاریخ/مرحله و منبع مجاز: …
- endpoint / method / status و نوع transport، در صورت کاربرد: …
- شکل schema پاک‌سازی‌شده، شناسه event/type و نام شناسه correlation: …
- گزاره و برچسب observed / inferred / unknown، با ارجاع به منبع امن: …
- مسیر کد و وضعیت match / mismatch / unverified، در صورت کاربرد: …
- مرز چرخه حیات و diagnostics امن، یا unknown / blocker: …
- نتیجه، عدم‌قطعیت و وضعیت بازبینی مالک: …

این بخش صرفاً برنامه بررسی است: در این تغییر هیچ کد، تست یا عملیات زنده حساب
انجام نمی‌شود و commit/push مجاز نیست.
