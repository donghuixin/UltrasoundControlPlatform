"""Continuous-recording integration skeleton; executing this file opens no port.

Supply a real AFE/TSW SDK adapter. Do not authorize a real transmission with a
mock adapter that merely claims the receiver is armed. User actions drive each
method: there is no automatic scan, STOP, timeout fallback or background thread.
"""
import math
from typing import Any, Protocol

from fpga_probe_client import FpgaProbeClient, ProbeStatus


class AcquisitionAdapter(Protocol):
    """Application-supplied acquisition API, separate from the FPGA UART."""

    def arm_continuous_external_trigger(self, *, prf_hz: int) -> bool:
        """Start indefinite recording; True ONLY after hardware is ready for J11.

        Accept gaps while FPGA is idle, 10 kHz steady triggers and truncated /
        irregularly spaced boundary pulses at a probe change. No fixed count.
        """
        ...

    def read_verified_chunk(self, *, timeout_s: float) -> Any:
        """Read a bounded chunk; validate records, overflow and drop indicators.

        Include acquisition timestamps / trigger indices. Do NOT assign an exact
        probe ID from an ACK or STATUS: no channel marker exists on J11. Raise
        on invalid samples; a read timeout does not imply FPGA transmission ended.
        """
        ...

    def cancel(self) -> None:
        """Stop recording/release buffers; never stops the FPGA transmitter."""
        ...


class ContinuousAcquisition:
    """Call in an application-owned worker, only following explicit user actions.

    Connect the client first; physically verify firmware and acquisition settings.
    Initial arming requires idle FPGA. Once armed, use S2 or select_probe / next_probe
    without restarting acquisition. read_chunk does not wait for DONE or a count.

    Continuous firmware has NO automatic expiry. USB disconnection, client.close,
    a read error, process exit or cancellation leaves TX running. The application
    must provide an explicit STOP action and a separate hardware safe-stop path.

    STATUS is only a snapshot: S2 changes between polls cannot be reconstructed.
    Store raw continuous data and mark uncertain channel-transition intervals.
    This protocol cannot precisely label every recorded frame by probe number.
    """

    def __init__(self, client: FpgaProbeClient, afe: AcquisitionAdapter) -> None:
        self.client = client
        self.afe = afe
        self.recording = False  # Last successful arm, NOT a live hardware health flag.

    def arm_recording(self) -> ProbeStatus:
        """Explicitly prepare reception; sends STATUS only, never START or STOP."""
        if self.recording:
            raise RuntimeError("Recording is already armed; do not re-arm on probe switches")
        initial = self.client.get_status()
        if initial.running:
            raise RuntimeError("FPGA is active; explicitly STOP before initially arming recording")
        try:
            if not self.afe.arm_continuous_external_trigger(prf_hz=10_000):
                raise RuntimeError("AFE did not confirm ready: no START was sent")
        except Exception:
            self.afe.cancel()
            raise
        self.recording = True
        return initial

    def _require_recording(self) -> None:
        if not self.recording:
            raise RuntimeError("Arm the real receiver before selecting a transmitting probe")

    def select_probe(self, probe: int) -> ProbeStatus:
        """Explicit UI selection; replaces/restarts TX, leaves receiver running."""
        if type(probe) is not int or probe not in range(1, 5):
            raise ValueError("probe must be 1..4")
        self._require_recording()
        status = self.client.start_probe(probe)
        if not status.running or status.active_probe != probe:
            raise RuntimeError("START ACK does not report the requested probe; "
                               "mark transition uncertain and use explicit STATUS/STOP recovery")
        # First J11 may precede the ACK. It is NOT an acquisition timestamp.
        return status

    def next_probe(self) -> ProbeStatus:
        """Explicit UI 'next' action; S2 changes the same next-probe cursor."""
        self._require_recording()
        status = self.client.next_probe()
        if not status.running:
            raise RuntimeError("NEXT ACK does not report running; use explicit STATUS/STOP recovery")
        return status

    def read_chunk(self, *, timeout_s: float = 1.0) -> Any:
        """Read while recording continues; errors never silently retry/stop TX."""
        self._require_recording()
        if (isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float))
                or not math.isfinite(timeout_s) or timeout_s <= 0):
            raise ValueError("timeout_s must be finite and positive")
        return self.afe.read_verified_chunk(timeout_s=timeout_s)

    def get_status(self) -> ProbeStatus:
        """Caller may poll for UI/logging; not precise channel labels or timing."""
        return self.client.get_status()

    def stop_transmission(self) -> ProbeStatus:
        """Explicit STOP; receiver remains armed so recording need not be interrupted."""
        status = self.client.stop()
        if status.running or status.active_probe != 0:
            raise RuntimeError("STOP not confirmed; keep state uncertain and request recovery")
        return status

    def finish_recording(self) -> ProbeStatus:
        """Explicitly close reception AFTER a confirmed idle snapshot; no auto STOP.

        S2 must not be operated concurrently. A status query cannot lock the button;
        safe physical shutdown needs the application's hardware procedure as well.
        """
        self._require_recording()
        status = self.client.get_status()
        if status.running:
            raise RuntimeError("FPGA is still transmitting; explicitly STOP before closing reception")
        self.afe.cancel()
        self.recording = False
        return status


if __name__ == "__main__":
    print("Integration skeleton only: no USB port opened and no command sent.")
    print("Use ContinuousAcquisition with a real receiver SDK in your application worker.")
    print("Arm once; switch probes by explicit user actions; explicitly STOP to stop TX.")
