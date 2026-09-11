"""Independent golden-frame checks; no serial, FPGA, or external dependency.

The reference transition below is deliberately separate from the production
encoder. It models only request effects, without concurrent button/expiry events.
RTL tests remain responsible for cycle timing and actual UART parsing behavior.
"""
import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
VECTORS = json.loads((ROOT / "tests/probe_protocol_vectors.json").read_text())
SPEC = importlib.util.spec_from_file_location(
    "control_probes_vectors", ROOT / "scripts/control_probes.py")
CONTROL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CONTROL
SPEC.loader.exec_module(CONTROL)


def independent_xor(values):
    result = 0
    for value in values:
        result ^= value
    return result


def transition(initial, command, argument):
    """Return result, public state and timer action for a valid wire request."""
    state = dict(initial)
    if command not in (0x10, 0x11, 0x12, 0x13):
        return 1, state, "none"
    if command == 0x10:
        if argument not in (1, 2, 3, 4):
            return 2, state, "none"
    elif argument != 0:
        return 2, state, "none"
    if command in (0x10, 0x11):
        selected = argument if command == 0x10 else state["next"]
        return 0, {"active": selected, "next": selected % 4 + 1,
                   "completed": False}, "restart"
    if command == 0x12:
        state.update(active=0, completed=False)
        return 0, state, "stop"
    return 0, state, "none"


class GoldenVectorTests(unittest.TestCase):
    def test_vector_inventory(self):
        vectors = VECTORS["vectors"]
        self.assertEqual(VECTORS["schema_version"], 1)
        self.assertEqual(len(vectors), 12)
        self.assertEqual(len({v["id"] for v in vectors}), len(vectors))
        self.assertEqual(
            {v["argument"] for v in vectors if v["command"] == 0x10 and not v["result"]},
            {1, 2, 3, 4})

    def test_request_frames_and_checksums(self):
        for vector in VECTORS["vectors"]:
            with self.subTest(vector=vector["id"]):
                body = bytes((vector["command"], vector["argument"], vector["sequence"]))
                expected = b"\xA5\x5A" + body + bytes((independent_xor(body),))
                self.assertEqual(bytes.fromhex(vector["request_hex"]), expected)

    def test_independent_state_transitions(self):
        for vector in VECTORS["vectors"]:
            with self.subTest(vector=vector["id"]):
                result, state, effect = transition(
                    vector["initial"], vector["command"], vector["argument"])
                self.assertEqual(result, vector["result"])
                self.assertEqual(state, vector["expected"])
                self.assertEqual(effect, vector["session_effect"])

    def test_response_frames_and_checksums(self):
        for vector in VECTORS["vectors"]:
            with self.subTest(vector=vector["id"]):
                state = vector["expected"]
                flags = int(state["active"] != 0) | (int(state["completed"]) << 1)
                body = bytes((vector["command"], vector["sequence"], vector["result"],
                              state["active"], state["next"], flags))
                expected = b"\x5A\xA5" + body + bytes((independent_xor(body),))
                self.assertEqual(bytes.fromhex(vector["response_hex"]), expected)

    def test_production_encoder_valid_vectors(self):
        names = {value: name for name, value in CONTROL.COMMANDS.items()}
        for vector in VECTORS["vectors"]:
            if vector["result"]:
                continue
            with self.subTest(vector=vector["id"]):
                name = names[vector["command"]]
                probe = vector["argument"] if name == "start" else None
                self.assertEqual(
                    CONTROL.encode_request(name, probe, vector["sequence"]),
                    bytes.fromhex(vector["request_hex"]))

    def test_production_decoder_all_vectors(self):
        for vector in VECTORS["vectors"]:
            with self.subTest(vector=vector["id"]):
                response = CONTROL.decode_response(bytes.fromhex(vector["response_hex"]),
                                                   vector["command"], vector["sequence"])
                self.assertEqual(response.result, vector["result"])
                self.assertEqual(response.active, vector["expected"]["active"])
                self.assertEqual(response.next_probe, vector["expected"]["next"])
                self.assertEqual(response.completed, vector["expected"]["completed"])
                self.assertEqual(response.running, vector["expected"]["active"] != 0)

    def test_duplicate_start_is_not_deduplicated(self):
        vectors = {v["id"]: v for v in VECTORS["vectors"]}
        first = vectors["start_hv2"]
        duplicate = vectors["duplicate_start_seq"]
        self.assertEqual(duplicate["request_hex"], first["request_hex"])
        self.assertEqual(duplicate["response_hex"], first["response_hex"])
        result, state, effect = transition(duplicate["initial"], duplicate["command"],
                                           duplicate["argument"])
        self.assertEqual((result, state, effect),
                         (0, duplicate["expected"], "restart"))


if __name__ == "__main__":
    unittest.main()
