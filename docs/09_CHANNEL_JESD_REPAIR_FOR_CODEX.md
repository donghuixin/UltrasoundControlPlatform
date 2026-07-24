# AFE58JD48 / TSW14J50 channel-independence repair

## 1. What is proved, and what is not

The failing captures contain persistent bit-exact duplicate columns such as
`3=5`, `4=6`, `9=15` and `10=16`. Ordinary acoustic crosstalk does not make
multi-megabyte ADC columns bit-for-bit identical, so the digital transport,
de-framing, profile or channel mapping must be repaired before receive-DAS.

The statement that 120 MSPS, eight-lane, PLL 40x, no-demod operation is valid
only in Subclass 2 is **not supported by the TI files installed on this
workstation**:

- SLOU521's eight-lane capture procedure selects `JESD: 120M 8L Subclass 1`.
- The AFE GUI package contains both `Custom_PLL_MODE_40x_No Demod_SubClass1`
  and `...SubClass2` firmware INIs.
- The device data sheet states support for Subclasses 0, 1 and 2.

The initial setup did contain a K mismatch, but subsequent controlled tests show
that it was not the root cause:

| Field | AFE TI 120M/8L quick-start | HSDC `M16_FIXED` |
|---|---:|---:|
| Subclass | 1 | 1 |
| Aggregate L | 8 (4 per die) | 8 |
| Aggregate M | 16 (8 per die) | 16 |
| F / S / N | 4 / 1 / 16 | 4 / 1 / 16 |
| K | **16** (`AFE Reg34=0x090F`) | **8** |
| lane map | 3,2,1,0,5,4,7,6 | 3,2,1,0,5,4,7,6 |
| channel pattern | sequential 1..16 | sequential 1..16 |

The first experiment changed only AFE K from 16 to 8. It failed. A fully matched
Subclass-2/K=8 test also failed. Finally, the TI-installed original 8-lane,
40x/no-demod/Subclass-1 profile failed with the same byte-identical output.
The persistent mapping is `3=5`, `4=6`, `9=15`, `10=16`, with AFE channels
3, 4, 15 and 16 missing. See `docs/11_JESD_CHANNEL_DUPLICATION_INCIDENT_REPORT.md`.

## 2. Safety state for digital transport tests

1. Disconnect or switch off TX7316 high-voltage rails. Keep `TX_BF_MODE=0`
   and CW disabled. The transducer and gel are not needed.
2. Leave AFE58JD48EVM, its FMC/transition connection and TSW14J50 powered as
   required by their guides.
3. Do not alter AFE gain, TGC, PRF or TX voltage during this repair. They cannot
   repair a digital lane/de-framing fault.
4. Close all automation clients that may own the HSDC or AFE GUI. One owner per
   board avoids stale profile and DLL state.

## 3. Preserve the rollback state

Before changing anything, record screenshots and read back both AFE dies:

- `Reg31` (PLL mode)
- `Reg34` (Subclass / JESD version / K)
- `Reg35` (L)
- `Reg36` (M)

Also preserve the currently selected HSDC device name. Do not overwrite the
installed TI files. The repository holds named candidate and rollback copies.

## 4. Gate 1 — matched Subclass 1 / K=8

### 4.1 Initialize in a known order

1. Start HSDC Pro and AFE58JD48 GUI as Administrator.
2. In the AFE GUI run `DUT RESET`, `INITIALIZE LMK`, `AFE RESET`, then
   `INITIALIZE AFE`.
3. Load TI Quick Start output format `JESD 120MSPS_Subclass1_8L.CFG`.
4. Immediately load repository overlay
   `configs/afe58jd48/AFE58JD48_120M_8L_S1_K8.cfg`.
5. Read back both dies. Required values are:

   - `Reg31 = 0x02C0` — PLL 40x
   - `Reg34 = 0x0907` — Subclass 1, JESD204B, K=8
   - `Reg35 = 0x03C0` — L=4 per die
   - `Reg36 = 0x0007` — M=8 per die

   Stop if either die differs.

6. In HSDC select `AFE58JD48_120M_8L_M16_FIXED`, then reload the device INI and
   reconnect the TSW14J50. The profile must report L/M/F/S/N/K as
   `8/16/4/1/16/8`, Subclass 1, sequential channels, and lane mapping
   `3,2,1,0,5,4,7,6`.
7. A normal HSDC capture must complete without DDR timeout or JESD/SYNC error.

### 4.2 Prove transport mapping without acoustics

1. In the AFE GUI load
   `configs/afe58jd48/ADC_UNIQUE_CODES_16CH.cfg`.
2. Capture 65,536 samples per channel in HSDC and save raw binary as
   `jesd_s1_k8_unique_codes.bin`. Disable averaging and external trigger for
   this test.
3. Run from the repository root:

   ```powershell
   python automation/jesd_transport_qa.py "C:\path\jesd_s1_k8_unique_codes.bin"
   ```

4. Gate-1 PASS requires all of the following:

   - `RESULT: PASS`
   - no bit-exact duplicate group
   - `Distinct modal codes: 16/16`
   - all 16 columns stable
   - all 16 expected AFE codes recovered exactly once

The JSON report also gives the observed AFE-channel to HSDC-slot mapping. Save
that mapping in the capture manifest; do not infer it from SMA labels.

5. Restore analogue data with
   `configs/afe58jd48/ADC_ANALOG_RESTORE.cfg`. Read back digital-channel Reg29
   as zero before reconnecting TX or acquiring acoustic data.

If Gate 1 fails, preserve the BIN and JSON. Do not proceed to acoustic capture.

## 5. Gate 2 — matched Subclass 2 / K=8 fallback

Only run this after a failed, documented Gate 1.

1. Select HSDC profile
   `AFE58JD48_120M_8L_M16_S2_K8_EXPERIMENTAL.ini`.
2. Cold-reinitialize HSDC/TSW and the AFE JESD link; a warm profile selection is
   insufficient.
3. Load AFE overlay
   `AFE58JD48_120M_8L_S2_K8_EXPERIMENTAL.cfg` and verify:
   `Reg31=0x02C0`, `Reg34=0x1107`, `Reg35=0x03C0`, `Reg36=0x0007` on both dies.
4. Verify the SYNC~ link is asserted/deasserted normally and HSDC reports no
   link error.
5. Repeat the unique-code capture and `jesd_transport_qa.py` acceptance test.

Do not mix the S2 AFE overlay with the S1 HSDC INI, or vice versa.

## 6. Gate 3 — TI-installed original profile control

This control determines whether the repository's literal `M=16` field is the
sole cause.

1. Preserve the current custom profile and its SHA-256; do not overwrite it.
2. Install a copy of TI's original AFE58JD48 40x/no-demod/Subclass-1 HSDC INI
   under a new display name. The installed file on the tested workstation uses
   `JESD IP Core_M=5`.
3. Cold-reinitialize AFE/TSW/HSDC, select the TI-original profile, and repeat
   the 65,536-sample unique-code capture.
4. Run `automation/jesd_transport_qa.py` and compare both the report and the
   complete BIN SHA-256 with Gates 1 and 2.

Observed on 2026-07-25: **FAIL**. All three BINs had SHA-256
`141E592D1631CDC19D42680BE18477E1EB12A6E84627D3F3DC3B2ACF60EBCED3`
and the same four duplicate pairs. Therefore neither Subclass nor the custom
literal M=16 field is the sole root cause.

The next action is to obtain TI's corrected TSW14J50 firmware INI/firmware,
because the public E2E case below reports this exact mapping and identifies an
INI bug:

- https://e2e.ti.com/support/data-converters-group/data-converters/f/data-converters-forum/1567281/afe58jd48evm-afe58jd48-channel-mapping-issue-with-jesd204b-interface

Do not proceed to acoustic acceptance until a corrected profile passes the
unique-code gate.

## 7. Gate 4 — acoustic eight-channel independence

After a transport PASS:

1. Restore analogue mode and the validated 16-slot mapping.
2. Re-enable the previously qualified gel-phantom TX/RX setup at conservative
   voltage and fixed AFE gain. Acquire one standard angle sweep.
3. Run:

   ```powershell
   python automation/channel_qa.py "C:\path\capture_..."
   ```

4. Required hardware acceptance for the configured physical RX aperture:

   - no persistent bit-exact duplicate pair among its eight mapped HSDC slots;
   - `distinct_waveform_count` equal or close to eight;
   - no clipped/stuck channel;
   - the mapping is stable across every angle file.

The SVD effective rank of a coherent planar echo can be below eight even when
the hardware is healthy. Treat rank as supporting evidence, not the sole gate.
For a rank test, use independent analogue inputs/noise or a sequence of digital
one-channel activations. A static reflector can legitimately be low-rank.

## 8. Reconstruction only after all gates pass

Use all validated physical receive channels rather than software masking:

```powershell
python reconstruct_ultrasound.py --capture-dir "C:\path\capture_..." --duplicate-policy keep-all
```

Compare `plane_wave_das_bmode.png`, channel QA and known phantom geometry. A
sector A-line montage is not a receive-DAS image and is not an acceptance image.

## 9. Rollback

For the first-stage S1 experiment:

1. Load `AFE58JD48_120M_8L_S1_K16_ROLLBACK.cfg`.
2. Read back `Reg34=0x090F` on both dies.
3. Re-select the exact pre-test HSDC profile and cold-reinitialize the link.
4. Load `ADC_ANALOG_RESTORE.cfg` and verify Reg29=0 on all channels.

For S2, return both ends to S1; never roll back one end only.

## 10. Source evidence

- `AFE58JD48EVM User's Guide` SLOU521: 120M/8L capture procedure selects
  Subclass 1.
- `AFE58JD48` data sheet SBAS881A: JESD modes and register definitions;
  test-pattern description (PDF p181), digital channel register map (p222),
  Reg29/Reg2A fields (p228).
- TI AFE GUI installed Quick Start script
  `JESD 120MSPS_Subclass1_8L.CFG`: `Reg34=0x090F` (K=16).
- TI AFE GUI installed 40x/no-demod firmware INIs: both Subclass 1 and
  Subclass 2 variants with lane mapping `3,2,1,0,5,4,7,6`.
- TI E2E thread 1567281: the same four duplicated channel pairs; TI identifies
  a TSW14J50 firmware INI bug and directs users to ultrasound RX support.
