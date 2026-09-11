// Four independent HV7350 probes, Tang Primer 25K, 50 MHz / 3.3 V I/O.
// Power-up is silent. S2 advances HV1 -> HV2 -> HV3 -> HV4 -> HV1,
// starting a fresh five-second, 10 kHz session on exactly one output.
// A press during a session aborts it and starts the next probe. UART can
// START a selected probe, NEXT, STOP, or query STATUS; see four_probe_control.md.
// READY is high while running; DONE latches high only on normal five-second
// completion. S1 is unused. HV5..HV8 always have PIN=NIN=0.
// The measured waveform is unchanged: 2.2 MHz, two positive RTZ cycles,
// 140 ns post-burst delay and one 100 ns negative damping pulse.
// J11 is 200 ns wide and leads each burst/J10 rising edge by exactly 2 us.
module top #(
    parameter integer CLK_FREQ_HZ = 50_000_000,
    parameter integer UART_BAUD = 115_200,
    parameter integer S2_DEBOUNCE_TICKS = CLK_FREQ_HZ / 50,
    parameter integer SESSION_TICKS = CLK_FREQ_HZ * 5,
    parameter integer PRF_PERIOD_TICKS = CLK_FREQ_HZ / 10_000,
    parameter integer PRF_HALF_TICKS = PRF_PERIOD_TICKS / 2,
    parameter integer PRETRIGGER_TICKS = CLK_FREQ_HZ / 500_000,
    parameter integer TRIGGER_PULSE_TICKS = CLK_FREQ_HZ / 5_000_000,
    parameter integer DAMP_PULSE_TICKS = CLK_FREQ_HZ / 10_000_000,
    parameter [31:0] DEFAULT_FREQ_WORD = 32'h0B439581,
    parameter [7:0] DEFAULT_BURST_CYCLES = 8'd2
)(
    input wire clk,
    input wire s2,
    input wire uart_rx_b3,
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
    // These outputs share the dock SDRAM bus: keep its CS_N inactive.
    output wire sdram_disable_n_k9
);

localparam [15:0] FIXED_DAMP_DELAY_TICKS = 16'd7;
assign sdram_disable_n_k9 = 1'b1;

// Synchronize and debounce both press and release. Holding S2 produces only
// one event. "Immediate" switching means after the normal 20 ms debounce.
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

wire command_valid;
wire [7:0] command;
wire [7:0] argument;
wire [7:0] sequence_id;
reg response_valid = 1'b0;
reg response_pending = 1'b0;
reg [7:0] response_command = 8'd0;
reg [7:0] response_sequence = 8'd0;
reg [7:0] response_result = 8'd0;
reg [7:0] response_active = 8'd0;
reg [7:0] response_next = 8'd1;
reg [7:0] response_flags = 8'd0;
wire response_busy;

probe_uart_control #(
    .CLK_FREQ_HZ(CLK_FREQ_HZ), .UART_BAUD(UART_BAUD)
) control_uart (
    .clk(clk), .rx(uart_rx_b3), .tx(uart_tx_c3),
    .command_valid(command_valid), .command(command),
    .argument(argument), .sequence_id(sequence_id),
    .response_valid(response_valid),
    .response_command(response_command), .response_sequence(response_sequence),
    .response_result(response_result), .response_active(response_active),
    .response_next(response_next), .response_flags(response_flags),
    .response_busy(response_busy)
);

wire uart_start = command_valid && (command == 8'h10) &&
                  (argument >= 8'd1) && (argument <= 8'd4);
wire uart_next = command_valid && (command == 8'h11) && (argument == 8'd0);
wire uart_stop = command_valid && (command == 8'h12) && (argument == 8'd0);
wire command_known = (command == 8'h10) || (command == 8'h11) ||
                     (command == 8'h12) || (command == 8'h13);
wire argument_valid = (command == 8'h10) ?
                      ((argument >= 8'd1) && (argument <= 8'd4)) :
                      (argument == 8'd0);

// One shared pulse engine feeds a one-of-four output selector, so the four
// probes cannot run simultaneously. Unselected PIN=NIN=0 means RTZ, NOT Hi-Z.
reg session_active = 1'b0;
reg session_completed = 1'b0;
reg [1:0] selected_channel = 2'd0;
reg [1:0] next_channel = 2'd0;
reg [31:0] session_count = 32'd0;
reg [15:0] frame_tick = 16'd0;

// UART STOP wins over a simultaneous button event. UART START wins over NEXT.
// The software and button share one cursor: START HV3 makes the next HV4.
wire request_start = !uart_stop && (uart_start || uart_next || s2_pressed);
wire [1:0] requested_channel = uart_start ?
                              (argument[1:0] - 2'd1) : next_channel;
// Suppress old pulses and reset the engine on every restart, including a
// restart of the SAME channel during a burst or its negative damping tail.
wire channel_run_enable = session_active && !request_start && !uart_stop;
wire frame_start = channel_run_enable &&
                   (frame_tick == PRETRIGGER_TICKS - 1);

always @(posedge clk) begin
    if (uart_stop) begin
        session_active <= 1'b0;
        session_completed <= 1'b0;
        session_count <= 32'd0;
        frame_tick <= 16'd0;
    end
    else if (request_start) begin
        selected_channel <= requested_channel;
        next_channel <= requested_channel + 2'd1;
        session_active <= 1'b1;
        session_completed <= 1'b0;
        session_count <= 32'd0;
        frame_tick <= 16'd0;
    end
    else if (session_active) begin
        if (session_count == SESSION_TICKS - 1) begin
            session_active <= 1'b0;
            session_completed <= 1'b1;
            session_count <= 32'd0;
            frame_tick <= 16'd0;
        end
        else begin
            session_count <= session_count + 1'b1;
            if (frame_tick == PRF_PERIOD_TICKS - 1)
                frame_tick <= 16'd0;
            else
                frame_tick <= frame_tick + 1'b1;
        end
    end
end

// Capture status AFTER the command has updated the session state. Responses
// are acknowledgments/status snapshots, not ultrasound data or ADC triggers.
// The host must wait for a response before sending another normal request.
// STOP is never blocked by response_busy.
always @(posedge clk) begin
    response_pending <= command_valid;
    response_valid <= response_pending;
    if (command_valid) begin
        response_command <= command;
        response_sequence <= sequence_id;
        if (!command_known)
            response_result <= 8'd1;
        else if (!argument_valid)
            response_result <= 8'd2;
        else
            response_result <= 8'd0;
    end
    if (response_pending) begin
        response_active <= session_active ?
                           ({6'd0, selected_channel} + 8'd1) : 8'd0;
        response_next <= {6'd0, next_channel} + 8'd1;
        response_flags <= {6'd0, session_completed, session_active};
    end
end

wire ch_pin;
wire ch_nin;
hv7350_tx_channel #(.DAMP_PULSE_TICKS(DAMP_PULSE_TICKS)) pulse_generator (
    .clk(clk), .run_enable(channel_run_enable), .frame_start(frame_start),
    .freq_word(DEFAULT_FREQ_WORD), .burst_cycles(DEFAULT_BURST_CYCLES),
    .start_delay_ticks(16'd0), .damp_delay_ticks(FIXED_DAMP_DELAY_TICKS),
    .pin_out(ch_pin), .nin_out(ch_nin)
);

// Register ALL external timing signals together. Combinational decoding of
// a binary frame counter or selector must never directly drive the HV pulser:
// unequal propagation delays could otherwise create unintended narrow pulses.
// This adds the SAME one-clock latency to J11, J10, PIN, NIN and READY, leaving
// all relative timing and the five-second external session length unchanged.
// Restart/STOP samples run_enable=0 and clears the old outputs on that edge;
// a new session begins with a full low clock followed by a fresh J11 pulse.
reg [3:0] pin_registered = 4'd0;
reg [3:0] nin_registered = 4'd0;
reg j11_registered = 1'b0;
reg j10_registered = 1'b0;
reg ready_registered = 1'b0;
reg done_registered = 1'b0;
always @(posedge clk) begin
    ready_registered <= channel_run_enable;
    done_registered <= session_completed;
    j11_registered <= channel_run_enable && (frame_tick < TRIGGER_PULSE_TICKS);
    j10_registered <= channel_run_enable &&
                      (frame_tick >= PRETRIGGER_TICKS) &&
                      (frame_tick < PRETRIGGER_TICKS + PRF_HALF_TICKS);
    pin_registered <= 4'd0;
    nin_registered <= 4'd0;
    if (channel_run_enable) begin
        pin_registered[selected_channel] <= ch_pin;
        nin_registered[selected_channel] <= ch_nin;
    end
end
assign led_ready = ready_registered;
assign led_done = done_registered;
assign sync_prf_j11 = j11_registered;
assign sync_prf_j10 = j10_registered;
assign tx1_pin_b2 = pin_registered[0];
assign tx1_nin_f2 = nin_registered[0];
assign tx2_pin_e1 = pin_registered[1];
assign tx2_nin_e3 = nin_registered[1];
assign tx3_pin_j1 = pin_registered[2];
assign tx3_nin_g4 = nin_registered[2];
assign tx4_pin_h1 = pin_registered[3];
assign tx4_nin_k7 = nin_registered[3];
assign tx5_pin_l7 = 1'b0;
assign tx5_nin_l10 = 1'b0;
assign tx6_pin_l9 = 1'b0;
assign tx6_nin_j8 = 1'b0;
assign tx7_pin_f7 = 1'b0;
assign tx7_nin_k8 = 1'b0;
assign tx8_pin_l8 = 1'b0;
assign tx8_nin_k10 = 1'b0;

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
