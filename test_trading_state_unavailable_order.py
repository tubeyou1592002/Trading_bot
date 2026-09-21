"""Test that TradingStateUnavailable from broker results in BLOCKED order (fail-closed)."""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from unittest.mock import MagicMock
from models.trading_state import TradingStateUnavailable
from models.order import Order, BUY
from models.account import Account
from core.order_engine import OrderEngine
from brokers.agaah.broker import AgaahBroker
from brokers.base import InstrumentLookupError, InstrumentProvider
from models.broker_instrument import BrokerInstrument
from models.instrument import Instrument


def test_trading_state_unavailable_results_in_blocked():
    """Test that TradingStateUnavailable from broker makes order BLOCKED."""
    
    # Setup mocks
    broker = MagicMock(spec=AgaahBroker)
    broker.name = "آگاه"
    
    provider = MagicMock(spec=InstrumentProvider)
    
    # Mock instrument resolution
    instrument = Instrument(
        symbol="TEST",
        name="Test Company",
        ins_code="12345678901234567",
        instrument_id="123",
        isin="IRO1TEST0001",
        market="بورس",
        flow=1,
    )
    
    broker_instrument = BrokerInstrument(
        name="TEST",
        company_name="Test Company",
        nsc_id="IRO1TEST0001",
        tse_id="12345678901234567",
        market_title="بورس",
        state_code="A",
        group_state_code="B",
    )
    
    provider.get_instrument.return_value = (instrument, broker_instrument)
    
    # Make broker.get_trading_state raise TradingStateUnavailable (source failure)
    broker.get_trading_state.side_effect = TradingStateUnavailable(
        "network error - source unavailable"
    )
    
    # Create account with sufficient funds
    account = Account(
        last_balance=100000000,
        adjusted_balance_t2=100000000,
        tradable_balance_t1=50000000,
        tradable_balance_t2=50000000,
        payable_balance_with_agah_credit_t0=0,
        payable_balance_with_agah_credit_t1=0,
        payable_balance_with_agah_credit_t2=0,
        payable_balance_without_agah_credit_t0=0,
        block=0,
        credit=0,
        settlement_date_t0=0,
        settlement_date_t1=0,
        settlement_date_t2=0,
    )
    
    # Create order
    order = Order(
        nsc_id="IRO1TEST0001",
        side=BUY,
        price=1000,
        quantity=10,
        bank_account_id=0,
    )
    
    # Execute through OrderEngine
    engine = OrderEngine()
    result = engine.execute_by_ins_code(
        broker=broker,
        provider=provider,
        ins_code=instrument.ins_code,
        order=order,
        account=account,
        live=False,  # Dry run
    )
    
    # Assertions
    print(f"Result: success={result.success}, sent={result.sent}, mode={result.mode}")
    print(f"Message: {result.message}")
    
    # Should be BLOCKED (fail-closed), not READY, and not throw exception
    assert result.success == False, "Order should not succeed"
    assert result.sent == False, "Order should not be sent"
    assert result.mode == "BLOCKED", f"Expected BLOCKED mode, got {result.mode}"
    assert result.order == order, "Order should be preserved"
    
    # Verify the broker was called
    broker.get_trading_state.assert_called_once_with("IRO1TEST0001")
    
    print("✅ Test passed: TradingStateUnavailable correctly results in BLOCKED order")


if __name__ == "__main__":
    try:
        test_trading_state_unavailable_results_in_blocked()
        print("\n🎉 All tests passed!")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)