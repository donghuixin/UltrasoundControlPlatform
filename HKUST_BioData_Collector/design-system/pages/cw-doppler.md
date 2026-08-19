# CW Doppler page override

- Preserve the existing light, dense operations-dashboard shell and semantic color tokens.
- Keep acquisition inputs, derived feasibility metrics, geometry calibration, and hardware actions in separate cards.
- Show requested values and derived/quantized values together; never hide NCO quantization or DDR duration.
- Keep physical ADC rate read-only and visually separate it from the selectable decimated I/Q output rate.
- Limit TX choices to qualified presets and I/Q choices to 15/10/7.5/6/5 MSPS; show the AFE hardware decimator D and the equation `I/Q = 120/(2D)`.
- Treat the three row angles as the central editable table. TX/RX logical patch IDs are read-only topology labels; AFE RX slots are editable mappings.
- Place signed measured `fD` beside each row and show the DBUD speed, flow angle, fitted frequencies, and residual directly below the table.
- Hardware states must use text in addition to color: ready, research-only, blocked, or safe standby.
- The page must expose finite DDR capture, output location, progress, manifest status, and an inline I/Q plus baseband-spectrum preview.
- The page must support mouse-wheel plus PageUp/PageDown/Home/End scrolling while active.
- Provide one primary action: export configuration. Hardware staging is visually dangerous and requires explicit checkboxes plus confirmation.
- A disabled continuous-CW button must state why it is unavailable; never provide an inert unlabeled control.
- Maintain keyboard focus order: backend → acquisition → processing → row geometry → confirmations → actions.
