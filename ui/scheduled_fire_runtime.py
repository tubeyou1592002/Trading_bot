"""Prestarted asyncio runtime for one immutable scheduled-send table."""

import asyncio
import threading
import math


ASYNC_ORDER_TIMEOUT_SECONDS = 10
MAX_ACCOUNT_CONNECTOR_LIMIT = 512


def required_account_connections(table, authorization, *, timeout_seconds=ASYNC_ORDER_TIMEOUT_SECONDS):
    """Worst-case in-flight requests per account from cadence and HTTP timeout."""
    interval = authorization.snapshot.schedule.interval_ms / 1000.0
    overlapping_turns = min(
        authorization.snapshot.schedule.planned_turns,
        max(1, math.ceil(timeout_seconds / interval)),
    )
    orders_per_account = {}
    for ticket in table.tickets:
        key = (ticket.account_id, ticket.broker_name)
        orders_per_account.setdefault(key, set()).add(id(ticket.queue_entry))
    return {key: len(orders) * overlapping_turns
            for key, orders in orders_per_account.items()}


class ScheduledFireRuntime:
    """Own one loop, account-private transports, and one task per ticket."""

    def __init__(self, *, monotonic_clock=None, on_complete=None):
        import time
        self._clock = monotonic_clock or time.monotonic
        self._on_complete = on_complete
        self._session_factory_calls = 0
        self._task_factory_calls = 0
        self._ready = threading.Event()
        self._loop = None
        self._startup_error = None
        self._thread = threading.Thread(
            target=self._run_loop, name="scheduled-fire-loop", daemon=True
        )
        self._stopped = threading.Event()
        self._cancelled = False
        self._closing = False
        self._tasks = {}
        self._payloads = {}
        self._ticket_ids = set()
        self._ticket_refs = {}
        self._started = set()
        self._outcomes = {}
        self._transports = {}
        self._brokers = {}
        self._lock = threading.Lock()
        self._thread.start()
        if not self._ready.wait(timeout=5):
            raise RuntimeError("Scheduled event loop startup timed out")
        if self._startup_error is not None:
            raise RuntimeError("Scheduled event loop failed to start") from self._startup_error
        if self._loop is None:
            raise RuntimeError("Scheduled event loop failed to start: thread returned no loop")

    def _run_loop(self):
        loop = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
        except BaseException as exc:
            self._startup_error = exc
            self._ready.set()
            self._stopped.set()
            return
        self._ready.set()
        try:
            loop.run_forever()
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        finally:
            loop.close()
            self._stopped.set()

    def _call(self, coroutine, timeout=15):
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        return future.result(timeout=timeout)

    async def _install(self, table, authorization, brokers, session_factory):
        self._authorization = authorization
        from core.live_order_authorization import prepared_fingerprint
        armed = authorization.ticket_ledger.validate_armed_table(
            authorization, table
        )
        if not armed.allowed:
            raise RuntimeError(armed.reason)
        self._brokers = dict(brokers)
        capacities = required_account_connections(table, authorization)
        if set(capacities) != set(self._brokers):
            raise RuntimeError("Scheduled table account destinations do not match prepared brokers")
        for key, broker in self._brokers.items():
            capacity = capacities.get(key, 0)
            if capacity > MAX_ACCOUNT_CONNECTOR_LIMIT:
                raise RuntimeError(
                    f"Unsupported schedule cadence: account {key[0]} requires {capacity} "
                    f"concurrent connections, above supported limit "
                    f"{MAX_ACCOUNT_CONNECTOR_LIMIT}"
                )
            self._session_factory_calls += 1
            self._transports[key] = await broker.prepare_async_order_transport(
                key[0], session_factory, connector_limit=capacity
            )
        for ticket in table.tickets:
            key = (ticket.account_id, ticket.broker_name)
            if key not in self._transports:
                raise RuntimeError("Ticket has no account-bound prepared transport")
            if (ticket.ticket_id in self._ticket_ids
                    or ticket.ticket_id not in authorization.ticket_ledger._reserved
                    or ticket.prepared_fingerprint != prepared_fingerprint(
                        ticket.prepared_order
                    )):
                raise RuntimeError("Scheduled table contains an unreserved/changed ticket")
            self._ticket_ids.add(ticket.ticket_id)
            self._ticket_refs[ticket.ticket_id] = ticket
            payload = ticket.payload
            self._payloads[ticket.ticket_id] = payload
            self._tasks[ticket.ticket_id] = asyncio.create_task(
                self._fire_ticket(ticket, key, payload),
                name=f"scheduled-ticket-{ticket.ticket_id}",
            )
            self._task_factory_calls += 1
        return len(self._transports), len(self._tasks)

    def _capture_outcome(self, task):
        ticket_id = task.get_name().removeprefix("scheduled-ticket-")
        if ticket_id is None or ticket_id in self._outcomes:
            return
        try:
            result = task.result()
        except asyncio.CancelledError:
            result = None
        except Exception as exc:
            result = exc
        self._outcomes[ticket_id] = result
        if self._on_complete is not None:
            self._loop.call_soon(self._on_complete, self._ticket_refs[ticket_id], result)

    async def _fire_ticket(self, ticket, key, payload):
        delay = ticket.due_mono - self._clock()
        if delay > 0:
            await asyncio.sleep(delay)
        if self._clock() < ticket.due_mono:
            await asyncio.sleep(ticket.due_mono - self._clock())
        if self._cancelled:
            return None
        self._started.add(ticket.ticket_id)
        broker = self._brokers[key]
        transport = self._transports[key]
        # Broker-owned hand-off checks account ownership and its current Live
        # lock immediately before the HTTP request. No M6/readiness/DB/ledger.
        try:
            result = await broker.submit_from_async_prepared_transport(
                transport, ticket.account_id, payload,
                ticket=ticket, authorization=self._authorization,
                broker=broker,
            )
        except Exception as exc:
            result = exc
        self._outcomes[ticket.ticket_id] = result
        if self._on_complete is not None:
            try:
                self._loop.call_soon(self._on_complete, ticket, result)
            except Exception:
                pass
        return result

    def arm(self, table, authorization, brokers, session_factory):
        if self._tasks or self._transports:
            raise RuntimeError("Scheduled runtime is already armed")
        capacities = required_account_connections(table, authorization)
        excessive = [(key, value) for key, value in capacities.items()
                     if value > MAX_ACCOUNT_CONNECTOR_LIMIT]
        if excessive:
            key, capacity = max(excessive, key=lambda item: item[1])
            raise RuntimeError(
                f"Unsupported schedule cadence: account {key[0]} requires {capacity} "
                f"concurrent connections, above supported limit "
                f"{MAX_ACCOUNT_CONNECTOR_LIMIT}"
            )
        return self._call(
            self._install(table, authorization, brokers, session_factory)
        )

    def stop(self):
        """Prevent sleepers from handing off; in-flight HTTP is not cancelled."""
        self._cancelled = True

        async def cancel_sleepers():
            for ticket_id, task in self._tasks.items():
                if ticket_id not in self._started and not task.done():
                    task.cancel()
        asyncio.run_coroutine_threadsafe(cancel_sleepers(), self._loop)

    def outcomes(self):
        if self._stopped.is_set():
            return dict(self._outcomes)
        async def snapshot():
            return dict(self._outcomes)
        return self._call(snapshot())

    def cancel_pending(self):
        """Cancel future ticket sleeps while preserving already-fired HTTP tasks."""
        self.stop()

    async def _close(self):
        if self._tasks:
            if not self._closing:
                raise RuntimeError("runtime close must be explicit")
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        for key, transport in tuple(self._transports.items()):
            await self._brokers[key].close_async_prepared_transport(transport)
        self._transports.clear()
        self._started.clear()

    def close(self):
        if self._stopped.is_set():
            return
        self.stop()
        self._closing = True
        async def cleanup_and_stop():
            await self._close()
            self._loop.call_soon(self._loop.stop)
        asyncio.run_coroutine_threadsafe(cleanup_and_stop(), self._loop)

    def wait_closed(self, timeout=15):
        return self._stopped.wait(timeout)

    @property
    def task_count(self):
        return len(self._tasks)

    @property
    def transport_count(self):
        return len(self._transports)

    @property
    def session_factory_calls(self):
        return self._session_factory_calls

    @property
    def task_factory_calls(self):
        return self._task_factory_calls


__all__ = ["ScheduledFireRuntime"]
