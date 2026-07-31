---
name: afe58jd48-jesd-repair
description: Diagnose and operate TX7316EVM, AFE58JD48EVM, and TSW14J50/HSDC Pro ultrasound chains. Use for deterministic channel duplication, missing converters, HSDC mapping, trigger and Doppler planning, TX/echo frequency confusion, weak or striped B-mode images, calibration gates, or a TI support packet.
---

# AFE58JD48 JESD Repair

Use digital evidence to localize a channel-mapping failure before changing the probe, TX waveform, beamformer, or reconstruction algorithm. Treat software channel dropping as a diagnostic/degraded mode, never as a repair.

## Start here

1. Keep TX7316 high voltage off, CW off, and `TX_BF_MODE=0` for digital transport tests.
2. Preserve AFE readbacks, selected HSDC device/profile, firmware name/version, and file hashes before changing anything.
3. Read [references/known-incident.md](references/known-incident.md) when the observed pairs include `3=5`, `4=6`, `9=15`, or `10=16`.
4. Read [references/decision-gates.md](references/decision-gates.md) before proposing the next experiment.
5. Read [references/source-map.md](references/source-map.md) before using local PDFs or the JESD reference RTL. It records which sources apply to TSW14J50 and which are only architectural examples.
6. Read [references/platform-traps.md](references/platform-traps.md) when the failure is a GUI, USB, firmware-load, trigger, save, or reconstruction exception rather than a repeatable converter mapping.
7. Read [references/system-architecture-and-modes.md](references/system-architecture-and-modes.md) before changing clocks, triggers, TX patterns, or capture topology.
8. Read [references/calibration-and-imaging.md](references/calibration-and-imaging.md) for weak echoes, grating lobes, frequency selection, and B-mode calibration.
9. Read [references/doppler-and-trigger.md](references/doppler-and-trigger.md) before attempting slow-time ensembles or multi-heart-cycle recording.
10. Read [references/open-source-evidence.md](references/open-source-evidence.md) before reusing USTB, UltraSpy, ListenToJESD, echomods, murgen, or ADCoctoSPI01 concepts.

## Transport gate

Use a distinct constant code in every AFE converter, capture 65,536 or more samples per HSDC column with averaging and external trigger disabled, then run from the repository root:

```powershell
python automation/jesd_transport_qa.py "C:\path\unique_codes.bin"
```

PASS requires all of the following:

- no bit-exact duplicate group;
- 16 stable, distinct modal codes;
- every expected AFE code appears exactly once;
- a one-to-one converter-to-HSDC-slot mapping.

Do not accept correlation, SVD rank, or a visually plausible ultrasound image as a substitute for this gate. Coherent echoes can legitimately be low-rank; multi-megabyte bit-exact digital duplicates cannot be explained by acoustic crosstalk.

## Compare experiments

Compare multiple QA JSON reports without loading raw BIN data:

```powershell
python skills/afe58jd48-jesd-repair/scripts/compare_transport_qa.py `
  "C:\run_s1\jesd_transport_qa.json" `
  "C:\run_s2\jesd_transport_qa_s2.json" `
  "C:\run_ti\jesd_transport_qa_ti.json"
```

If raw source files still exist, the script also computes SHA-256. Identical complete BIN hashes across profile changes prove that the changed field did not alter the delivered HSDC columns.

## Classify the failure

- A pure permutation with all 16 unique codes points to lane/converter ordering, not data loss.
- Missing codes replaced by other valid codes point to converter lookup/deformatter/column assembly.
- Random bit errors, unstable modal fractions, or changing duplicate pairs point toward link integrity, clocks, power, or physical lanes.
- Stable duplicated pairs that survive matched Subclass 1, matched Subclass 2, and the TI-installed profile point downstream of the changed AFE fields. Obtain the matching TI HSDC INI/TSW firmware before probing the acoustic path.
- A working CGS/ILA/link status proves framing and link establishment, not necessarily correct converter-to-column unpacking.

## Protect experimental validity

- Change one variable per cold-start experiment.
- Never mix an S1 AFE overlay with an S2 HSDC profile.
- Never overwrite TI-installed profiles; install a renamed copy and hash it.
- Restore analog mode before reconnecting TX or acquiring acoustic data.
- Do not publish NDA PDFs, extracted text, proprietary RTL, or private register sequences. Commit only derived test results, hashes, public-safe procedures, and redacted support packets.
- Do not claim 8/16-channel imaging until the digital transport gate passes. `drop-later` can prevent double weighting but cannot restore missing converters.

## After transport PASS

1. Restore analog input and record the validated HSDC-slot mapping in the capture manifest.
2. Acquire a conservative gel-phantom dataset at fixed gain.
3. Run `python automation/channel_qa.py <capture_dir>`.
4. Reconstruct with `--duplicate-policy keep-all` only after the physical receive channels are independently verified.

For the complete project-specific incident and operational commands, use `docs/11_JESD_CHANNEL_DUPLICATION_INCIDENT_REPORT.md` and `docs/13_JESD_DOCUMENT_EVIDENCE_AND_DECISION_GATES.md`.
