// Top-level wrapper for the HV7350 single-channel project.
//
// OEN and REN are intentionally not FPGA outputs in this minimal bring-up
// wrapper. Tie H2.31 OEN and H2.29 REN to the required enable level on the
// HV7350 board, then use these three FPGA outputs for PIN1/NIN1/CLK.
module top (
    input clk,
    input s2,
    output led_ready,
    output led_done,
    output hv_pin1,
    output hv_nin1,
    output hv_clk
);

hv7350_single_channel_example u_hv7350_single_channel_example (
    .clk(clk),
    .s2(s2),
    .led_ready(led_ready),
    .led_done(led_done),
    .hv_pin1(hv_pin1),
    .hv_nin1(hv_nin1),
    .hv_clk(hv_clk)
);

endmodule
