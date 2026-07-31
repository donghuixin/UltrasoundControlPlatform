# Known deterministic duplication incident

## Reproduced signature

The 2026-07-25 digital constant-code tests on AFE58JD48EVM + TSW14J50 + HSDC Pro 5.31 produced:

- duplicate HSDC slots: `[3,5] [4,6] [9,15] [10,16]`;
- missing AFE converters: `3,4,15,16`;
- observed slot mapping: `[1,2,5,6,5,6,7,8,9,10,11,12,13,14,9,10]`;
- 12 distinct stable codes in 16 columns;
- 65,536/65,536 identical samples inside every duplicate pair.

Matched S1/K8, matched S2/K8, and the TI-installed S1 profile produced complete BIN files with the same SHA-256:

`141E592D1631CDC19D42680BE18477E1EB12A6E84627D3F3DC3B2ACF60EBCED3`

## What this proves

- The acoustic path, probe, FPC, TX7316, T/R switch, and AFE analog chain are bypassed.
- Subclass alone is not the root cause.
- A literal custom `JESD IP Core_M=16` field is not the sole root cause.
- The signature is not a simple permutation because four expected converter codes disappear and other codes are duplicated.
- Stable output does not prove correct de-framing.

## Current leading action

Use a corrected, mutually compatible AFE58JD48 HSDC profile and TSW14J50RX firmware from TI, then rerun the same unique-code gate. If the exact signature remains after a vendor-confirmed profile/firmware pair, proceed to a board/FMC/physical-lane A/B test.

The committed redacted evidence is `diagnostics/jesd_unique_code_test_summary_20260725.json`. Raw BIN files are intentionally excluded.
