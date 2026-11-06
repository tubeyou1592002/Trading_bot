"""Narrow composition seam for preparing one scheduled Live batch."""

from uuid import uuid4


def _resolve_prearm_ins_code(order):
    """Return the numeric TSETMC ins_code for an order, fail-closed if missing."""
    ins_code = getattr(order, "ins_code", None)
    if not isinstance(ins_code, str) or not ins_code.strip():
        raise ValueError(
            f"Order missing valid numeric ins_code (order.nsc_id={order.nsc_id!r}); "
            "refusing prearm — never falling back to Agah nscId."
        )
    return ins_code


class LivePrearmService:
    """Prepare frozen QueueEntry targets; this service never submits orders."""

    def __init__(self, account_store, session_manager, broker_manager, engine=None):
        from importlib import import_module
        OrderEngine = import_module("core.order_engine").OrderEngine

        self.account_store = account_store
        self.session_manager = session_manager
        self.broker_manager = broker_manager
        self.engine = engine if engine is not None else OrderEngine()

    def prepare(self, targets):
        execution_id = uuid4().hex
        requests = []
        for target in targets:
            broker = self.broker_manager.get_for_account(
                target.account_id, target.broker_name
            )
            provider = self.broker_manager.get_instrument_provider_for_account(
                target.account_id, target.broker_name
            )
            try:
                ins_code = _resolve_prearm_ins_code(target.entry.order)
            except ValueError:
                return execution_id, self.engine.prepare_batch((), execution_id)
            requests.append({
                "broker": broker,
                "provider": provider,
                "ins_code": ins_code,
                "order": target.entry.order,
                "account": target.account,
                "account_id": target.account_id,
                "broker_name": target.broker_name,
            })
        return execution_id, self.engine.prepare_batch(requests, execution_id)
