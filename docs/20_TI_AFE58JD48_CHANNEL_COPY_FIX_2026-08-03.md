# TI AFE58JD48 120-MSPS 8L channel-copy fix packet

Date: 2026-08-03

Scope: AFE58JD48EVM + TSW14J50/HSDC Pro channel-copy investigation where the digital unique-code test previously showed duplicated HSDC slots `[3,5] [4,6] [9,15] [10,16]` and missing expected converter codes.

## Status

TI Ultrasound Rx AFE support supplied a corrected AFE GUI configuration file and an updated firmware INI file for the TSW14J50RX path.

These files are treated as private vendor support material. The raw CFG/INI contents are intentionally not committed to this public repository. This repository records only their names, sizes, SHA-256 checksums, installation notes, and validation procedure.

## Files received from TI

| File | Bytes | SHA-256 |
|---|---:|---|
| `JESD 120MSPS_Subclass1_8L.CFG` | 4236 | `FC5A7093E21D816B7063D826759109C60BC1E31D294C7898B26808109ABAA344` |
| `AFE58JD48_Custom_PLL_MODE_40x_No Demod_SubClass1.ini` | 1668 | `78923A1787DC6794274398B5457DF1EE2F40852B0E9854DDC6AED41E9CDC8E67` |

Local private archive, outside the Git repository:

`<TI_AFE58jd48 workspace>/TI_Support_Materials/2026-08-03_afe58jd48_s1_8l_channel_copy_fix/`

## Local install-path note

TI's email references the default installation path:

`C:\Program Files (x86)\Texas Instruments\AFE58JD48 EVM\Config Files\AFE58JD48\AFE58JD48vA\Firmware INI Files\TSW14J50_TSW14J50RX_FIRMWARE\`

On the current workstation, the matching AFE58JD48 EVM software installation was found under:

`E:\Program Files (x86)\Texas Instruments\AFE58JD48 EVM\Config Files\AFE58JD48\AFE58JD48vA\Firmware INI Files\TSW14J50_TSW14J50RX_FIRMWARE\`

Before replacement, the installed INI was backed up locally with SHA-256:

`72C1F4B59E9A1E057A4B001D723B6C04DFAAB981DD6AED73F43A34CAEF332C7E`

## Recommended installation and validation sequence

1. Close AFE58JD48 GUI, HSDC Pro, and all automation scripts.
2. Keep TX7316 high voltage off and CW off. This is a digital transport test, not an acoustic test.
3. Back up the currently installed firmware INI before replacing it.
4. Replace the installed `AFE58JD48_Custom_PLL_MODE_40x_No Demod_SubClass1.ini` with TI's updated INI in the actual `TSW14J50_TSW14J50RX_FIRMWARE` directory.
5. Start the AFE58JD48 GUI as administrator.
6. Use the top `Open Configuration` button to load TI's `JESD 120MSPS_Subclass1_8L.CFG`.
7. Initialize LMK and AFE.
8. Start HSDC Pro and record the selected board name, firmware type, firmware version, and ADC/device string before capture.
9. Run the AFE digital unique-code transport gate using at least 65,536 samples per HSDC column.
10. Analyze the saved BIN using:

```powershell
python automation/jesd_transport_qa.py "C:\path\to\unique_code_capture.bin"
```

## Acceptance criteria

The TI update is accepted only if all of the following are true:

- no bit-exact duplicate column groups;
- 16 stable, distinct modal codes;
- every expected AFE converter code appears exactly once;
- the final result is a one-to-one converter-to-HSDC-slot mapping.

Do not use B-mode image quality, channel correlation, or a plausible acoustic echo as a substitute for this digital transport gate.

## If the gate still fails

Return to TI with:

- the redacted `jesd_transport_qa.json`;
- the raw BIN SHA-256, not the raw BIN unless explicitly requested;
- selected HSDC device/profile string;
- TSW14J50 board name, firmware type, and firmware version;
- observed duplicate groups and missing converter codes;
- whether the same signature survives a cold restart.

## Draft thank-you reply

Subject: Re: TSW14J50 / AFE58JD48 120-MSPS 8L configuration

Hi Sheetal,

Thank you for sending the updated AFE configuration and firmware INI files.

I have archived the received files with checksums and will back up the existing installed INI before replacing it in the `TSW14J50_TSW14J50RX_FIRMWARE` directory. I will then load the updated CFG through the AFE58JD48 GUI and rerun the 16-channel unique-code transport test to confirm whether the previous duplicate-channel pattern is resolved.

This is very helpful for isolating the TSW14J50/AFE58JD48 channel-copy issue. I will let you know the test result, or share the remaining mismatch details if the issue persists.

Thanks & regards,  
Huixin
