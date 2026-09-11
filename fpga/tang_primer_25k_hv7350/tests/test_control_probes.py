"""Host protocol tests; no pyserial dependency and no physical serial access."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "control_probes.py"
spec = importlib.util.spec_from_file_location("control_probes", SCRIPT)
control = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = control
spec.loader.exec_module(control)


def reply(cmd=0x10, seq=0x42, result=0, active=1, next_probe=2, flags=1):
    body = bytes((cmd, seq, result, active, next_probe, flags))
    return b"\x5A\xA5" + body + bytes((control.xor_bytes(body),))


class FakeSerial:
    def __init__(self, incoming=b"", write_count=None):
        self.incoming = bytearray(incoming)
        self.writes = []
        self.write_count = write_count

    def write(self, packet):
        self.writes.append(packet)
        return len(packet) if self.write_count is None else self.write_count

    def read(self, size):
        block = bytes(self.incoming[:size])
        del self.incoming[:size]
        return block


class ControlProtocolTests(unittest.TestCase):
    def test_start_each_probe(self):
        for probe in range(1, 5):
            self.assertEqual(control.encode_request("start", probe, 0x42),
                             bytes((0xA5, 0x5A, 0x10, probe, 0x42, 0x10 ^ probe ^ 0x42)))

    def test_other_commands(self):
        for name, command in control.COMMANDS.items():
            if name != "start":
                self.assertEqual(control.encode_request(name, sequence=7),
                                 bytes((0xA5, 0x5A, command, 0, 7, command ^ 7)))

    def test_invalid_request_arguments(self):
        for args in [("start",), ("start", 0), ("start", 5), ("next", 1),
                     ("status", 1), ("stop", 4), ("bad",), ("start", 1, -1),
                     ("start", 1, 256)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                control.encode_request(*args)

    def test_response_valid_and_completed(self):
        response = control.decode_response(reply(), 0x10, 0x42)
        self.assertEqual(response.active, 1)
        self.assertTrue(response.running)
        self.assertFalse(response.completed)
        response = control.decode_response(reply(active=0, flags=2), 0x10, 0x42)
        self.assertTrue(response.completed)
        self.assertFalse(response.running)

    def test_response_validation(self):
        bad_frames = [b"", reply()[:-1], b"\x00" + reply()[1:],
                      reply()[:-1] + b"\x00", reply(seq=0x43), reply(cmd=0x13),
                      reply(result=7), reply(active=5), reply(next_probe=0),
                      reply(flags=0), reply(flags=3), reply(flags=4)]
        for frame in bad_frames:
            with self.subTest(frame=frame), self.assertRaises(ValueError):
                control.decode_response(frame, 0x10, 0x42)

    def test_exchange_sends_exactly_once_skips_noise_stale_corrupt(self):
        incoming = (b"\xFF\x5A" + reply(seq=1) + reply()[:-1] + b"\xFF" + reply())
        port = FakeSerial(incoming)
        request = control.encode_request("start", 1, 0x42)
        response = control.exchange(port, request, 0.1)
        self.assertEqual(response.sequence, 0x42)
        self.assertEqual(port.writes, [request])

    def test_timeout_never_retries(self):
        port = FakeSerial()
        request = control.encode_request("start", 1, 0x42)
        with self.assertRaisesRegex(TimeoutError, "NOT retried"):
            control.exchange(port, request, 0.001)
        self.assertEqual(port.writes, [request])

    def test_partial_write_never_retries(self):
        port = FakeSerial(write_count=3)
        request = control.encode_request("next", sequence=0x42)
        with self.assertRaisesRegex(IOError, "NOT retried"):
            control.exchange(port, request, 0.1)
        self.assertEqual(port.writes, [request])

    def test_bad_exchange_packet_not_sent(self):
        port = FakeSerial()
        with self.assertRaises(ValueError):
            control.exchange(port, b"bad", 0.1)
        self.assertEqual(port.writes, [])

    def test_dry_run_without_serial_import(self):
        with mock.patch.object(control, "load_serial", side_effect=AssertionError("hardware access")):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(control.main(["--dry-run", "--seq", "0", "start", "4"]), 0)
        self.assertEqual(output.getvalue().strip(), "A5 5A 10 04 00 14")

    def test_dry_run_bad_probe_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(control.main(["--dry-run", "start", "8"]), 1)


if __name__ == "__main__":
    unittest.main()
