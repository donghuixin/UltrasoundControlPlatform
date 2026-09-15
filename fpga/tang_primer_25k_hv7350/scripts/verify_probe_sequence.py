#!/usr/bin/env python3
"""Compile and simulate the four-probe controller with Icarus Verilog.

Use IVERILOG and VVP environment variables for a portable tool installation.
Default: timing, buttons, UART integration, and a continuous 20-frame run.
--full-duration additionally simulates all 300 million clocks of a 6 s run,
past the former 5 s limit, and verifies that only explicit STOP ends output.
If VERILATOR is set or verilator is on PATH, the full-duration case is compiled
for speed. Optional VERILATOR_CFLAGS is passed verbatim as one -CFLAGS argument.
No hardware is programmed and generated simulation files stay in a temp folder.
"""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def executable(name: str, environment: str) -> str:
    candidate = os.environ.get(environment) or shutil.which(name)
    if not candidate:
        raise SystemExit(f"{name} not found; install Icarus Verilog or set {environment}.")
    return candidate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-duration", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    iverilog = executable("iverilog", "IVERILOG")
    vvp = executable("vvp", "VVP")
    sources = [root / "src/pmod_led.v", root / "src/probe_uart_control.v",
               root / "tests/tb_probe_sequence.sv"]
    with tempfile.TemporaryDirectory(prefix="probe-sequence-") as directory:
        for top in ("tb_probe_sequence", "tb_probe_duration"):
            verilator = os.environ.get("VERILATOR") or shutil.which("verilator")
            if top == "tb_probe_duration" and args.full_duration and verilator:
                build = Path(directory) / "compiled-duration"
                compile_command = [verilator, "--binary", "--timing", "-O3", "-Wno-fatal",
                                   "-j", "4", "--top-module", top, "--Mdir", str(build)]
                if os.environ.get("VERILATOR_CFLAGS"):
                    compile_command += ["-CFLAGS", os.environ["VERILATOR_CFLAGS"]]
                compile_command += list(map(str, sources))
                subprocess.run(compile_command, check=True, cwd=root)
                print("Running tb_probe_duration (compiled full six seconds)", flush=True)
                subprocess.run([str(build / f"V{top}"), "+FULL_DURATION"], check=True, cwd=root)
                continue
            binary = Path(directory) / f"{top}.vvp"
            subprocess.run([iverilog, "-g2012", "-Wall", "-s", top, "-o", str(binary),
                            *map(str, sources)], check=True, cwd=root)
            command = [vvp, str(binary)]
            if top == "tb_probe_duration" and args.full_duration:
                command.append("+FULL_DURATION")
            print(f"Running {top}" + (" (full six seconds)" if len(command) == 3 else ""),
                  flush=True)
            subprocess.run(command, check=True, cwd=root)


if __name__ == "__main__":
    main()
