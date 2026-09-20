"""
ui/order_config_state.py — UI-3.1 order configuration state.

A small, application-level state object that holds what the user has
entered on the Order Configuration page:

    symbol selection, side (BUY/SELL), price, quantity.

Explicitly NOT (UI-3.1 boundary):

    * NOT a ``models.order.Order`` — the Core ``Order`` needs a real
      ``nsc_id`` which only the Core instrument-resolution path can
      produce; the UI does not guess or fabricate identities.
    * no ``nsc_id`` field, no ``to_payload()``, no broker payload,
      no execution — this object never executes, submits or dispatches
      anything.
    * no price/quantity rule duplication — ``fixed_price_tick``,
      price thresholds, min/max quantity and lot size remain the
      authority of ``OrderValidator``/``BrokerInstrument`` inside the
      Core; only basic input-level checks (empty / non-numeric) exist
      here.

Side uses the project's real constants (``models.order.BUY`` /
``models.order.SELL``) — no new side enum is invented in the UI.

Fee: no fee contract exists in the repository yet, so no fee value is
computed or stored — fee display stays "Not available" (UI-3.3 scope).
"""

from dataclasses import dataclass

from models.instrument import Instrument
from models.order import BUY, SELL


class OrderConfigError(ValueError):
    """Raised for invalid order-configuration input (basic input-level only)."""


# Only valid sides — bound to the real project constants.
VALID_SIDES = (BUY, SELL)

# Symbol status placeholders. No real status is computed in UI-3.1; the
# authoritative source is connected in a later task. An absent/unknown
# status is NEVER shown as tradable.
SYMBOL_STATUS_NOT_AVAILABLE = "Not available"


@dataclass
class OrderConfiguration:
    """
    The user's current order configuration (form state only).

    ``selected_instrument`` is a ``models.instrument.Instrument`` when the
    user has picked a symbol from real data, otherwise ``None`` — a fake
    instrument is never created just to enable ordering.
    """

    selected_instrument: object | None = None
    side: int | None = None
    price: int | None = None
    quantity: int | None = None

    # ---------------------------------------------------------
    # Basic input-level setters (no Core rule duplication)
    # ---------------------------------------------------------

    def set_side(self, side):
        """
        Set the order side. Only the real project constants
        (``models.order.BUY`` / ``models.order.SELL``) are accepted.
        """
        if side not in VALID_SIDES:
            raise OrderConfigError(
                f"Invalid side: {side!r} (expected models.order.BUY "
                f"({BUY}) or models.order.SELL ({SELL}))"
            )
        self.side = side
        return self.side

    def set_price(self, price):
        """
        Set the price as an integer.

        The Core ``Order`` contract is ``price: int``, so the UI state
        accepts exactly that type: a real ``int`` (not ``bool``, not
        ``float`` — even ``15000.0`` is not an int). Negative values are
        invalid input. No tick / price-limit / range rules exist here —
        those remain Core authority (OrderValidator/BrokerInstrument).
        """
        if isinstance(price, bool) or not isinstance(price, int):
            raise OrderConfigError(
                "Price must be an integer (the Core Order contract is "
                "price: int)"
            )
        if price < 0:
            raise OrderConfigError("Price must not be negative")
        self.price = price
        return self.price

    def set_quantity(self, quantity):
        """
        Set the quantity as an integer.

        The Core ``Order`` contract is ``quantity: int``, so the UI state
        accepts exactly that type: a real ``int`` (not ``bool``, not
        ``float`` — even ``500.0`` is not an int). Negative values are
        invalid input. No minimum / maximum / lot-size / capacity rules
        exist here — those remain Core authority.
        """
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise OrderConfigError(
                "Quantity must be an integer (the Core Order contract is "
                "quantity: int)"
            )
        if quantity < 0:
            raise OrderConfigError("Quantity must not be negative")
        self.quantity = quantity
        return self.quantity

    def select_instrument(self, instrument):
        """
        Store a real ``models.instrument.Instrument`` selection.

        Only a genuine ``models.instrument.Instrument`` instance (or
        ``None``) is accepted — any other object, even one that merely
        carries an ``ins_code`` attribute, is rejected: the UI never
        fabricates an instrument. Nothing is resolved or guessed here.
        """
        if instrument is not None and not isinstance(instrument, Instrument):
            raise OrderConfigError(
                "selected_instrument must be a real "
                "models.instrument.Instrument instance or None — "
                "the UI never fabricates an instrument"
            )
        self.selected_instrument = instrument
        return self.selected_instrument

    # ---------------------------------------------------------
    # Derived display values
    # ---------------------------------------------------------

    def base_amount(self):
        """
        Base amount = price * quantity, or ``None`` when either input is
        missing. This is explicitly NOT a final amount — no fee, tax or
        any other charge is invented (no fee contract exists yet).
        """
        if self.price is None or self.quantity is None:
            return None
        return self.price * self.quantity

    def final_amount(self):
        """
        Always ``None`` in UI-3.1: there is no authoritative fee contract,
        so a final amount is never fabricated (Fee is UI-3.3 scope).
        """
        return None

    def symbol_status(self):
        """
        Symbol status placeholder. Without a verified, authoritative
        source the status is "Not available" — it is NEVER reported as
        tradable/permitted, matching the project's fail-closed stance.
        """
        return SYMBOL_STATUS_NOT_AVAILABLE
