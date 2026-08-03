# Diagnostic evidence

This directory contains small, de-identified QA summaries that are safe to keep
with the code. Raw HSDC BIN files, capture folders, local user paths, screenshots
and large generated analysis outputs are intentionally excluded.

- `jesd_unique_code_test_summary_20260725.json`: three AFE58JD48 digital
  unique-code transport tests using matched S1/K8, matched S2/K8 and the
  TI-installed original HSDC profile.
- `ti_channel_copy_fix_packet_20260803.json`: public-safe metadata for the
  TI support packet that supplied a corrected AFE GUI CFG plus updated
  TSW14J50RX firmware INI for the channel-copy investigation. Raw vendor files
  are intentionally excluded; only sizes, hashes and validation gates are kept.
