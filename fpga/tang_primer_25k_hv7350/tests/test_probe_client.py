"""Persistent client tests using fake transports only; pyserial is not needed."""
import concurrent.futures
import importlib.util
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest import mock

CLIENT_PATH = Path(__file__).resolve().parents[1] / "host" / "python" / "fpga_probe_client.py"
spec = importlib.util.spec_from_file_location("fpga_probe_client", CLIENT_PATH)
client = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = client
spec.loader.exec_module(client)


def response(command=client.STATUS, sequence=0, result=0, active=0, next_probe=1, flags=0):
    body = bytes((command, sequence, result, active, next_probe, flags))
    return b"\x5A\xA5" + body + bytes((client._xor(body),))


class FakeTransport:
    def __init__(self):
        self.port = None
        self.dtr = True
        self.rts = True
        self.timeout = 0.001
        self.write_timeout = 1
        self.is_open = False
        self.open_calls = 0
        self.close_calls = 0
        self.reset_calls = 0
        self.reset_output_calls = 0
        self.writes = []
        self.incoming = bytearray()
        self.on_write = lambda request: response(request[2], request[4])
        self.open_error = None
        self.close_error = None
        self.write_error = None
        self.read_error = None
        self.write_count = None
        self.open_configuration = None
        self.unread_reply_on_write = False

    def open(self):
        self.open_calls += 1
        self.open_configuration = (self.port, self.dtr, self.rts)
        if self.open_error:
            raise self.open_error
        self.is_open = True

    def close(self):
        self.close_calls += 1
        self.is_open = False
        if self.close_error:
            raise self.close_error

    def reset_input_buffer(self):
        self.reset_calls += 1
        self.incoming.clear()

    def reset_output_buffer(self):
        self.reset_output_calls += 1

    def write(self, request):
        self.writes.append(request)
        if self.incoming:
            self.unread_reply_on_write = True
        if self.write_error:
            raise self.write_error
        if self.write_count is not None:
            return self.write_count
        if self.on_write:
            self.incoming.extend(self.on_write(request))
        return len(request)

    def read(self, size):
        if self.read_error:
            raise self.read_error
        if not self.incoming:
            time.sleep(min(self.timeout, 0.001))
            return b""
        block = bytes(self.incoming[:size])
        del self.incoming[:size]
        return block


class FakeFactory:
    def __init__(self, transport=None):
        self.transport = transport or FakeTransport()
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        for key, value in kwargs.items():
            setattr(self.transport, key, value)
        return self.transport


class ClientTests(unittest.TestCase):
    def make_client(self, **kwargs):
        factory = FakeFactory()
        connection = client.FpgaProbeClient("COM5", timeout=0.01, sequence_start=0,
                                            transport_factory=factory, **kwargs)
        self.addCleanup(connection.close)
        return connection, factory.transport, factory

    def test_constructor_and_connect_are_silent_and_configuration_is_correct(self):
        connection, transport, factory = self.make_client()
        self.assertFalse(connection.connected)
        self.assertTrue(connection.state_unknown)
        self.assertEqual(factory.calls, [])
        self.assertIsNone(connection.connect())
        self.assertTrue(connection.connected)
        self.assertEqual(transport.open_configuration, ("COM5", False, False))
        self.assertEqual(factory.calls[0], dict(port=None, baudrate=115200, bytesize=8,
                         parity="N", stopbits=1, timeout=0.01, write_timeout=1.0,
                         xonxoff=False, rtscts=False, dsrdtr=False))
        self.assertEqual(transport.writes, [])
        self.assertEqual(transport.reset_calls, 1)
        connection.connect()
        self.assertEqual(transport.open_calls, 1)

    def test_connect_explicit_status_and_all_commands(self):
        connection, transport, _ = self.make_client()
        status = connection.connect(check_status=True)
        self.assertEqual(status.command, client.STATUS)
        self.assertFalse(connection.state_unknown)
        for probe in range(1, 5):
            connection.start_probe(probe)
        connection.next_probe()
        connection.stop()
        connection.get_status()
        expected = [(client.STATUS, 0), (client.START, 1), (client.START, 2),
                    (client.START, 3), (client.START, 4), (client.NEXT, 0),
                    (client.STOP, 0), (client.STATUS, 0)]
        self.assertEqual(transport.writes,
                         [client.encode_request(cmd, arg, seq) for seq, (cmd, arg) in enumerate(expected)])

    def test_unknown_gate_and_invalid_probe_never_write_or_consume_sequence(self):
        connection, transport, _ = self.make_client()
        connection.connect()
        with self.assertRaises(client.StateUnknownError):
            connection.start_probe(1)
        with self.assertRaises(client.StateUnknownError):
            connection.next_probe()
        for probe in (0, 5, True, "1", None):
            with self.subTest(probe=probe), self.assertRaises(ValueError):
                connection.start_probe(probe)
        self.assertEqual(transport.writes, [])
        connection.stop()
        self.assertEqual(transport.writes[0], client.encode_request(client.STOP, 0, 0))
        self.assertFalse(connection.state_unknown)

    def test_unknown_recovery_discards_output_and_waits_only_on_explicit_action(self):
        connection, transport, _ = self.make_client()
        with mock.patch.object(client.time, "sleep") as sleep:
            connection.connect()
            self.assertEqual(transport.reset_output_calls, 0)
            sleep.assert_not_called()
            connection.get_status()
            sleep.assert_called_once_with(0.030)
            self.assertEqual(transport.reset_output_calls, 1)
            sleep.reset_mock()
            connection.get_status()  # Known state: no recovery reset/wait.
            connection.stop()
            sleep.assert_not_called()
            self.assertEqual(transport.reset_output_calls, 1)

    def test_recovery_allows_transport_without_output_reset(self):
        connection, transport, _ = self.make_client()
        transport.reset_output_buffer = None
        connection.connect()
        with mock.patch.object(client.time, "sleep") as sleep:
            connection.stop()
            sleep.assert_called_once_with(0.030)
        self.assertFalse(connection.state_unknown)

    def test_not_connected_never_sends(self):
        connection, transport, _ = self.make_client()
        with self.assertRaises(client.NotConnectedError):
            connection.get_status()
        self.assertEqual(transport.writes, [])

    def test_rejected_ack_exposes_status_and_confirms_known_state(self):
        for code in (1, 2):
            with self.subTest(code=code):
                connection, transport, _ = self.make_client()
                transport.on_write = lambda req: response(req[2], req[4], result=code, active=3,
                                                         next_probe=4, flags=1)
                connection.connect()
                with self.assertRaises(client.CommandRejected) as caught:
                    connection.get_status()
                self.assertEqual(caught.exception.response.result, code)
                self.assertEqual(caught.exception.response.active_probe, 3)
                self.assertTrue(caught.exception.response.running)
                self.assertFalse(connection.state_unknown)
                self.assertEqual(connection.last_status, caught.exception.response)
                self.assertEqual(len(transport.writes), 1)

    def test_matching_semantic_errors_mark_state_unknown(self):
        invalid = [dict(result=3), dict(active=5), dict(next_probe=0), dict(next_probe=5),
                   dict(flags=4), dict(active=1, flags=0), dict(active=0, flags=1),
                   dict(active=1, flags=3)]
        for changes in invalid:
            with self.subTest(changes=changes):
                connection, transport, _ = self.make_client()
                transport.on_write = lambda req: response(req[2], req[4], **changes)
                connection.connect()
                with self.assertRaises(client.ProtocolError):
                    connection.get_status()
                self.assertTrue(connection.state_unknown)
                self.assertEqual(len(transport.writes), 1)

    def test_noise_corrupt_stale_and_wrong_command_are_skipped(self):
        connection, transport, _ = self.make_client()
        def noisy(request):
            good = response(request[2], request[4], active=4, next_probe=1, flags=1)
            return (b"\xFF\x5A" + response(request[2], 0xFF)
                    + response(client.NEXT, request[4]) + good[:-1] + b"\xFF" + good)
        transport.on_write = noisy
        connection.connect()
        status = connection.get_status()
        self.assertEqual(status.active_probe, 4)
        self.assertFalse(connection.state_unknown)
        self.assertEqual(len(transport.writes), 1)

    def test_timeout_has_no_retry_and_recovery_is_explicit(self):
        connection, transport, _ = self.make_client()
        connection.connect(check_status=True)
        transport.on_write = lambda req: b""
        with self.assertRaisesRegex(client.ResponseTimeout, "NOT retried"):
            connection.start_probe(1)
        self.assertEqual(len(transport.writes), 2)
        self.assertTrue(connection.state_unknown)
        self.assertIsNotNone(connection.last_status)  # Old snapshot must not imply current state.
        with self.assertRaises(client.StateUnknownError):
            connection.next_probe()
        self.assertEqual(len(transport.writes), 2)
        # A late START ack must not satisfy the new STATUS request.
        transport.on_write = lambda req: response(client.START, 1, active=1, flags=1) + response(req[2], req[4])
        status = connection.get_status()
        self.assertEqual(status.sequence, 2)
        self.assertFalse(connection.state_unknown)
        connection.start_probe(2)
        self.assertEqual(transport.writes[-1][4], 3)

    def test_partial_write_is_ambiguous_and_never_completed_automatically(self):
        connection, transport, _ = self.make_client()
        connection.connect(check_status=True)
        transport.write_count = 3
        with self.assertRaisesRegex(client.TransportError, "Partial serial write"):
            connection.start_probe(1)
        self.assertTrue(connection.state_unknown)
        self.assertEqual(len(transport.writes), 2)
        transport.write_count = None
        connection.stop()
        self.assertFalse(connection.state_unknown)
        self.assertEqual(transport.writes[-1][4], 2)

    def test_read_and_write_errors_mark_unknown_without_retry(self):
        for operation in ("read_error", "write_error"):
            with self.subTest(operation=operation):
                connection, transport, _ = self.make_client()
                connection.connect(check_status=True)
                setattr(transport, operation, OSError("unplugged"))
                with self.assertRaisesRegex(client.TransportError, "NOT retried"):
                    connection.start_probe(1)
                self.assertTrue(connection.state_unknown)
                self.assertEqual(len(transport.writes), 2)

    def test_sequence_wrap(self):
        factory = FakeFactory()
        with client.FpgaProbeClient("COM5", sequence_start=255, transport_factory=factory) as connection:
            self.assertEqual(connection.get_status().sequence, 255)
            self.assertEqual(connection.stop().sequence, 0)
            self.assertEqual(connection.get_status().sequence, 1)

    def test_close_and_context_exit_do_not_send_stop(self):
        factory = FakeFactory()
        with client.FpgaProbeClient("COM5", transport_factory=factory) as connection:
            self.assertTrue(connection.connected)
            self.assertEqual(factory.transport.writes, [])
            connection.get_status()
        self.assertEqual(len(factory.transport.writes), 1)
        self.assertFalse(connection.connected)
        self.assertTrue(connection.state_unknown)
        self.assertEqual(factory.transport.close_calls, 1)
        connection.close()
        self.assertEqual(factory.transport.close_calls, 1)

    def test_open_failure_closes_transport_and_does_not_send_commands(self):
        connection, transport, _ = self.make_client()
        transport.open_error = OSError("busy")
        with self.assertRaisesRegex(client.TransportError, "Cannot open"):
            connection.connect()
        self.assertFalse(connection.connected)
        self.assertEqual(transport.close_calls, 1)
        self.assertEqual(transport.writes, [])

    def test_close_failure_detaches_transport(self):
        connection, transport, _ = self.make_client()
        connection.connect()
        transport.close_error = OSError("gone")
        with self.assertRaisesRegex(client.TransportError, "FPGA may still be running"):
            connection.close()
        self.assertFalse(connection.connected)
        self.assertTrue(connection.state_unknown)

    def test_status_failure_on_connect_leaves_port_open_for_explicit_recovery(self):
        connection, transport, _ = self.make_client()
        transport.on_write = lambda req: b""
        with self.assertRaises(client.ResponseTimeout):
            connection.connect(check_status=True)
        self.assertTrue(connection.connected)
        self.assertTrue(connection.state_unknown)
        self.assertEqual(len(transport.writes), 1)
        transport.on_write = lambda req: response(req[2], req[4])
        connection.stop()
        self.assertFalse(connection.state_unknown)

    def test_many_threads_share_one_outstanding_request(self):
        connection, transport, _ = self.make_client()
        connection.connect()
        original_read = transport.read
        def slower_read(size):
            time.sleep(0.00005)
            return original_read(size)
        transport.read = slower_read
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            statuses = list(executor.map(lambda _: connection.get_status(), range(32)))
        self.assertEqual(sorted(item.sequence for item in statuses), list(range(32)))
        self.assertFalse(transport.unread_reply_on_write)
        self.assertEqual([frame[4] for frame in transport.writes], list(range(32)))

    def test_stop_waits_for_existing_transaction_not_interleaved(self):
        connection, transport, _ = self.make_client()
        connection.connect()
        read_entered, release_read = threading.Event(), threading.Event()
        original_read = transport.read
        def blocking_read(size):
            if not read_entered.is_set():
                read_entered.set()
                if not release_read.wait(1):
                    raise AssertionError("test read release timed out")
            return original_read(size)
        transport.read = blocking_read
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(connection.get_status)
            self.assertTrue(read_entered.wait(1))
            second = executor.submit(connection.stop)
            self.assertEqual(len(transport.writes), 1)
            release_read.set()
            self.assertEqual(first.result().command, client.STATUS)
            self.assertEqual(second.result().command, client.STOP)
        self.assertFalse(transport.unread_reply_on_write)

    def test_invalid_constructor_arguments(self):
        invalid = [dict(port=""), dict(timeout=0), dict(timeout=float("nan")),
                   dict(timeout=float("inf")), dict(write_timeout=-1),
                   dict(sequence_start=-1), dict(sequence_start=256)]
        for fields in invalid:
            args = {"port": "COM5", **fields}
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                client.FpgaProbeClient(**args)


class CodecTests(unittest.TestCase):
    def test_golden_packets(self):
        self.assertEqual(client.encode_request(client.START, 4, 0), bytes.fromhex("A5 5A 10 04 00 14"))
        self.assertEqual(client.encode_request(client.STOP, 0, 0xA5), bytes.fromhex("A5 5A 12 00 A5 B7"))
        status = client.decode_response(response(active=0, next_probe=3, flags=2))
        self.assertTrue(status.completed)
        self.assertFalse(status.running)

    def test_request_validation(self):
        for args in [(0xFF, 0, 0), (client.START, 0, 0), (client.START, 5, 0),
                     (client.STOP, 1, 0), (client.STATUS, 0, -1), (client.NEXT, 0, 256)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                client.encode_request(*args)

    def test_response_framing_validation(self):
        good = response()
        for frame in (b"", good[:-1], b"\x00" + good[1:], good[:-1] + b"\xFF"):
            with self.subTest(frame=frame), self.assertRaises(client.ProtocolError):
                client.decode_response(frame)


class IntegrationExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        example_path = CLIENT_PATH.with_name("example_integration.py")
        example_spec = importlib.util.spec_from_file_location("example_integration", example_path)
        cls.example = importlib.util.module_from_spec(example_spec)
        example_spec.loader.exec_module(cls.example)

    def status(self, active=0, completed=False):
        return client.ProbeStatus(client.STATUS, 0, 0, active, 1, 1 if active else (2 if completed else 0))

    def test_arm_before_start_waits_for_normal_completion_and_returns_final_status(self):
        log = []
        controller, afe = mock.Mock(), mock.Mock()
        snapshots = iter([self.status(), self.status(active=2), self.status(completed=True)])
        controller.get_status.side_effect = lambda: (log.append("status"), next(snapshots))[1]
        controller.start_probe.side_effect = lambda probe: (log.append("start"), self.status(active=probe))[1]
        afe.arm_external_trigger.side_effect = lambda **kwargs: (log.append("arm"), True)[1]
        afe.wait_and_read.side_effect = lambda **kwargs: (log.append("samples"), "verified_samples")[1]
        with mock.patch.object(self.example.time, "monotonic", return_value=0.0), \
             mock.patch.object(self.example.time, "sleep") as sleep:
            status, samples = self.example.acquire_one_probe(controller, afe, 2)
        self.assertEqual(log, ["status", "arm", "start", "samples", "status", "status"])
        self.assertTrue(status.completed)
        self.assertFalse(status.running)
        self.assertEqual(samples, "verified_samples")
        sleep.assert_called_once_with(0.1)
        afe.arm_external_trigger.assert_called_once_with(probe=2, trigger_count=50_000, prf_hz=10_000)
        afe.cancel.assert_called_once()
        controller.stop.assert_not_called()

    def test_bad_start_ack_is_rejected_before_reading_samples(self):
        for acknowledgement in (self.status(), self.status(active=3)):
            with self.subTest(acknowledgement=acknowledgement):
                controller, afe = mock.Mock(), mock.Mock()
                controller.get_status.return_value = self.status()
                controller.start_probe.return_value = acknowledgement
                afe.arm_external_trigger.return_value = True
                with self.assertRaisesRegex(RuntimeError, "START ACK"):
                    self.example.acquire_one_probe(controller, afe, 2)
                afe.wait_and_read.assert_not_called()
                afe.cancel.assert_called_once()
                controller.stop.assert_not_called()

    def test_observed_channel_change_or_abnormal_stop_discards_capture(self):
        for final in (self.status(active=3), self.status()):
            with self.subTest(final=final):
                controller, afe = mock.Mock(), mock.Mock()
                controller.get_status.side_effect = [self.status(), final]
                controller.start_probe.return_value = self.status(active=2)
                afe.arm_external_trigger.return_value = True
                with self.assertRaisesRegex(RuntimeError, "discard capture"):
                    self.example.acquire_one_probe(controller, afe, 2)
                afe.cancel.assert_called_once()
                controller.stop.assert_not_called()

    def test_completion_deadline_expires_without_stop_or_start_retry(self):
        controller, afe = mock.Mock(), mock.Mock()
        controller.get_status.side_effect = [self.status(), self.status(active=2)]
        controller.start_probe.return_value = self.status(active=2)
        afe.arm_external_trigger.return_value = True
        with mock.patch.object(self.example.time, "monotonic", side_effect=[0.0, 0.001, 7.001]), \
             self.assertRaisesRegex(TimeoutError, "within 7 s"):
            self.example.acquire_one_probe(controller, afe, 2)
        controller.start_probe.assert_called_once_with(2)
        controller.stop.assert_not_called()
        afe.cancel.assert_called_once()

    def test_afe_capture_validation_error_is_propagated(self):
        controller, afe = mock.Mock(), mock.Mock()
        controller.get_status.return_value = self.status()
        controller.start_probe.return_value = self.status(active=2)
        afe.arm_external_trigger.return_value = True
        afe.wait_and_read.side_effect = RuntimeError("AFE overflow or fewer than 50000 triggers")
        with self.assertRaisesRegex(RuntimeError, "AFE overflow"):
            self.example.acquire_one_probe(controller, afe, 2)
        controller.get_status.assert_called_once()  # No false completion check after bad samples.
        controller.stop.assert_not_called()
        afe.cancel.assert_called_once()

    def test_failed_arm_never_sends_start_and_always_cancels(self):
        for fails_by_exception in (False, True):
            controller, afe = mock.Mock(), mock.Mock()
            controller.get_status.return_value = self.status()
            if fails_by_exception:
                afe.arm_external_trigger.side_effect = RuntimeError("arm error")
            else:
                afe.arm_external_trigger.return_value = False
            with self.assertRaises(RuntimeError):
                self.example.acquire_one_probe(controller, afe, 2)
            controller.start_probe.assert_not_called()
            controller.stop.assert_not_called()
            afe.cancel.assert_called_once()


if __name__ == "__main__":
    unittest.main()
