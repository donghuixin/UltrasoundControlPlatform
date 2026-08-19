# JESD channel-repair decision gates

## Gate 0 — establish a digital baseline

- TX high voltage off; no probe or phantom required.
- Give every converter a distinct stable code.
- Capture at least 65,536 samples per column without averaging.
- Save the AFE readbacks, HSDC device name, firmware build, profile hash, BIN hash, and QA JSON.

Stop if the capture has random bit errors or cannot establish the link; solve clock/power/SYNC/firmware loading first.

## Gate 1 — classify mapping versus data loss

- All expected codes exactly once, different order: mapping/permutation problem.
- Some expected codes missing and other valid codes repeated: converter lookup/deformatter/column assembly problem.
- Duplicate pairs change across cold starts: link integrity or unsynchronized configuration problem.
- Duplicate pairs stay bit-exact across cold starts: deterministic configuration/firmware problem.

## Gate 2 — one-variable profile experiments

Test in this order and cold-start both ends each time:

1. Known matched Subclass 1 / K / lane count / converter count.
2. Matched Subclass 2 control.
3. Unmodified TI-installed profile control.
4. Vendor-corrected HSDC profile plus its matching TSW firmware.

Compare QA reports and complete BIN hashes after every row. If a changed configuration produces the identical BIN, do not continue tuning that field.

## Gate 3 — localize receiver layers

When TI support exposes the controls, separate these tests:

1. CGS/ILA/link status: proves link establishment only.
2. Per-lane link/transport pattern: tests serial lanes and JESD receiver integrity.
3. Distinct per-converter constants/ramp: tests converter identity and column assembly.
4. One-converter-at-a-time activation: identifies the exact lookup table or word-unpack substitution.

Do not publish private register sequences from selective-disclosure material. Record only the test identity and observed signature.

## Gate 4 — hardware A/B only after a corrected profile fails

Change one item at a time:

1. reseat/inspect transition and FMC connectors;
2. swap to a known-good transition/capture board;
3. compare physical JESD lanes with appropriate high-speed equipment;
4. repeat the digital unique-code gate.

A simple physical lane swap should normally preserve all converter codes as a permutation. A repeatable missing-and-duplicated converter pattern is stronger evidence for deterministic unpacking than for an ordinary lane swap.

## Acceptance

Transport repair is complete only when duplicate groups are empty, all 16 columns are stable and distinct, and all expected converter codes appear exactly once. Reconstruction quality is evaluated only after this gate.
