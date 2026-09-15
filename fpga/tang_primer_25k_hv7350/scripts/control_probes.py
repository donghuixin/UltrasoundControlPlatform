#!/usr/bin/env python3
"""Control four HV7350 probes over the Dock's USB-C UART (115200, 8N1).

No serial dependency or hardware access is needed for --dry-run. Real serial
access / --list requires pyserial (python -m pip install pyserial). Commands are
sent ONCE: a timeout is ambiguous, so use status or stop, never blind START retry.
The UART controls transmission only; it does not acquire AFE samples over USB.
Continuous firmware has no automatic stop: closing USB leaves TX running.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import secrets
import sys
import time
from typing import Any

COMMANDS = {"start": 0x10, "next": 0x11, "stop": 0x12, "status": 0x13}
RESULTS = {0: "ok", 1: "unknown command", 2: "bad argument"}


def xor_bytes(data: bytes) -> int:
    checksum = 0
    for value in data:
        checksum ^= value
    return checksum


def encode_request(command: str, probe: int | None = None, sequence: int = 0) -> bytes:
    if command not in COMMANDS:
        raise ValueError("command must be start, next, stop, or status")
    if not 0 <= sequence <= 255:
        raise ValueError("sequence must be 0..255")
    if command == "start":
        if probe not in (1, 2, 3, 4):
            raise ValueError("start requires probe 1..4")
        argument = probe
    else:
        if probe is not None:
            raise ValueError("only start takes a probe number")
        argument = 0
    body = bytes((COMMANDS[command], argument, sequence))
    return b"\xA5\x5A" + body + bytes((xor_bytes(body),))


@dataclass(frozen=True)
class Response:
    command: int
    sequence: int
    result: int
    active: int
    next_probe: int
    flags: int

    @property
    def running(self) -> bool:
        return bool(self.flags & 1)

    @property
    def completed(self) -> bool:
        """Legacy finite-session flag; always false on continuous firmware."""
        return bool(self.flags & 2)


def decode_response(frame: bytes, command: int, sequence: int) -> Response:
    if len(frame) != 9 or frame[:2] != b"\x5A\xA5":
        raise ValueError("invalid response length/header")
    if xor_bytes(frame[2:8]) != frame[8]:
        raise ValueError("response checksum mismatch")
    response = Response(*frame[2:8])
    if response.command != command or response.sequence != sequence:
        raise ValueError("response command/sequence does not match request")
    if response.result not in RESULTS:
        raise ValueError("unknown response result")
    if response.active not in range(5) or response.next_probe not in range(1, 5):
        raise ValueError("invalid probe in response")
    if response.flags & ~3 or response.running != (response.active != 0):
        raise ValueError("inconsistent response flags")
    if response.running and response.completed:
        raise ValueError("RUNNING and COMPLETED cannot both be set")
    return response


def read_response(port: Any, command: int, sequence: int, timeout: float) -> Response:
    """Skip noise/stale/corrupt packets; deadline is not extended by junk bytes."""
    deadline = time.monotonic() + timeout
    buffer = bytearray()
    while time.monotonic() < deadline:
        # The Serial object has a short read timeout, never an unbounded read.
        block = port.read(1)
        if not block:
            continue
        buffer.extend(block)
        while len(buffer) >= 2:
            if buffer[:2] != b"\x5A\xA5":
                del buffer[0]
                continue
            if len(buffer) < 9:
                break
            try:
                return decode_response(bytes(buffer[:9]), command, sequence)
            except ValueError:
                # Advance one byte so overlapping headers remain discoverable.
                del buffer[0]
    raise TimeoutError("No valid matching reply. Command may have executed; it was NOT retried. "
                       "Send status to check, or stop to stop transmission.")


def exchange(port: Any, request: bytes, timeout: float) -> Response:
    if len(request) != 6 or request[:2] != b"\xA5\x5A" or xor_bytes(request[2:5]) != request[5]:
        raise ValueError("invalid request")
    count = port.write(request)
    if count != len(request):
        raise IOError("Partial serial write; request was NOT retried")
    return read_response(port, request[2], request[4], timeout)


def load_serial() -> Any:
    try:
        import serial
    except ImportError as exc:
        raise RuntimeError("pyserial is required: python -m pip install pyserial") from exc
    return serial


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="COM5 (Windows) or /dev/cu.usbmodem... (macOS)")
    parser.add_argument("--list", action="store_true", help="list serial ports without opening them")
    parser.add_argument("--dry-run", action="store_true", help="print request only; never open a port")
    parser.add_argument("--seq", type=int, help="sequence 0..255; default is random")
    parser.add_argument("--timeout", type=float, default=1.0, help="response timeout seconds (default 1)")
    parser.add_argument("command", nargs="?", choices=COMMANDS)
    parser.add_argument("probe", nargs="?", type=int, help="1..4, for start only")
    args = parser.parse_args(argv)
    try:
        if args.list:
            if args.dry_run or args.command is not None:
                parser.error("--list cannot be combined with --dry-run or a command")
            load_serial()
            from serial.tools import list_ports
            for port in list_ports.comports():
                print(f"{port.device}\t{port.description}")
            return 0
        if args.command is None:
            parser.error("a command is required unless --list is used")
        if not 0 < args.timeout <= 60:
            parser.error("--timeout must be >0 and <=60 seconds")
        sequence = secrets.randbelow(256) if args.seq is None else args.seq
        request = encode_request(args.command, args.probe, sequence)
        if args.dry_run:
            print(request.hex(" ").upper())
            return 0
        if not args.port:
            parser.error("--port is required for serial access")
        serial = load_serial()
        # Disable flow control and request inactive modem signals before opening.
        # The Dock UART does not require a reset or any automatic START on open.
        port = serial.Serial(port=None, baudrate=115200, bytesize=serial.EIGHTBITS,
                             parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                             timeout=min(args.timeout, 0.02), write_timeout=args.timeout,
                             xonxoff=False, rtscts=False, dsrdtr=False)
        try:
            port.dtr = False
            port.rts = False
            port.port = args.port
            port.open()
            port.reset_input_buffer()
            response = exchange(port, request, args.timeout)
        finally:
            port.close()
        print(f"result={RESULTS[response.result]} active=HV{response.active}" if response.active
              else f"result={RESULTS[response.result]} active=idle", end=" ")
        print(f"next=HV{response.next_probe} running={int(response.running)} "
              f"completed={int(response.completed)} seq={response.sequence}")
        return 0 if response.result == 0 else 2
    except (ValueError, RuntimeError, OSError, TimeoutError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
