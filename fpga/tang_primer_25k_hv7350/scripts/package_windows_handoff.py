#!/usr/bin/env python3
"""Create a portable, checksummed Windows handoff ZIP. Never opens hardware.

Generated ZIP/manifest are mechanical artifacts, not an installer. The Markdown
contract must be rendered with render_usb_handoff.mjs before packaging.
"""
from pathlib import Path
import hashlib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NAME = "FPGA_4PROBE_WINDOWS_HANDOFF_20260911"
EXPECTED_FS_SHA256 = "a4dfe8bd5030e336c011ed138eb02b064a19936257fac45c7c2f24a8aea0be63"


def main():
    files = {ROOT / "README_WINDOWS_HANDOFF.md", ROOT / "pmod_led.gprj"}
    for directory, suffixes in (
        ("src", {".v", ".cst", ".sdc"}),
        ("scripts", {".py", ".tcl", ".mjs"}),
        ("tests", {".py", ".sv", ".v", ".json"}),
        ("docs", {".md"}),
        ("host", {".py", ".cs", ".csproj", ".md"}),
    ):
        for file in (ROOT / directory).rglob("*"):
            if file.is_file() and file.suffix in suffixes and not ({"bin", "obj", "__pycache__"} & set(file.parts)):
                files.add(file)
    html = ROOT / "docs/USB_WINDOWS_INTERFACE_HANDOFF.html"
    markdown = ROOT / "docs/USB_WINDOWS_INTERFACE_HANDOFF.md"
    if not html.exists() or html.stat().st_mtime < markdown.stat().st_mtime:
        raise SystemExit("Render the updated USB handoff HTML before packaging.")
    files.add(html)
    for name in (
        "pmod_led_4probe_5s_2p2mhz_2cycles_10khz_uart.fs",
        "pmod_led_4probe_5s_2p2mhz_2cycles_10khz_uart.bin",
        "README_four_probe_20260911.md",
        "pmod_led_FINAL_2p2mhz_2cycles_pos_fixed140ns_neg30v_100ns_autostart.fs",
        "source_before_four_probe_20260911.tar.gz",
    ):
        files.add(ROOT / "burn_test" / name)
    new_fs = ROOT / "burn_test/pmod_led_4probe_5s_2p2mhz_2cycles_10khz_uart.fs"
    if hashlib.sha256(new_fs.read_bytes()).hexdigest() != EXPECTED_FS_SHA256:
        raise SystemExit("Firmware differs from the approved/documented release; update and re-verify it first.")
    entries = []
    for file in sorted(files):
        data = file.read_bytes()
        entries.append((file.relative_to(ROOT).as_posix(), data))
    manifest = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in entries)
    destination = ROOT / "handoff"
    destination.mkdir(exist_ok=True)
    output = destination / f"{NAME}.zip"
    # Re-running regenerates this task's artifact only, not firmware or user data.
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in entries:
            archive.writestr(f"{NAME}/{name}", data)
        archive.writestr(f"{NAME}/MANIFEST_SHA256.txt", manifest)
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        for name, data in entries:
            assert archive.read(f"{NAME}/{name}") == data
    print(f"PASS: ZIP CRC and byte-for-byte verification for {len(entries)} files")
    print(f"ZIP: {output}")
    print(f"SHA256: {hashlib.sha256(output.read_bytes()).hexdigest()}")
    print(f"Size: {output.stat().st_size} bytes")


if __name__ == "__main__":
    main()
