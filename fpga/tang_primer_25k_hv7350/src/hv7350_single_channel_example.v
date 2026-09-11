// HV7350 single-channel bring-up example for Tang Primer 25K.
//
// This file is intentionally not added to pmod_led.gprj. Use it as a starting
// point after assigning these ports to the FPGA pins that are wired to H2 on
// the HV7350 board.
//
// Output pattern:
// - hv_pin1/hv_nin1 generate a bipolar 5 MHz burst.
// - Each burst lasts 1 us and repeats every 50 us while S2 is held.
// - hv_pin1 and hv_nin1 are never asserted at the same time.
//
// Important:
// - These outputs are 3.3 V logic signals for HV7350 H2 only.
// - Do not connect FPGA pins to H1 high-voltage outputs.
// - Confirm HV7350 CLK/OEN/REN polarity and timing in the datasheet before
//   enabling high-voltage supplies.
module hv7350_single_channel_example #(
    parameter CLK_FREQ_HZ = 50_000_000,
    parameter HALF_5M_TICKS = CLK_FREQ_HZ / 5_000_000 / 2,
    parameter BURST_PERIOD_TICKS = CLK_FREQ_HZ / 20_000,
    parameter BURST_ACTIVE_TICKS = CLK_FREQ_HZ / 1_000_000
) (
    input clk,
    input s2,
    output reg led_ready = 1'b0,
    output reg led_done = 1'b0,

    output reg hv_pin1 = 1'b0,
    output reg hv_nin1 = 1'b0,
    output reg hv_clk = 1'b0
);

reg s2_meta = 1'b0;
reg s2_sync = 1'b0;
reg s2_last = 1'b0;

reg [31:0] burst_period_count = 32'd0;
reg [31:0] half_count = 32'd0;
reg phase_negative = 1'b0;
reg clk_strobe_pending = 1'b0;

always @(posedge clk) begin
    s2_meta <= s2;
    s2_sync <= s2_meta;
    s2_last <= s2_sync;

    // A simple status indication: DONE follows the armed state.
    led_done <= s2_sync;
    led_ready <= s2_sync;

    // Pulse CLK one system-clock cycle after each PIN/NIN update. This gives
    // the external control inputs one clk period of setup time if CLK is used
    // as a latch clock by the HV7350.
    hv_clk <= clk_strobe_pending;
    clk_strobe_pending <= 1'b0;

    if (s2_sync) begin
        if (!s2_last || burst_period_count >= BURST_PERIOD_TICKS - 1) begin
            burst_period_count <= 32'd0;
            half_count <= 32'd0;
            phase_negative <= 1'b0;
            hv_pin1 <= 1'b1;
            hv_nin1 <= 1'b0;
            clk_strobe_pending <= 1'b1;
        end
        else begin
            burst_period_count <= burst_period_count + 1'b1;

            if (burst_period_count < BURST_ACTIVE_TICKS) begin
                if (half_count >= HALF_5M_TICKS - 1) begin
                    half_count <= 32'd0;
                    phase_negative <= ~phase_negative;
                    hv_pin1 <= phase_negative;
                    hv_nin1 <= ~phase_negative;
                    clk_strobe_pending <= 1'b1;
                end
                else begin
                    half_count <= half_count + 1'b1;
                end
            end
            else begin
                half_count <= 32'd0;
                phase_negative <= 1'b0;
                hv_pin1 <= 1'b0;
                hv_nin1 <= 1'b0;
            end
        end
    end
    else begin
        burst_period_count <= 32'd0;
        half_count <= 32'd0;
        phase_negative <= 1'b0;
        clk_strobe_pending <= 1'b0;
        hv_pin1 <= 1'b0;
        hv_nin1 <= 1'b0;
        hv_clk <= 1'b0;
    end
end

endmodule
