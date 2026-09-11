"""AFE-first integration skeleton. Running this file DOES NOT open any port.

Replace the AFE adapter with your acquisition SDK in the host application.
Do not use a mock AFE that claims to be armed to authorize a real transmission.
"""
import time
from typing import Any, Protocol

from fpga_probe_client import FpgaProbeClient, ProbeStatus


class AcquisitionAdapter(Protocol):
    """Your AFE/TSW SDK adapter, not implemented by the FPGA UART client."""

    def arm_external_trigger(self, *, probe: int, trigger_count: int, prf_hz: int) -> bool:
        """Configure/start buffering, and return True ONLY after hardware is ready."""
        ...

    def wait_and_read(self, *, timeout_s: float) -> Any:
        """Return ONLY a verified full capture within timeout_s.

        The adapter must verify exactly the armed trigger_count (50,000 here),
        expected samples per record, and no overflow/dropped/invalid records.
        Raise on any failure; the FPGA STATUS cannot validate captured samples.
        """
        ...

    def cancel(self) -> None:
        """Cancel capture and release buffers. This does NOT stop the FPGA."""
        ...


def acquire_one_probe(client: FpgaProbeClient, afe: AcquisitionAdapter, probe: int) -> tuple[ProbeStatus, Any]:
    """Call from a worker thread after explicit user authorization to transmit.

    Preconditions: client connected, correct firmware physically verified,
    no active FPGA session, acquisition settings/load safe, and S2 not used
    concurrently. AFE must accept J11 external rising edges and 10 kHz triggers.
    Each full session has 50,000 triggers, with the burst beginning 2 us later.
    Returns (final completed status, verified samples), NOT the initial START ACK.
    Capture/completion deadline is approximately 7 s from sending START; a serial
    transaction already in flight remains bounded by the client's own timeouts.

    STATUS has no session ID: polling catches observed channel changes/stops,
    but cannot prove absence of a brief S2 change/restart between polls. Do not
    operate S2 or another client during this acquisition.
    """
    if type(probe) is not int or probe not in range(1, 5):
        raise ValueError("probe must be 1..4")
    initial = client.get_status()
    if initial.running:
        raise RuntimeError("An FPGA session is active; explicitly STOP it before arming a new capture")
    try:
        if not afe.arm_external_trigger(probe=probe, trigger_count=50_000, prf_hz=10_000):
            raise RuntimeError("AFE did not confirm ready: START was NOT sent")
        deadline = time.monotonic() + 7.0
        acknowledgement = client.start_probe(probe)  # Only AFTER the AFE has armed.
        if not acknowledgement.running or acknowledgement.active_probe != probe:
            raise RuntimeError("START ACK does not report the requested probe running; "
                               "capture invalid, use explicit STATUS/STOP recovery")
        # J11 may already have fired before this ACK arrives. It is NOT a trigger.
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Acquisition deadline expired after START; FPGA state needs explicit recovery")
        samples = afe.wait_and_read(timeout_s=min(6.0, remaining))
        # The last trigger arrives before the FPGA's 5 s session has ended.
        # Do not hand the next probe to the caller while the old one is running.
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("FPGA did not confirm normal completion within 7 s; "
                                   "use explicit STATUS/STOP recovery")
            final = client.get_status()
            if time.monotonic() >= deadline:
                raise TimeoutError("FPGA completion confirmation exceeded the acquisition deadline")
            if final.running:
                if final.active_probe != probe:
                    raise RuntimeError("FPGA probe changed during acquisition; discard capture "
                                       "and use explicit STATUS/STOP recovery")
            elif final.completed:
                return final, samples
            else:
                raise RuntimeError("FPGA stopped without normal completion; discard capture "
                                   "and use explicit STATUS/STOP recovery")
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
    finally:
        afe.cancel()
        # Deliberately no automatic FPGA STOP/retry here. The application owns
        # that policy. On an ambiguous START failure, show UNKNOWN and offer an
        # explicit STOP or STATUS action. Closing USB alone does not stop TX.


if __name__ == "__main__":
    print("Integration skeleton only: no USB port opened and no command sent.")
    print("Import FpgaProbeClient and acquire_one_probe into your worker thread;")
    print("supply a real AFE SDK adapter that confirms hardware armed BEFORE START.")
