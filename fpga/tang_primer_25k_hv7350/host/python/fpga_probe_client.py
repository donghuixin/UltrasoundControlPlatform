"""Persistent, thread-safe control client for the four-probe FPGA firmware.

Copy this file into the host application. It is self-contained; only a real
connection needs pyserial. No command is sent by construction/connect()/close()
unless connect(check_status=True) explicitly requests a STATUS query.

This is a transmission-control interface, NOT an ultrasound sample interface.
An ACK is a state snapshot, NOT the hardware acquisition trigger. Sequence IDs
match replies only: the FPGA does NOT deduplicate requests. Commands are never
retried automatically, including STATUS.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import secrets
import threading
import time
from typing import Any, Callable, Optional

START = 0x10
NEXT = 0x11
STOP = 0x12
STATUS = 0x13
BAUD_RATE = 115200
RECOVERY_QUIET_SECONDS = 0.030
RESULT_NAMES = {0: "ok", 1: "unknown command", 2: "bad argument"}


class ProbeClientError(RuntimeError):
    """Base exception for this client."""


class NotConnectedError(ProbeClientError):
    pass


class StateUnknownError(ProbeClientError):
    """START/NEXT blocked until an explicit STATUS or STOP confirms state."""


class TransportError(ProbeClientError):
    """Serial failure. The command may have executed; state is unknown."""


class ResponseTimeout(ProbeClientError, TimeoutError):
    """No matching valid response arrived. The command was NOT retried."""


class ProtocolError(ProbeClientError, ValueError):
    """A response has invalid framing, checksum, or semantic fields."""


class CommandRejected(ProbeClientError):
    """The FPGA returned a valid matching ACK with a nonzero result."""

    def __init__(self, response: "ProbeStatus") -> None:
        self.response = response
        super().__init__(f"FPGA rejected command 0x{response.command:02X}: "
                         f"{RESULT_NAMES[response.result]} (result={response.result})")


@dataclass(frozen=True)
class ProbeStatus:
    """Snapshot at command processing time, not a continuously live state."""

    command: int
    sequence: int
    result: int
    active_probe: int   # 0 means idle, otherwise 1..4.
    next_probe: int     # 1..4; shared with the physical S2 button.
    flags: int

    @property
    def running(self) -> bool:
        return bool(self.flags & 0x01)

    @property
    def completed(self) -> bool:
        return bool(self.flags & 0x02)


def _xor(data: bytes) -> int:
    value = 0
    for byte in data:
        value ^= byte
    return value


def encode_request(command: int, argument: int, sequence: int) -> bytes:
    """Encode a validated 6-byte request without opening a serial port."""
    if command not in (START, NEXT, STOP, STATUS):
        raise ValueError("unsupported command")
    if type(argument) is not int or (argument not in range(1, 5) if command == START else argument != 0):
        raise ValueError("START requires probe 1..4; other commands require argument 0")
    if type(sequence) is not int or not 0 <= sequence <= 255:
        raise ValueError("sequence must be an integer in 0..255")
    body = bytes((command, argument, sequence))
    return b"\xA5\x5A" + body + bytes((_xor(body),))


def decode_response(frame: bytes) -> ProbeStatus:
    """Validate one 9-byte response; command/sequence matching is done by client."""
    if len(frame) != 9 or frame[:2] != b"\x5A\xA5":
        raise ProtocolError("invalid response length/header")
    if _xor(frame[2:8]) != frame[8]:
        raise ProtocolError("response checksum mismatch")
    status = ProbeStatus(*frame[2:8])
    if status.result not in RESULT_NAMES:
        raise ProtocolError(f"unknown response result {status.result}")
    if status.active_probe not in range(5) or status.next_probe not in range(1, 5):
        raise ProtocolError("response probe index is outside the documented range")
    if status.flags & ~0x03:
        raise ProtocolError("response has unsupported flag bits")
    if status.running and status.completed:
        raise ProtocolError("RUNNING and COMPLETED cannot both be set")
    if status.running != (status.active_probe != 0):
        raise ProtocolError("RUNNING flag does not match active_probe")
    return status


def _default_serial_factory(**kwargs: Any) -> Any:
    try:
        import serial
    except ImportError as exc:
        raise TransportError("Install pyserial in the host environment: python -m pip install pyserial") from exc
    return serial.Serial(**kwargs)


class FpgaProbeClient:
    """One persistent port and one outstanding request per instance.

    All I/O is synchronous: write_timeout + timeout, plus 30 ms for UNKNOWN-state
    recovery (and lock waiting behind another call). Use a worker
    thread/QThread, not the GUI thread. A STOP call waits behind an outstanding
    transaction's lock; this client is not an emergency-stop interlock.

    transport_factory is a test seam: it must return an unopened pyserial-like
    object with port/dtr/rts/timeout/write_timeout, open/close, is_open,
    reset_input_buffer(), write(bytes), and read(size). Production callers omit it.
    """

    def __init__(self, port: str, *, timeout: float = 1.0,
                 write_timeout: float = 1.0, sequence_start: Optional[int] = None,
                 transport_factory: Optional[Callable[..., Any]] = None) -> None:
        if not isinstance(port, str) or not port.strip():
            raise ValueError("port is required, for example COM5")
        for name, value in (("timeout", timeout), ("write_timeout", write_timeout)):
            if not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 < value <= 60:
                raise ValueError(f"{name} must be finite, >0, and <=60 seconds")
        if sequence_start is not None and (type(sequence_start) is not int or not 0 <= sequence_start <= 255):
            raise ValueError("sequence_start must be 0..255")
        self.port_name = port
        self.timeout = float(timeout)
        self.write_timeout = float(write_timeout)
        self._sequence = secrets.randbelow(256) if sequence_start is None else sequence_start
        self._factory = transport_factory or _default_serial_factory
        self._transport: Optional[Any] = None
        self._lock = threading.Lock()
        self._state_unknown = True
        self._last_status: Optional[ProbeStatus] = None

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._transport is not None and bool(self._transport.is_open)

    @property
    def state_unknown(self) -> bool:
        """True before a valid reply, after ambiguous I/O, or after close().

        False means the latest reply was valid, not that its snapshot is current:
        S2 or automatic completion can change the FPGA at any time.
        """
        with self._lock:
            return self._state_unknown

    @property
    def last_status(self) -> Optional[ProbeStatus]:
        """Latest valid snapshot, potentially stale even while connected."""
        with self._lock:
            return self._last_status

    def connect(self, *, check_status: bool = False) -> Optional[ProbeStatus]:
        """Open without START/STOP. Optional STATUS does not identify firmware.

        If the optional STATUS fails, the port remains open for an explicit
        get_status()/stop(), or close(). There is no automatic retry or reconnect.
        """
        with self._lock:
            if self._transport is None or not self._transport.is_open:
                transport = None
                try:
                    transport = self._factory(
                        port=None, baudrate=BAUD_RATE, bytesize=8, parity="N", stopbits=1,
                        timeout=min(self.timeout, 0.02), write_timeout=self.write_timeout,
                        xonxoff=False, rtscts=False, dsrdtr=False)
                    transport.dtr = False
                    transport.rts = False
                    transport.port = self.port_name
                    transport.open()
                    transport.reset_input_buffer()
                except Exception as exc:
                    if transport is not None:
                        try:
                            transport.close()
                        except Exception:
                            pass
                    self._state_unknown = True
                    raise TransportError(f"Cannot open {self.port_name}: {exc}") from exc
                self._transport = transport
                self._state_unknown = True
            return self._execute_locked(STATUS, 0) if check_status else None

    def close(self) -> None:
        """Close the port; does NOT send STOP or stop an active FPGA session."""
        with self._lock:
            transport, self._transport = self._transport, None
            self._state_unknown = True
            if transport is not None:
                try:
                    transport.close()
                except Exception as exc:
                    raise TransportError(f"Serial close failed: {exc}; FPGA may still be running") from exc

    def __enter__(self) -> "FpgaProbeClient":
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def start_probe(self, probe: int) -> ProbeStatus:
        """Start/restart for 5 s; requires known state and AFE armed by caller."""
        return self._execute(START, probe)

    def next_probe(self) -> ProbeStatus:
        """Immediately replace the session with the shared next probe for 5 s."""
        return self._execute(NEXT, 0)

    def stop(self) -> ProbeStatus:
        """Explicit STOP, serialized behind any current transaction; never retried."""
        return self._execute(STOP, 0)

    def get_status(self) -> ProbeStatus:
        """Read a snapshot without altering transmission. Caller may retry it."""
        return self._execute(STATUS, 0)

    def _execute(self, command: int, argument: int) -> ProbeStatus:
        # Validate before consuming a sequence number or accessing the port.
        encode_request(command, argument, 0)
        with self._lock:
            return self._execute_locked(command, argument)

    def _execute_locked(self, command: int, argument: int) -> ProbeStatus:
        transport = self._transport
        if transport is None or not transport.is_open:
            self._state_unknown = True
            raise NotConnectedError("Call connect() before sending commands")
        if command in (START, NEXT) and self._state_unknown:
            raise StateUnknownError("START/NEXT blocked while state is UNKNOWN. "
                                    "Explicitly query STATUS or send STOP first; no command was sent.")
        if command in (STATUS, STOP) and self._state_unknown:
            # Only reached after the caller EXPLICITLY requested STATUS/STOP.
            # Discard locally queued output where supported, then give the FPGA's
            # 10 ms partial-packet parser timeout margin. This cannot guarantee
            # that every USB/driver queue is empty; persistent errors need review.
            try:
                reset_output = getattr(transport, "reset_output_buffer", None)
                if reset_output is not None:
                    reset_output()
                time.sleep(RECOVERY_QUIET_SECONDS)
            except Exception as exc:
                raise TransportError(f"Cannot prepare explicit recovery: {exc}; state remains UNKNOWN") from exc
        sequence = self._sequence
        self._sequence = (self._sequence + 1) & 0xFF
        request = encode_request(command, argument, sequence)
        try:
            count = transport.write(request)  # Exactly ONE write. No retries.
            if count != len(request):
                raise TransportError(f"Partial serial write ({count}/6 bytes); command was NOT retried")
            response = self._read_response_locked(transport, command, sequence)
        except (ResponseTimeout, ProtocolError, TransportError):
            self._state_unknown = True
            raise
        except Exception as exc:
            self._state_unknown = True
            raise TransportError(f"Serial transaction failed: {exc}. Command may have executed; "
                                 "it was NOT retried. Explicitly query STATUS or send STOP.") from exc
        self._last_status = response
        self._state_unknown = False
        if response.result != 0:
            raise CommandRejected(response)
        return response

    def _read_response_locked(self, transport: Any, command: int, sequence: int) -> ProbeStatus:
        deadline = time.monotonic() + self.timeout
        buffer = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ResponseTimeout("No valid matching reply. State is UNKNOWN: command may have "
                                      "executed and was NOT retried. Explicitly query STATUS or send STOP.")
            transport.timeout = min(remaining, 0.02)
            block = transport.read(1)
            if not block:
                continue
            buffer.extend(block)
            while len(buffer) >= 2:
                if buffer[:2] != b"\x5A\xA5":
                    del buffer[0]
                    continue
                if len(buffer) < 9:
                    break
                frame = bytes(buffer[:9])
                if _xor(frame[2:8]) != frame[8]:
                    del buffer[0]  # Resynchronize even when a header overlaps noise.
                    continue
                del buffer[:9]
                if frame[2] != command or frame[3] != sequence:
                    continue  # Complete but stale/unrelated response.
                return decode_response(frame)
