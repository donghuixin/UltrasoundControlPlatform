# Opus 求助包：AFE58JD48 / TSW14J50 確定性 converter 複製

> 本文件可整份貼給 Opus。請它先用現有證據推理，再提出可證偽、一次只改一項的實驗。不要讓它把問題重新歸因於探頭、聲學串擾或離線 DAS。

## Role and request

You are reviewing a deterministic JESD204B de-framing/channel-mapping failure involving an AFE58JD48EVM, a TSW14J50 capture board and HSDC Pro 5.31. Please identify the most likely failing configuration layer and propose the smallest falsifiable experiment sequence. Do not suggest acoustic, transducer or beamforming fixes: the failure is reproduced with independent constant digital codes generated inside all 16 AFE converter channels.

## Hardware/software context

- AFE: TI AFE58JD48EVM, 16 analog channels implemented as two 8-channel ADC dies.
- Capture: TSW14J50, `TSW14J50RX_FIRMWARE`, HSDC Pro 5.31.
- JESD mode under test: aggregate L=8, aggregate M=16, F=4, S=1, N=16, K=8, no demod, PLL 40x.
- HSDC raw format: 16 interleaved signed/offset-binary 16-bit output columns, 65,536 rows per test.
- Test source: each AFE digital channel emits a different constant code. Both AFE dies were read back after configuration.
- TX7316 high voltage and acoustic path were disabled.

## Reproducible symptom

Every tested profile yields this exact HSDC-slot-to-AFE-channel mapping:

```text
slot  1 -> AFE  1
slot  2 -> AFE  2
slot  3 -> AFE  5   (AFE 3 is missing)
slot  4 -> AFE  6   (AFE 4 is missing)
slot  5 -> AFE  5
slot  6 -> AFE  6
slot  7 -> AFE  7
slot  8 -> AFE  8
slot  9 -> AFE  9
slot 10 -> AFE 10
slot 11 -> AFE 11
slot 12 -> AFE 12
slot 13 -> AFE 13
slot 14 -> AFE 14
slot 15 -> AFE  9   (AFE 15 is missing)
slot 16 -> AFE 10   (AFE 16 is missing)
```

Bit-exact duplicate groups are `[3,5] [4,6] [9,15] [10,16]`. All 16 columns are perfectly stable for all 65,536 samples. There are only 12 distinct modal codes. The three complete BIN files have the same SHA-256:

```text
141E592D1631CDC19D42680BE18477E1EB12A6E84627D3F3DC3B2ACF60EBCED3
```

## Profiles already tested

1. Matched Subclass 1 / K=8:
   - AFE readback on both dies: Reg31=0x02C0, Reg34=0x0907, Reg35=0x03C0, Reg36=0x0007.
   - Custom HSDC profile: L/M/F/S/N/K = 8/16/4/1/16/8, lane map 3,2,1,0,5,4,7,6, Group128=1.
   - Result: exact failure above.
2. Matched Subclass 2 / K=8:
   - AFE readback on both dies: Reg31=0x02C0, Reg34=0x1107, Reg35=0x03C0, Reg36=0x0007.
   - HSDC profile changed to Subclass 2 at the same time.
   - Result: byte-identical failure.
3. TI-installed original 40x/no-demod/Subclass-1 HSDC profile:
   - Uses `JESD IP Core_M=5` rather than the custom literal M=16.
   - Result: byte-identical failure.

Thus a simple subclass mismatch and the custom M=16 field are not sufficient explanations.

## Important matching public evidence

TI E2E has a report with the same four substitutions:

- https://e2e.ti.com/support/data-converters-group/data-converters/f/data-converters-forum/1567281/afe58jd48evm-afe58jd48-channel-mapping-issue-with-jesd204b-interface

The TI response says one TSW14J50 firmware INI contains a bug and directs the user to `ultrasound_rx-support@list.ti.com` for an updated file.

The TSW14J50 guide explains that the ADC INI programs the FPGA JESD parameters after device selection/capture:

- https://www.ti.com/lit/ug/slau576a/slau576a.pdf

AFE product information:

- https://www.ti.com/product/AFE58JD48

## Questions to answer

1. In TSW14J50/HSDC ADC INI files, is `JESD IP Core_M=5` a private enumeration rather than literal converter count? What does value 5 select?
2. Which fields actually control the two-die converter-to-HSDC-column deinterleave: `Channel Pattern`, `Group128`, lane mapping, M, firmware build, or another hidden table?
3. Does the exact replacement pattern `(3<-5, 4<-6, 15<-9, 16<-10)` reveal a likely off-by-group, stale lookup table, or 128-bit word unpacking error?
4. Why can the JESD link capture normally with all columns stable while four converter IDs are substituted? Which JESD transport/deformatter checks would fail to catch this?
5. What exact AFE58JD48 8-lane/no-demod profile and TSW14J50RX firmware version should be used with HSDC Pro 5.31?
6. If the corrected TI profile still fails, what is the minimal one-variable test order to distinguish:
   - AFE converter transport mapping,
   - TSW FPGA deformatter/firmware,
   - INI parser/private encoding,
   - physical FMC/JESD lanes?
7. Is a lane swap expected to preserve all 16 unique converter codes as a permutation? If yes, does the missing-and-duplicated pattern largely rule out a simple physical lane swap?
8. Which diagnostic registers or ILAS fields should be captured from both AFE dies and the TSW FPGA to prove the negotiated LMFSK and converter mapping?

## Required answer format

Please return:

1. a ranked root-cause table with evidence for and against each cause;
2. a minimal experiment matrix where only one field changes per row;
3. expected PASS/FAIL signatures for each experiment;
4. exact rollback instructions after each experiment;
5. a list of files/registers/screenshots to send TI support;
6. any warning where the public documentation is insufficient and an updated TI-private INI/firmware is required.

Acceptance is strict: no bit-exact duplicate group, 16/16 distinct stable codes, and every expected AFE code recovered exactly once. Software channel dropping is not a repair.
