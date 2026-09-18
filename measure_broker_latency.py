"""
Block 8 — Task 8.3 Phase B: operator-only REAL Broker/API round-trip measurement.

This is a manual operator tool, NOT part of the trading path and NOT part of
the test suite:

    python measure_broker_latency.py --operation get_account --samples 3
    python measure_broker_latency.py --operation get_trading_state --nsc-id <nscId>
    python measure_broker_latency.py --operation get_instrument --nsc-id <nscId>

Safety properties (Task 8.3 §12/§13/§17):

  * READ-ONLY operations only. ``--operation`` is restricted to
    ``core.latency_instrumentation.READ_ONLY_OPERATIONS``; ``place_order`` and
    ``cancel_order`` are not reachable from this tool.
  * No order is sent, nothing is cancelled, no account or position state is
    modified, and ``live_trading_enabled`` is never touched.
  * The login uses the repository's existing credential mechanism: the
    operator types the username/password interactively (``getpass``) and the
    captcha text, exactly like ``test_agah_login.py``. Nothing is hard-coded
    and no secret is ever printed.
  * This tool is NOT connected to ``DispatchCore.dispatch()`` and is never
    invoked automatically. Importing it performs no I/O.
  * Sequential samples only (capped at ``MAX_SAMPLES``) — no bursts, no
    polling loop, no stress test.

INTERPRETATION (Task 8.3 §6): the measured value is a *Broker/API round trip*
— the whole existing broker method call, including local request preparation,
network transfer, remote server processing, response transfer and local
response handling performed inside that method. It is NOT pure network
latency. No DNS/TCP/TLS-level instrumentation is performed, and a single
sample proves nothing: read the distribution. This tool does not rank
brokers.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from datetime import datetime
from getpass import getpass

from brokers.manager import BrokerManager
from core.latency_instrumentation import (
    OP_GET_BUY_CAPACITY,
    OP_GET_INSTRUMENT,
    OP_GET_SELL_CAPACITY,
    OP_GET_TRADING_STATE,
    READ_ONLY_OPERATIONS,
    BrokerCallRecorder,
)
from models.order import BUY, SELL


DEFAULT_BROKER = "آگاه"
DEFAULT_SAMPLES = 3

# Deliberately small: this is a diagnostic measurement, not a benchmark.
# Each sample is one real request against the broker's API.
MAX_SAMPLES = 10

DEFAULT_CAPTCHA_IMAGE = "captcha.png"

_SIDES = {"buy": BUY, "sell": SELL}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Block 8 Task 8.3 Phase B — measure a REAL read-only Broker/API "
            "round trip. No order is sent and nothing is modified."
        )
    )
    parser.add_argument(
        "--broker",
        default=DEFAULT_BROKER,
        help=f"registered broker name (default: {DEFAULT_BROKER})",
    )
    parser.add_argument(
        "--operation",
        default="get_account",
        choices=sorted(READ_ONLY_OPERATIONS),
        help="read-only operation to measure (default: get_account)",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=DEFAULT_SAMPLES,
        help=(
            f"sequential sample count, 1..{MAX_SAMPLES} "
            f"(default: {DEFAULT_SAMPLES})"
        ),
    )
    parser.add_argument(
        "--nsc-id",
        dest="nsc_id",
        default=None,
        help="broker nscId required by instrument/trading-state/capacity reads",
    )
    parser.add_argument(
        "--side",
        default="buy",
        choices=["buy", "sell"],
        help="order side used only as a capacity-read parameter (default: buy)",
    )
    parser.add_argument(
        "--price",
        type=int,
        default=None,
        help="price parameter required by capacity reads",
    )
    parser.add_argument(
        "--fund",
        type=float,
        default=None,
        help="fund parameter used by the BUY capacity read",
    )
    parser.add_argument(
        "--captcha-image",
        default=DEFAULT_CAPTCHA_IMAGE,
        help=f"where to save the login captcha (default: {DEFAULT_CAPTCHA_IMAGE})",
    )
    return parser


def validate_args(args) -> None:
    if args.operation not in READ_ONLY_OPERATIONS:
        # Unreachable through argparse choices; kept as an explicit guard.
        raise SystemExit(
            f"refused: operation {args.operation!r} is not read-only"
        )

    if args.samples < 1 or args.samples > MAX_SAMPLES:
        raise SystemExit(
            f"--samples must be between 1 and {MAX_SAMPLES} "
            f"(got {args.samples}); this is a diagnostic, not a benchmark"
        )

    if args.operation != "get_account" and not args.nsc_id:
        raise SystemExit(f"--nsc-id is required for {args.operation}")

    if args.operation in (OP_GET_BUY_CAPACITY, OP_GET_SELL_CAPACITY):
        if args.price is None:
            raise SystemExit(f"--price is required for {args.operation}")

    if args.operation == OP_GET_BUY_CAPACITY and args.fund is None:
        raise SystemExit(f"--fund is required for {args.operation}")


def build_call(args, broker):
    """
    Return a zero-argument callable for the requested READ-ONLY operation.

    Only existing, already-supported broker methods appear here. There is no
    order endpoint and no cancel endpoint in this mapping.
    """
    operation = args.operation

    if operation == "get_account":
        return lambda: broker.get_account()

    if operation == OP_GET_INSTRUMENT:
        return lambda: broker.get_instrument(args.nsc_id)

    if operation == OP_GET_TRADING_STATE:
        return lambda: broker.get_trading_state(args.nsc_id)

    if operation == OP_GET_BUY_CAPACITY:
        return lambda: broker.get_buy_capacity(
            nsc_id=args.nsc_id,
            side_code=_SIDES[args.side],
            fund=args.fund,
            price=args.price,
        )

    if operation == OP_GET_SELL_CAPACITY:
        return lambda: broker.get_sell_capacity(
            nsc_id=args.nsc_id,
            side_code=_SIDES[args.side],
            fund=None,
            price=args.price,
        )

    raise SystemExit(f"refused: unsupported operation {operation!r}")


# ---------------------------------------------------------------------------
# Login (existing credential mechanism — nothing hard-coded, nothing printed)
# ---------------------------------------------------------------------------


def interactive_login(broker, captcha_image: str) -> None:
    """
    Interactive login using the existing captcha + credential flow.

    Prints no credential: only whether the expected identifiers came back.
    """
    print("Requesting captcha ...")
    captcha_data = broker.get_captcha()
    broker.save_captcha_image(captcha_data, captcha_image)
    print(f"Captcha saved to: {captcha_image}")
    print()

    username = input("username: ").strip()
    password = getpass("password: ")
    captcha = input("captcha text: ").strip()

    result = broker.login(
        username=username,
        password=password,
        captcha=captcha,
        captcha_id=captcha_data["captchaId"],
    )

    print()
    print("LOGIN OK")
    print(
        "  userIdentifier received:",
        bool(result.get("userIdentifier")),
    )
    print("  refreshToken received  :", bool(result.get("hasRefreshToken")))


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------


def measure_samples(broker, operation, call, samples):
    """
    Run ``samples`` sequential single-request measurements.

    Uses the same Task 8.3 measurement mechanism (``BrokerCallRecorder``,
    ``time.perf_counter_ns``) as the offline dispatch instrumentation.
    """
    results = []
    for index in range(1, samples + 1):
        recorder = BrokerCallRecorder()
        ok = True
        error = None

        try:
            recorder.measure(operation, call)
        except Exception as exc:  # a failed read is a valid measurement
            ok = False
            error = f"{type(exc).__name__}: {exc}"

        timing = recorder.calls[-1]
        results.append(
            {
                "sample": index,
                "duration_ns": timing.duration_ns,
                "ok": ok and timing.ok,
                "error": error,
            }
        )
    return results


def _ms(ns: int) -> str:
    return f"{ns / 1_000_000:.3f} ms"


def print_report(broker, args, results) -> None:
    successful = [r for r in results if r["ok"]]
    durations = [r["duration_ns"] for r in successful]

    print()
    print("=" * 66)
    print("Block 8 — Task 8.3 Phase B: real read-only Broker/API measurement")
    print("=" * 66)
    print(f"timestamp (local) : {datetime.now().isoformat(timespec='seconds')}")
    print(f"broker            : {broker.name}")
    print(f"operation         : {args.operation}")
    print(f"samples requested : {args.samples}")
    print(
        f"samples completed : {len(results)} "
        f"(ok: {len(successful)}, failed: {len(results) - len(successful)})"
    )
    print("-" * 66)
    print("per sample (broker/API round trip):")
    for result in results:
        status = "ok" if result["ok"] else f"FAILED ({result['error']})"
        print(
            f"  {result['sample']:>3}  {_ms(result['duration_ns']):>12}  {status}"
        )

    print("-" * 66)
    if durations:
        print("summary of successful samples:")
        print(f"  count : {len(durations)}")
        print(f"  min   : {_ms(min(durations))}")
        print(f"  median: {_ms(int(statistics.median(durations)))}")
        print(f"  mean  : {_ms(int(statistics.mean(durations)))}")
        print(f"  max   : {_ms(max(durations))}")
    else:
        print("summary: no successful sample — nothing can be concluded.")

    print("-" * 66)
    print("Interpretation:")
    print("  * The value is a Broker/API ROUND TRIP (local preparation,")
    print("    transfer, remote processing, response handling inside the")
    print("    existing method). It is NOT network-only latency.")
    print("  * One sample proves nothing; read the distribution.")
    print("  * No order was sent, nothing was cancelled, no account state")
    print("    was changed, and live trading stayed disabled.")
    print("=" * 66)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    validate_args(args)

    print("=" * 66)
    print("READ-ONLY broker/API measurement — no order will be sent")
    print("=" * 66)
    print(f"broker    : {args.broker}")
    print(f"operation : {args.operation}")
    print(f"samples   : {args.samples}")
    print()

    broker_manager = BrokerManager()
    try:
        broker = broker_manager.get(args.broker)
    except Exception as exc:
        print(f"Unknown broker {args.broker!r}: {exc}")
        return 2

    try:
        interactive_login(broker, args.captcha_image)
    except Exception as exc:
        print()
        print("LOGIN FAILED")
        print(f"  {type(exc).__name__}: {exc}")
        return 3

    call = build_call(args, broker)
    results = measure_samples(broker, args.operation, call, args.samples)
    print_report(broker, args, results)

    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
