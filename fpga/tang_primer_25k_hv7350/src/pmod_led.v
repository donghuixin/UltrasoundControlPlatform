// Eight-channel HV7350 transmit beamformer for Tang Primer 25K.
//
// Control:
// - Transmission starts automatically after FPGA configuration; READY and DONE
//   are steady high while output is enabled. No button press is required.
// - S1 is reserved and has no effect in this final fixed-damping build.
// - S2 remains an optional emergency stop/restart control after a 20 ms
//   debounce. Restart always uses the fixed 0-degree beam and 140 ns damping
//   delay; disabling forces every synchronization and pulser output low.
// - J11 is a short 200 ns, 10 kHz trigger. J10 and the transmit burst start
//   exactly 2 us after the J11 rising edge.
// - READY and DONE indicate that the automatic transmitter is running.
// - The measured carrier and cycle count are fixed in this final build. UART
//   packets may update stored steering profiles but cannot change carrier or
//   cycle count.
//
// Each HV7350 channel first emits a positive-unipolar RTZ burst on PINx. After
// a fixed 140 ns damping delay, NINx emits one 100 ns negative damping pulse.
// PINx and NINx are never high together. With OEN high, PINx=NINx=0 selects the
// HV7350 return-to-ground path. All logic outputs are low while S2 is disabled.
module top #(
    parameter integer CLK_FREQ_HZ = 50_000_000,
    parameter integer UART_BAUD = 115_200,
    parameter integer S2_DEBOUNCE_TICKS = CLK_FREQ_HZ / 50,
    parameter integer PRF_PERIOD_TICKS = CLK_FREQ_HZ / 10_000,
    parameter integer PRF_HALF_TICKS = PRF_PERIOD_TICKS / 2,
    parameter integer PRETRIGGER_TICKS = CLK_FREQ_HZ / 500_000,
    parameter integer TRIGGER_PULSE_TICKS = CLK_FREQ_HZ / 5_000_000,
    parameter integer DAMP_PULSE_TICKS = CLK_FREQ_HZ / 10_000_000,
    // round(2.2 MHz * 2^32 / 50 MHz) = 0x0B439581.
    parameter [31:0] DEFAULT_FREQ_WORD = 32'h0B439581,
    parameter [7:0] DEFAULT_BURST_CYCLES = 8'd2
)(
    input  wire clk,
    input  wire s2,
    input  wire uart_rx_b3,
    output wire uart_tx_c3,

    output wire led_ready,
    output wire led_done,
    output wire sync_prf_j11,
    output wire sync_prf_j10,

    output wire tx1_pin_b2,
    output wire tx1_nin_f2,
    output wire tx2_pin_e1,
    output wire tx2_nin_e3,
    output wire tx3_pin_j1,
    output wire tx3_nin_g4,
    output wire tx4_pin_h1,
    output wire tx4_nin_k7,
    output wire tx5_pin_l7,
    output wire tx5_nin_l10,
    output wire tx6_pin_l9,
    output wire tx6_nin_j8,
    output wire tx7_pin_f7,
    output wire tx7_nin_k8,
    output wire tx8_pin_l8,
    output wire tx8_nin_k10,

    // The transmit pins share the dock-board SDRAM bus. Hold CS_N high so the
    // SDRAM never drives its DQ pins while they are used by this design.
    output wire sdram_disable_n_k9
);

localparam integer UART_CLKS_PER_BIT = CLK_FREQ_HZ / UART_BAUD;
localparam [3:0] CALIBRATION_ANGLE_INDEX = 4'd5;
localparam [15:0] FIXED_DAMP_DELAY_TICKS = 16'd7;

assign uart_tx_c3 = 1'b1;
assign sdram_disable_n_k9 = 1'b1;

// The board S1 input is disconnected from this final top level. Synchronize
// and debounce only the optional S2 emergency stop/restart input.
reg s2_meta = 1'b0;
reg s2_sync = 1'b0;
reg s2_state = 1'b0;
reg s2_state_last = 1'b0;
reg [31:0] s2_debounce_count = 32'd0;

wire s2_pressed = s2_state && !s2_state_last;

always @(posedge clk) begin
    s2_meta <= s2;
    s2_sync <= s2_meta;
    s2_state_last <= s2_state;

    if (s2_sync == s2_state) begin
        s2_debounce_count <= 32'd0;
    end
    else if (s2_debounce_count >= S2_DEBOUNCE_TICKS - 1) begin
        s2_state <= s2_sync;
        s2_debounce_count <= 32'd0;
    end
    else begin
        s2_debounce_count <= s2_debounce_count + 1'b1;
    end
end

// Start automatically with a visible J11 trigger, then begin the first frame
// exactly PRETRIGGER_TICKS (2 us) later. Steering is fixed at 0 degrees and the
// measured optimum damping-tail delay is fixed at seven clocks (140 ns).
reg output_enabled = 1'b1;
reg scan_active = 1'b1;
reg pretrigger_active = 1'b1;
reg [15:0] pretrigger_count = 16'd0;
reg [15:0] frame_count = 16'd0;
reg [3:0] scan_angle_index = CALIBRATION_ANGLE_INDEX;
reg [3:0] active_frame_angle_index = CALIBRATION_ANGLE_INDEX;

wire pretrigger_complete = scan_active && pretrigger_active &&
                           (pretrigger_count == PRETRIGGER_TICKS - 1);
wire prf_interval_complete = scan_active && !pretrigger_active &&
                             (frame_count == PRF_PERIOD_TICKS - 1);
wire scan_frame_start = pretrigger_complete || prf_interval_complete;
wire initial_trigger_pulse = pretrigger_active &&
                             (pretrigger_count < TRIGGER_PULSE_TICKS);
wire frame_trigger_pulse = scan_active && !pretrigger_active &&
                           (frame_count >=
                            PRF_PERIOD_TICKS - PRETRIGGER_TICKS) &&
                           (frame_count <
                            PRF_PERIOD_TICKS - PRETRIGGER_TICKS +
                            TRIGGER_PULSE_TICKS);
// This edge is one clock before frame_trigger_pulse becomes visible at J11.
wire frame_trigger_start = scan_active && !pretrigger_active &&
                           (frame_count ==
                            PRF_PERIOD_TICKS - PRETRIGGER_TICKS - 1);
wire frame_start = scan_frame_start;
wire channel_run_enable = output_enabled;

always @(posedge clk) begin
    if (s2_pressed) begin
        output_enabled <= !output_enabled;

        // An optional S2 restart selects the fixed 0-degree beam and starts
        // with a short J11 pulse plus a complete 2 us trigger-to-transmit
        // delay. When READY
        // turns off, the output masks below force J11/J10/PIN/NIN low
        // immediately.
        scan_active <= !output_enabled;
        pretrigger_active <= !output_enabled;
        pretrigger_count <= 16'd0;
        frame_count <= 16'd0;
        scan_angle_index <= CALIBRATION_ANGLE_INDEX;
        active_frame_angle_index <= CALIBRATION_ANGLE_INDEX;
    end
    else if (!output_enabled) begin
        scan_active <= 1'b0;
        pretrigger_active <= 1'b0;
        pretrigger_count <= 16'd0;
        frame_count <= 16'd0;
    end
    else if (scan_active) begin
        if (frame_trigger_start) begin
            active_frame_angle_index <= CALIBRATION_ANGLE_INDEX;
        end

        if (pretrigger_active) begin
            if (pretrigger_complete) begin
                pretrigger_active <= 1'b0;
                pretrigger_count <= 16'd0;
                frame_count <= 16'd0;
            end
            else begin
                pretrigger_count <= pretrigger_count + 1'b1;
            end
        end
        else if (prf_interval_complete) begin
            frame_count <= 16'd0;
        end
        else begin
            frame_count <= frame_count + 1'b1;
        end

    end
    else begin
        // Defensive recovery: READY can only be on in transmit mode. If state
        // is ever lost, restart it with a new, visible J11 pretrigger.
        scan_active <= 1'b1;
        pretrigger_active <= 1'b1;
        pretrigger_count <= 16'd0;
        frame_count <= 16'd0;
        scan_angle_index <= CALIBRATION_ANGLE_INDEX;
        active_frame_angle_index <= CALIBRATION_ANGLE_INDEX;
    end
end

assign led_ready = output_enabled;
assign led_done = output_enabled;
assign sync_prf_j11 = output_enabled && scan_active &&
                      (initial_trigger_pulse || frame_trigger_pulse);
assign sync_prf_j10 = output_enabled && scan_active &&
                      !pretrigger_active &&
                      (frame_count < PRF_HALF_TICKS);

// UART receiver and binary configuration parser.
wire [7:0] uart_rx_data;
wire uart_rx_valid;

uart_rx_8n1 #(
    .CLKS_PER_BIT(UART_CLKS_PER_BIT)
) uart_receiver (
    .clk(clk),
    .rx(uart_rx_b3),
    .data(uart_rx_data),
    .valid(uart_rx_valid)
);

wire config_valid;
wire angle_table_valid;
wire [3:0] angle_table_index;
wire [31:0] config_freq_word;
wire [7:0] config_burst_cycles;
wire [15:0] config_delay0;
wire [15:0] config_delay1;
wire [15:0] config_delay2;
wire [15:0] config_delay3;
wire [15:0] config_delay4;
wire [15:0] config_delay5;
wire [15:0] config_delay6;
wire [15:0] config_delay7;

beam_config_parser #(
    .MAX_DELAY_TICKS(PRF_PERIOD_TICKS - 1)
) config_parser (
    .clk(clk),
    .rx_data(uart_rx_data),
    .rx_valid(uart_rx_valid),
    .config_valid(config_valid),
    .angle_table_valid(angle_table_valid),
    .angle_table_index(angle_table_index),
    .freq_word(config_freq_word),
    .burst_cycles(config_burst_cycles),
    .delay0(config_delay0),
    .delay1(config_delay1),
    .delay2(config_delay2),
    .delay3(config_delay3),
    .delay4(config_delay4),
    .delay5(config_delay5),
    .delay6(config_delay6),
    .delay7(config_delay7)
);

// Scan steering table. Index 0..10 represents
// -10, -8, -6, -4, -2, 0, +2, +4, +6, +8, +10 degrees.
// The table assumes 1.00 mm element pitch and 1540 m/s propagation speed.
// Values are true-time delays in 50 MHz clock ticks (20 ns per tick), so they
// are independent of carrier frequency. They have been recalculated/verified
// for all 11 scan angles; the 2.2 MHz carrier changes phase per tick, not the
// propagation delay needed for a given steering angle.

function [15:0] positive_angle_delay;
    input [3:0] magnitude_index;
    input [2:0] channel_index;
    begin
        positive_angle_delay = 16'd0;

        case (magnitude_index)
            // +2 degrees:  [0, 1, 2, 3, 5, 6, 7, 8]
            4'd1: begin
                case (channel_index)
                    3'd0: positive_angle_delay = 16'd0;
                    3'd1: positive_angle_delay = 16'd1;
                    3'd2: positive_angle_delay = 16'd2;
                    3'd3: positive_angle_delay = 16'd3;
                    3'd4: positive_angle_delay = 16'd5;
                    3'd5: positive_angle_delay = 16'd6;
                    3'd6: positive_angle_delay = 16'd7;
                    default: positive_angle_delay = 16'd8;
                endcase
            end

            // +4 degrees:  [0, 2, 5, 7, 9, 11, 14, 16]
            4'd2: begin
                case (channel_index)
                    3'd0: positive_angle_delay = 16'd0;
                    3'd1: positive_angle_delay = 16'd2;
                    3'd2: positive_angle_delay = 16'd5;
                    3'd3: positive_angle_delay = 16'd7;
                    3'd4: positive_angle_delay = 16'd9;
                    3'd5: positive_angle_delay = 16'd11;
                    3'd6: positive_angle_delay = 16'd14;
                    default: positive_angle_delay = 16'd16;
                endcase
            end

            // +6 degrees:  [0, 3, 7, 10, 14, 17, 20, 24]
            4'd3: begin
                case (channel_index)
                    3'd0: positive_angle_delay = 16'd0;
                    3'd1: positive_angle_delay = 16'd3;
                    3'd2: positive_angle_delay = 16'd7;
                    3'd3: positive_angle_delay = 16'd10;
                    3'd4: positive_angle_delay = 16'd14;
                    3'd5: positive_angle_delay = 16'd17;
                    3'd6: positive_angle_delay = 16'd20;
                    default: positive_angle_delay = 16'd24;
                endcase
            end

            // +8 degrees:  [0, 5, 9, 14, 18, 23, 27, 32]
            4'd4: begin
                case (channel_index)
                    3'd0: positive_angle_delay = 16'd0;
                    3'd1: positive_angle_delay = 16'd5;
                    3'd2: positive_angle_delay = 16'd9;
                    3'd3: positive_angle_delay = 16'd14;
                    3'd4: positive_angle_delay = 16'd18;
                    3'd5: positive_angle_delay = 16'd23;
                    3'd6: positive_angle_delay = 16'd27;
                    default: positive_angle_delay = 16'd32;
                endcase
            end

            // +10 degrees: [0, 6, 11, 17, 23, 28, 34, 39]
            4'd5: begin
                case (channel_index)
                    3'd0: positive_angle_delay = 16'd0;
                    3'd1: positive_angle_delay = 16'd6;
                    3'd2: positive_angle_delay = 16'd11;
                    3'd3: positive_angle_delay = 16'd17;
                    3'd4: positive_angle_delay = 16'd23;
                    3'd5: positive_angle_delay = 16'd28;
                    3'd6: positive_angle_delay = 16'd34;
                    default: positive_angle_delay = 16'd39;
                endcase
            end

            // 0 degrees.
            default: positive_angle_delay = 16'd0;
        endcase
    end
endfunction

function [15:0] scan_angle_delay;
    input [3:0] angle_index;
    input [2:0] channel_index;
    reg [3:0] magnitude_index;
    reg [2:0] table_channel;
    begin
        if (angle_index >= 4'd5) begin
            magnitude_index = angle_index - 4'd5;
            table_channel = channel_index;
        end
        else begin
            magnitude_index = 4'd5 - angle_index;
            table_channel = 3'd7 - channel_index;
        end

        scan_angle_delay = positive_angle_delay(magnitude_index, table_channel);
    end
endfunction

// UART command 0x02 can replace these 11 profiles at run time. Eight separate
// memories keep each channel to one write port and one asynchronous read port.
reg [15:0] angle_table_ch0 [0:10];
reg [15:0] angle_table_ch1 [0:10];
reg [15:0] angle_table_ch2 [0:10];
reg [15:0] angle_table_ch3 [0:10];
reg [15:0] angle_table_ch4 [0:10];
reg [15:0] angle_table_ch5 [0:10];
reg [15:0] angle_table_ch6 [0:10];
reg [15:0] angle_table_ch7 [0:10];
integer angle_init_index;

initial begin
    for (angle_init_index = 0; angle_init_index < 11;
         angle_init_index = angle_init_index + 1) begin
        angle_table_ch0[angle_init_index] = scan_angle_delay(angle_init_index, 3'd0);
        angle_table_ch1[angle_init_index] = scan_angle_delay(angle_init_index, 3'd1);
        angle_table_ch2[angle_init_index] = scan_angle_delay(angle_init_index, 3'd2);
        angle_table_ch3[angle_init_index] = scan_angle_delay(angle_init_index, 3'd3);
        angle_table_ch4[angle_init_index] = scan_angle_delay(angle_init_index, 3'd4);
        angle_table_ch5[angle_init_index] = scan_angle_delay(angle_init_index, 3'd5);
        angle_table_ch6[angle_init_index] = scan_angle_delay(angle_init_index, 3'd6);
        angle_table_ch7[angle_init_index] = scan_angle_delay(angle_init_index, 3'd7);
    end
end

always @(posedge clk) begin
    if (angle_table_valid) begin
        angle_table_ch0[angle_table_index] <= config_delay0;
        angle_table_ch1[angle_table_index] <= config_delay1;
        angle_table_ch2[angle_table_index] <= config_delay2;
        angle_table_ch3[angle_table_index] <= config_delay3;
        angle_table_ch4[angle_table_index] <= config_delay4;
        angle_table_ch5[angle_table_index] <= config_delay5;
        angle_table_ch6[angle_table_index] <= config_delay6;
        angle_table_ch7[angle_table_index] <= config_delay7;
    end
end

// Frequency and cycle count are intentionally locked to the measured optimum.
// UART configuration cannot override these two values in the final build.
wire [31:0] frame_freq_word = DEFAULT_FREQ_WORD;
wire [7:0] frame_burst_cycles = DEFAULT_BURST_CYCLES;
wire [3:0] frame_angle_index = active_frame_angle_index;
wire [15:0] frame_delay0 = angle_table_ch0[frame_angle_index];
wire [15:0] frame_delay1 = angle_table_ch1[frame_angle_index];
wire [15:0] frame_delay2 = angle_table_ch2[frame_angle_index];
wire [15:0] frame_delay3 = angle_table_ch3[frame_angle_index];
wire [15:0] frame_delay4 = angle_table_ch4[frame_angle_index];
wire [15:0] frame_delay5 = angle_table_ch5[frame_angle_index];
wire [15:0] frame_delay6 = angle_table_ch6[frame_angle_index];
wire [15:0] frame_delay7 = angle_table_ch7[frame_angle_index];
// The final measured optimum is seven 50 MHz clocks = 140 ns. It is applied to
// every channel and every frame; S1 cannot alter it.
wire [15:0] frame_damp_delay_ticks = FIXED_DAMP_DELAY_TICKS;

wire ch1_pin;
wire ch1_nin;
wire ch2_pin;
wire ch2_nin;
wire ch3_pin;
wire ch3_nin;
wire ch4_pin;
wire ch4_nin;
wire ch5_pin;
wire ch5_nin;
wire ch6_pin;
wire ch6_nin;
wire ch7_pin;
wire ch7_nin;
wire ch8_pin;
wire ch8_nin;

hv7350_tx_channel #(.DAMP_PULSE_TICKS(DAMP_PULSE_TICKS)) channel1 (
    .clk(clk), .run_enable(channel_run_enable), .frame_start(frame_start),
    .freq_word(frame_freq_word), .burst_cycles(frame_burst_cycles),
    .start_delay_ticks(frame_delay0),
    .damp_delay_ticks(frame_damp_delay_ticks),
    .pin_out(ch1_pin), .nin_out(ch1_nin)
);

hv7350_tx_channel #(.DAMP_PULSE_TICKS(DAMP_PULSE_TICKS)) channel2 (
    .clk(clk), .run_enable(channel_run_enable), .frame_start(frame_start),
    .freq_word(frame_freq_word), .burst_cycles(frame_burst_cycles),
    .start_delay_ticks(frame_delay1),
    .damp_delay_ticks(frame_damp_delay_ticks),
    .pin_out(ch2_pin), .nin_out(ch2_nin)
);

hv7350_tx_channel #(.DAMP_PULSE_TICKS(DAMP_PULSE_TICKS)) channel3 (
    .clk(clk), .run_enable(channel_run_enable), .frame_start(frame_start),
    .freq_word(frame_freq_word), .burst_cycles(frame_burst_cycles),
    .start_delay_ticks(frame_delay2),
    .damp_delay_ticks(frame_damp_delay_ticks),
    .pin_out(ch3_pin), .nin_out(ch3_nin)
);

hv7350_tx_channel #(.DAMP_PULSE_TICKS(DAMP_PULSE_TICKS)) channel4 (
    .clk(clk), .run_enable(channel_run_enable), .frame_start(frame_start),
    .freq_word(frame_freq_word), .burst_cycles(frame_burst_cycles),
    .start_delay_ticks(frame_delay3),
    .damp_delay_ticks(frame_damp_delay_ticks),
    .pin_out(ch4_pin), .nin_out(ch4_nin)
);

hv7350_tx_channel #(.DAMP_PULSE_TICKS(DAMP_PULSE_TICKS)) channel5 (
    .clk(clk), .run_enable(channel_run_enable), .frame_start(frame_start),
    .freq_word(frame_freq_word), .burst_cycles(frame_burst_cycles),
    .start_delay_ticks(frame_delay4),
    .damp_delay_ticks(frame_damp_delay_ticks),
    .pin_out(ch5_pin), .nin_out(ch5_nin)
);

hv7350_tx_channel #(.DAMP_PULSE_TICKS(DAMP_PULSE_TICKS)) channel6 (
    .clk(clk), .run_enable(channel_run_enable), .frame_start(frame_start),
    .freq_word(frame_freq_word), .burst_cycles(frame_burst_cycles),
    .start_delay_ticks(frame_delay5),
    .damp_delay_ticks(frame_damp_delay_ticks),
    .pin_out(ch6_pin), .nin_out(ch6_nin)
);

hv7350_tx_channel #(.DAMP_PULSE_TICKS(DAMP_PULSE_TICKS)) channel7 (
    .clk(clk), .run_enable(channel_run_enable), .frame_start(frame_start),
    .freq_word(frame_freq_word), .burst_cycles(frame_burst_cycles),
    .start_delay_ticks(frame_delay6),
    .damp_delay_ticks(frame_damp_delay_ticks),
    .pin_out(ch7_pin), .nin_out(ch7_nin)
);

hv7350_tx_channel #(.DAMP_PULSE_TICKS(DAMP_PULSE_TICKS)) channel8 (
    .clk(clk), .run_enable(channel_run_enable), .frame_start(frame_start),
    .freq_word(frame_freq_word), .burst_cycles(frame_burst_cycles),
    .start_delay_ticks(frame_delay7),
    .damp_delay_ticks(frame_damp_delay_ticks),
    .pin_out(ch8_pin), .nin_out(ch8_nin)
);

// Mask both pulser inputs immediately when S2 disables output. Each channel
// guarantees mutually exclusive PIN/NIN drive: PIN carries the positive main
// burst and NIN carries only the short negative damping tail.
assign tx1_pin_b2 = output_enabled && ch1_pin;
assign tx1_nin_f2 = output_enabled && ch1_nin;
assign tx2_pin_e1 = output_enabled && ch2_pin;
assign tx2_nin_e3 = output_enabled && ch2_nin;
assign tx3_pin_j1 = output_enabled && ch3_pin;
assign tx3_nin_g4 = output_enabled && ch3_nin;
assign tx4_pin_h1 = output_enabled && ch4_pin;
assign tx4_nin_k7 = output_enabled && ch4_nin;
assign tx5_pin_l7 = output_enabled && ch5_pin;
assign tx5_nin_l10 = output_enabled && ch5_nin;
assign tx6_pin_l9 = output_enabled && ch6_pin;
assign tx6_nin_j8 = output_enabled && ch6_nin;
assign tx7_pin_f7 = output_enabled && ch7_pin;
assign tx7_nin_k8 = output_enabled && ch7_nin;
assign tx8_pin_l8 = output_enabled && ch8_pin;
assign tx8_nin_k10 = output_enabled && ch8_nin;

endmodule


// One coherent, delayed positive RTZ burst followed by one negative damping
// pulse. The 32-bit phase accumulator gives an average carrier frequency of
// freq_word * 50 MHz / 2^32. At
// frequencies not divisible by the 50 MHz system clock, individual edges have
// one-clock (20 ns) quantization while long-term frequency remains accurate.
module hv7350_tx_channel #(
    parameter integer DAMP_PULSE_TICKS = 5
) (
    input  wire clk,
    input  wire run_enable,
    input  wire frame_start,
    input  wire [31:0] freq_word,
    input  wire [7:0] burst_cycles,
    input  wire [15:0] start_delay_ticks,
    input  wire [15:0] damp_delay_ticks,
    output wire pin_out,
    output wire nin_out
);

reg waiting = 1'b0;
reg active = 1'b0;
reg damp_waiting = 1'b0;
reg damp_active = 1'b0;
reg [15:0] delay_count = 16'd0;
reg [15:0] damp_count = 16'd0;
reg [31:0] phase_accumulator = 32'd0;
reg [7:0] completed_cycles = 8'd0;

wire [32:0] phase_sum = {1'b0, phase_accumulator} + {1'b0, freq_word};

assign pin_out = active && !phase_accumulator[31];
// NIN is active only after PIN has completed the positive burst. All other
// intervals use PIN=NIN=0 so the HV7350 actively returns TX to RGND.
assign nin_out = damp_active;

always @(posedge clk) begin
    if (!run_enable) begin
        waiting <= 1'b0;
        active <= 1'b0;
        damp_waiting <= 1'b0;
        damp_active <= 1'b0;
        delay_count <= 16'd0;
        damp_count <= 16'd0;
        phase_accumulator <= 32'd0;
        completed_cycles <= 8'd0;
    end
    else if (frame_start) begin
        delay_count <= 16'd0;
        damp_count <= 16'd0;
        phase_accumulator <= 32'd0;
        completed_cycles <= 8'd0;
        damp_waiting <= 1'b0;
        damp_active <= 1'b0;

        if (start_delay_ticks == 16'd0) begin
            waiting <= 1'b0;
            active <= 1'b1;
        end
        else begin
            waiting <= 1'b1;
            active <= 1'b0;
        end
    end
    else if (waiting) begin
        if (delay_count >= start_delay_ticks - 1'b1) begin
            waiting <= 1'b0;
            active <= 1'b1;
            delay_count <= 16'd0;
            phase_accumulator <= 32'd0;
            completed_cycles <= 8'd0;
        end
        else begin
            delay_count <= delay_count + 1'b1;
        end
    end
    else if (active) begin
        phase_accumulator <= phase_sum[31:0];

        if (phase_sum[32]) begin
            if (completed_cycles >= burst_cycles - 1'b1) begin
                active <= 1'b0;
                phase_accumulator <= 32'd0;
                completed_cycles <= 8'd0;

                damp_count <= 16'd0;
                if (damp_delay_ticks == 16'd0) begin
                    damp_waiting <= 1'b0;
                    damp_active <= 1'b1;
                end
                else begin
                    damp_waiting <= 1'b1;
                    damp_active <= 1'b0;
                end
            end
            else begin
                completed_cycles <= completed_cycles + 1'b1;
            end
        end
    end
    else if (damp_waiting) begin
        if (damp_count >= damp_delay_ticks - 1'b1) begin
            damp_waiting <= 1'b0;
            damp_active <= 1'b1;
            damp_count <= 16'd0;
        end
        else begin
            damp_count <= damp_count + 1'b1;
        end
    end
    else if (damp_active) begin
        if (damp_count >= DAMP_PULSE_TICKS - 1) begin
            damp_active <= 1'b0;
            damp_count <= 16'd0;
        end
        else begin
            damp_count <= damp_count + 1'b1;
        end
    end
end

endmodule


// 8-N-1 UART receiver. CLKS_PER_BIT=434 at 50 MHz/115200 baud.
module uart_rx_8n1 #(
    parameter integer CLKS_PER_BIT = 434
)(
    input  wire clk,
    input  wire rx,
    output reg [7:0] data,
    output reg valid
);

localparam [1:0] UART_IDLE  = 2'd0;
localparam [1:0] UART_START = 2'd1;
localparam [1:0] UART_DATA  = 2'd2;
localparam [1:0] UART_STOP  = 2'd3;

reg rx_meta = 1'b1;
reg rx_sync = 1'b1;
reg [1:0] state = UART_IDLE;
reg [15:0] clock_count = 16'd0;
reg [2:0] bit_index = 3'd0;
reg [7:0] shift_register = 8'd0;

initial begin
    data = 8'd0;
    valid = 1'b0;
end

always @(posedge clk) begin
    rx_meta <= rx;
    rx_sync <= rx_meta;
    valid <= 1'b0;

    case (state)
        UART_IDLE: begin
            clock_count <= 16'd0;
            bit_index <= 3'd0;
            if (!rx_sync) begin
                state <= UART_START;
                clock_count <= (CLKS_PER_BIT / 2) - 1;
            end
        end

        UART_START: begin
            if (clock_count == 16'd0) begin
                if (!rx_sync) begin
                    state <= UART_DATA;
                    clock_count <= CLKS_PER_BIT - 1;
                end
                else begin
                    state <= UART_IDLE;
                end
            end
            else begin
                clock_count <= clock_count - 1'b1;
            end
        end

        UART_DATA: begin
            if (clock_count == 16'd0) begin
                shift_register[bit_index] <= rx_sync;
                clock_count <= CLKS_PER_BIT - 1;

                if (bit_index == 3'd7) begin
                    bit_index <= 3'd0;
                    state <= UART_STOP;
                end
                else begin
                    bit_index <= bit_index + 1'b1;
                end
            end
            else begin
                clock_count <= clock_count - 1'b1;
            end
        end

        UART_STOP: begin
            if (clock_count == 16'd0) begin
                if (rx_sync) begin
                    data <= shift_register;
                    valid <= 1'b1;
                end
                state <= UART_IDLE;
            end
            else begin
                clock_count <= clock_count - 1'b1;
            end
        end

        default: state <= UART_IDLE;
    endcase
end

endmodule


// Packet format, all multibyte values little-endian:
//   A5 5A CMD WORD[31:0] VALUE D0[15:0] ... D7[15:0] CHECKSUM
// CMD=01: WORD is frequency tuning word and VALUE is burst cycles.
// CMD=02: WORD is reserved and VALUE is scan angle-table index 0..10.
// CHECKSUM is XOR(command through the final delay byte). Invalid packets do
// not alter the active configuration.
module beam_config_parser #(
    parameter integer MAX_DELAY_TICKS = 2499
)(
    input  wire clk,
    input  wire [7:0] rx_data,
    input  wire rx_valid,
    output reg config_valid,
    output reg angle_table_valid,
    output reg [3:0] angle_table_index,
    output reg [31:0] freq_word,
    output reg [7:0] burst_cycles,
    output reg [15:0] delay0,
    output reg [15:0] delay1,
    output reg [15:0] delay2,
    output reg [15:0] delay3,
    output reg [15:0] delay4,
    output reg [15:0] delay5,
    output reg [15:0] delay6,
    output reg [15:0] delay7
);

localparam [1:0] WAIT_A5 = 2'd0;
localparam [1:0] WAIT_5A = 2'd1;
localparam [1:0] READ_BODY = 2'd2;
localparam [1:0] READ_CHECKSUM = 2'd3;

localparam [31:0] MIN_FREQ_WORD = 32'd85899346;   // 1 MHz at 50 MHz
localparam [31:0] MAX_FREQ_WORD = 32'd343597384;  // 4 MHz at 50 MHz

reg [1:0] state = WAIT_A5;
reg [4:0] body_index = 5'd0;
reg [7:0] command = 8'd0;
reg [7:0] checksum = 8'd0;

initial begin
    config_valid = 1'b0;
    angle_table_valid = 1'b0;
    angle_table_index = 4'd0;
    freq_word = 32'h0A3D70A4;
    burst_cycles = 8'd2;
    delay0 = 16'd0;
    delay1 = 16'd0;
    delay2 = 16'd0;
    delay3 = 16'd0;
    delay4 = 16'd0;
    delay5 = 16'd0;
    delay6 = 16'd0;
    delay7 = 16'd0;
end

wire delays_valid =
    (delay0 <= MAX_DELAY_TICKS) && (delay1 <= MAX_DELAY_TICKS) &&
    (delay2 <= MAX_DELAY_TICKS) && (delay3 <= MAX_DELAY_TICKS) &&
    (delay4 <= MAX_DELAY_TICKS) && (delay5 <= MAX_DELAY_TICKS) &&
    (delay6 <= MAX_DELAY_TICKS) && (delay7 <= MAX_DELAY_TICKS);

always @(posedge clk) begin
    config_valid <= 1'b0;
    angle_table_valid <= 1'b0;

    if (rx_valid) begin
        case (state)
            WAIT_A5: begin
                if (rx_data == 8'hA5)
                    state <= WAIT_5A;
            end

            WAIT_5A: begin
                if (rx_data == 8'h5A) begin
                    state <= READ_BODY;
                    body_index <= 5'd0;
                    checksum <= 8'd0;
                end
                else if (rx_data != 8'hA5) begin
                    state <= WAIT_A5;
                end
            end

            READ_BODY: begin
                checksum <= checksum ^ rx_data;

                case (body_index)
                    5'd0: command <= rx_data;
                    5'd1: freq_word[7:0] <= rx_data;
                    5'd2: freq_word[15:8] <= rx_data;
                    5'd3: freq_word[23:16] <= rx_data;
                    5'd4: freq_word[31:24] <= rx_data;
                    5'd5: burst_cycles <= rx_data;
                    5'd6: delay0[7:0] <= rx_data;
                    5'd7: delay0[15:8] <= rx_data;
                    5'd8: delay1[7:0] <= rx_data;
                    5'd9: delay1[15:8] <= rx_data;
                    5'd10: delay2[7:0] <= rx_data;
                    5'd11: delay2[15:8] <= rx_data;
                    5'd12: delay3[7:0] <= rx_data;
                    5'd13: delay3[15:8] <= rx_data;
                    5'd14: delay4[7:0] <= rx_data;
                    5'd15: delay4[15:8] <= rx_data;
                    5'd16: delay5[7:0] <= rx_data;
                    5'd17: delay5[15:8] <= rx_data;
                    5'd18: delay6[7:0] <= rx_data;
                    5'd19: delay6[15:8] <= rx_data;
                    5'd20: delay7[7:0] <= rx_data;
                    5'd21: delay7[15:8] <= rx_data;
                    default: ;
                endcase

                if (body_index == 5'd21) begin
                    state <= READ_CHECKSUM;
                end
                else begin
                    body_index <= body_index + 1'b1;
                end
            end

            READ_CHECKSUM: begin
                if ((rx_data == checksum) && delays_valid) begin
                    if ((command == 8'h01) &&
                        (freq_word >= MIN_FREQ_WORD) &&
                        (freq_word <= MAX_FREQ_WORD) &&
                        (burst_cycles >= 8'd1) &&
                        (burst_cycles <= 8'd32)) begin
                        config_valid <= 1'b1;
                    end
                    else if ((command == 8'h02) &&
                             (burst_cycles <= 8'd10)) begin
                        angle_table_index <= burst_cycles[3:0];
                        angle_table_valid <= 1'b1;
                    end
                end
                state <= WAIT_A5;
            end

            default: state <= WAIT_A5;
        endcase
    end
end

endmodule
