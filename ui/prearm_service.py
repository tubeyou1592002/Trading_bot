"""Narrow composition seam for preparing one scheduled Live batch."""

from uuid import uuid4


class LivePrearmService:
    """Prepare frozen QueueEntry targets; this service never submits orders."""

    def __init__(self, account_store, session_manager, broker_manager, engine=None):
        from core.order_engine import OrderEngine

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
            requests.append({
                "broker": broker,
                "provider": provider,
                "ins_code": target.entry.order.nsc_id,
                "order": target.entry.order,
                "account": target.account,
                "account_id": target.account_id,
                "broker_name": target.broker_name,
            })
        return execution_id, self.engine.prepare_batch(requests, execution_id)
