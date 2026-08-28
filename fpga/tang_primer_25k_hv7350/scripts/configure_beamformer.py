#!/usr/bin/env python3
"""Configure the eight-channel Tang Primer/HV7350 beamformer over UART."""

import argparse
import math
import os
import struct
import sys
import termios


FPGA_CLOCK_HZ = 50_000_000
PHASE_SCALE = 1 << 32
PRF_PERIOD_TICKS = 5000
CHANNEL_COUNT = 8
S1_ANGLES_DEG = tuple(range(-10, 11, 2))


def steering_delays(angle_deg, pitch_mm, sound_speed, reverse_array):
    angle_rad = math.radians(angle_deg)
    pitch_m = pitch_mm / 1000.0
    positions = [(index - 3.5) * pitch_m for index in range(CHANNEL_COUNT)]

    if reverse_array:
        positions.reverse()

    raw_delays = [position * math.sin(angle_rad) / sound_speed
                  for position in positions]
    minimum_delay = min(raw_delays)
    normalized_delays = [delay - minimum_delay for delay in raw_delays]
    delay_ticks = [int(round(delay * FPGA_CLOCK_HZ))
                   for delay in normalized_delays]
    return normalized_delays, delay_ticks


def encode_packet(command, word, value, delay_ticks):
    body = bytearray([command])
    body.extend(struct.pack("<I", word))
    body.append(value)

    for delay in delay_ticks:
        body.extend(struct.pack("<H", delay))

    checksum = 0
    for value in body:
        checksum ^= value

    packet = bytearray([0xA5, 0x5A])
    packet.extend(body)
    packet.append(checksum)
    return bytes(packet)


def build_config_packet(frequency_hz, burst_cycles, delay_ticks):
    frequency_word = int(round(frequency_hz * PHASE_SCALE / FPGA_CLOCK_HZ))
    packet = encode_packet(0x01, frequency_word, burst_cycles, delay_ticks)
    return packet, frequency_word


def build_angle_table_packet(angle_index, delay_ticks):
    return encode_packet(0x02, 0, angle_index, delay_ticks)


def configure_serial(fd):
    attributes = termios.tcgetattr(fd)
    attributes[0] = 0
    attributes[1] = 0
    attributes[2] = termios.CLOCAL | termios.CREAD | termios.CS8
    attributes[3] = 0
    attributes[4] = termios.B115200
    attributes[5] = termios.B115200
    attributes[6][termios.VMIN] = 0
    attributes[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, attributes)


def send_packets(port, packets):
    payload = b"".join(packets)
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY)
    try:
        configure_serial(fd)
        bytes_written = 0
        while bytes_written < len(payload):
            bytes_written += os.write(fd, payload[bytes_written:])
        termios.tcdrain(fd)
    finally:
        os.close(fd)

    if bytes_written != len(payload):
        raise RuntimeError(
            f"Only wrote {bytes_written} of {len(payload)} packet bytes"
        )

    return bytes_written


def parse_args():
    parser = argparse.ArgumentParser(
        description="Send frequency and steering angle to the FPGA beamformer"
    )
    parser.add_argument(
        "--port",
        help="Serial device, for example /dev/cu.usbserial-0001",
    )
    parser.add_argument(
        "--frequency-mhz",
        type=float,
        default=2.2,
        help="Transmit carrier frequency from 1.0 to 4.0 MHz (default: 2.2)",
    )
    parser.add_argument(
        "--angle-deg",
        type=float,
        required=True,
        help="Far-field steering angle from -90 to +90 degrees",
    )
    parser.add_argument(
        "--pitch-mm",
        type=float,
        required=True,
        help="Center-to-center transducer element spacing in millimeters",
    )
    parser.add_argument(
        "--sound-speed",
        type=float,
        default=1540.0,
        help="Propagation speed in m/s (default: 1540 for soft tissue)",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=2,
        help="Carrier cycles per burst, 1 to 32 (default: 2)",
    )
    parser.add_argument(
        "--reverse-array",
        action="store_true",
        help="Reverse CH1..CH8 physical order and steering sign",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print delays and packet without opening the serial port",
    )
    return parser.parse_args()


def validate_args(args):
    if not 1.0 <= args.frequency_mhz <= 4.0:
        raise ValueError("frequency must be between 1.0 and 4.0 MHz")
    if not -90.0 <= args.angle_deg <= 90.0:
        raise ValueError("angle must be between -90 and +90 degrees")
    if args.pitch_mm <= 0.0:
        raise ValueError("pitch must be greater than zero")
    if args.sound_speed <= 0.0:
        raise ValueError("sound speed must be greater than zero")
    if not 1 <= args.cycles <= 32:
        raise ValueError("cycles must be between 1 and 32")
    if not args.dry_run and not args.port:
        raise ValueError("--port is required unless --dry-run is used")


def main():
    args = parse_args()

    try:
        validate_args(args)
        frequency_hz = args.frequency_mhz * 1_000_000.0
        delays_s, delay_ticks = steering_delays(
            args.angle_deg,
            args.pitch_mm,
            args.sound_speed,
            args.reverse_array,
        )

        angle_profiles = []
        for angle in S1_ANGLES_DEG:
            _, profile_ticks = steering_delays(
                angle,
                args.pitch_mm,
                args.sound_speed,
                args.reverse_array,
            )
            angle_profiles.append(profile_ticks)

        burst_ticks = int(math.ceil(args.cycles * FPGA_CLOCK_HZ / frequency_hz))
        if max(delay_ticks) + burst_ticks >= PRF_PERIOD_TICKS:
            raise ValueError(
                "maximum steering delay plus burst duration exceeds the 100 us frame"
            )
        if max(delay_ticks) > 0xFFFF:
            raise ValueError("a channel delay exceeds the 16-bit packet field")

        config_packet, frequency_word = build_config_packet(
            frequency_hz,
            args.cycles,
            delay_ticks,
        )
        table_packets = [
            build_angle_table_packet(index, profile)
            for index, profile in enumerate(angle_profiles)
        ]
        packets = table_packets + [config_packet]
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    actual_frequency = frequency_word * FPGA_CLOCK_HZ / PHASE_SCALE
    print(f"Requested carrier : {frequency_hz / 1e6:.6f} MHz")
    print(f"NCO carrier       : {actual_frequency / 1e6:.6f} MHz")
    print(f"Steering angle    : {args.angle_deg:.3f} deg")
    print(f"Element pitch     : {args.pitch_mm:.6f} mm")
    print(f"Burst             : {args.cycles} cycles")
    print("Channel delays:")
    for index, (delay_s, ticks) in enumerate(zip(delays_s, delay_ticks), start=1):
        print(f"  CH{index}: {delay_s * 1e9:9.3f} ns -> {ticks:4d} ticks "
              f"({ticks * 20:4d} ns)")
    print("Scan angle table:")
    for angle, profile in zip(S1_ANGLES_DEG, angle_profiles):
        print(f"  {angle:+3d} deg: {profile}")
    packet_text = " ".join(f"{value:02x}" for value in config_packet)
    print(f"Config packet     : {packet_text}")
    print(f"Table packets     : {len(table_packets)} x {len(table_packets[0])} bytes")

    if args.dry_run:
        print("Dry run: packets were not sent.")
    else:
        bytes_written = send_packets(args.port, packets)
        print(f"Sent {bytes_written} bytes to {args.port} at 115200 baud.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
