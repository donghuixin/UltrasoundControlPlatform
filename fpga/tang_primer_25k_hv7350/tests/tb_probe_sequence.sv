`timescale 1ns/1ps

// External waveform assertions exercise continuous sessions and interruptions.
// The UART instance uses the production 115200 baud rate.
module tb_probe_sequence;
    reg clk = 0;
    always #10 clk = ~clk;
    reg s2 = 0;
    wire ready, done, j11, j10, uart_tx, sdram_off;
    wire [7:0] p, n;
    top #(.S2_DEBOUNCE_TICKS(4)) dut (
        .clk(clk), .s2(s2), .uart_rx_b3(1'b1), .uart_tx_c3(uart_tx),
        .led_ready(ready), .led_done(done), .sync_prf_j11(j11), .sync_prf_j10(j10),
        .tx1_pin_b2(p[0]), .tx1_nin_f2(n[0]), .tx2_pin_e1(p[1]), .tx2_nin_e3(n[1]),
        .tx3_pin_j1(p[2]), .tx3_nin_g4(n[2]), .tx4_pin_h1(p[3]), .tx4_nin_k7(n[3]),
        .tx5_pin_l7(p[4]), .tx5_nin_l10(n[4]), .tx6_pin_l9(p[5]), .tx6_nin_j8(n[5]),
        .tx7_pin_f7(p[6]), .tx7_nin_k8(n[6]), .tx8_pin_l8(p[7]), .tx8_nin_k10(n[7]),
        .sdram_disable_n_k9(sdram_off)
    );

    reg serial_rx = 1;
    wire serial_tx, u_ready, u_done, u_j11, u_j10;
    wire [7:0] up, un;
    top #(.S2_DEBOUNCE_TICKS(4)) uart_dut (
        .clk(clk), .s2(1'b0), .uart_rx_b3(serial_rx), .uart_tx_c3(serial_tx),
        .led_ready(u_ready), .led_done(u_done), .sync_prf_j11(u_j11), .sync_prf_j10(u_j10),
        .tx1_pin_b2(up[0]), .tx1_nin_f2(un[0]), .tx2_pin_e1(up[1]), .tx2_nin_e3(un[1]),
        .tx3_pin_j1(up[2]), .tx3_nin_g4(un[2]), .tx4_pin_h1(up[3]), .tx4_nin_k7(un[3]),
        .tx5_pin_l7(up[4]), .tx5_nin_l10(un[4]), .tx6_pin_l9(up[5]), .tx6_nin_j8(un[5]),
        .tx7_pin_f7(up[6]), .tx7_nin_k8(un[6]), .tx8_pin_l8(up[7]), .tx8_nin_k10(un[7]),
        .sdram_disable_n_k9()
    );

    integer cycle = 0, start_cycle = 0, elapsed, slot;
    integer session_triggers = 0, accepted_starts = 0;
    reg previous_active = 0;
    reg [7:0] expected_p, expected_n;
    integer u_cycle = 0, u_start_cycle = 0, u_slot;
    reg u_previous_active = 0;
    reg [7:0] u_expected_p, u_expected_n;
    integer response_count = 0;

    task check(input bit condition, input string description);
        if (!condition) $fatal(1, "%s (time=%0t)", description, $time);
    endtask

    // These intervals are the measured-contract edge times, not a duplicate
    // of the NCO or of the session/frame counter implementation.
    function automatic bit positive_at(input integer frame_position);
        positive_at = (frame_position >= 100 && frame_position < 112) ||
                      (frame_position >= 123 && frame_position < 135);
    endfunction
    function automatic bit negative_at(input integer frame_position);
        negative_at = frame_position >= 153 && frame_position < 158;
    endfunction

    always @(posedge clk) begin
        #2;
        cycle = cycle + 1;
        check(sdram_off === 1'b1, "SDRAM must remain deselected");
        check((p[7:4] | n[7:4] | up[7:4] | un[7:4]) === 4'b0,
              "HV5..HV8 must always be inactive");
        check((p & n) === 8'b0 && (up & un) === 8'b0, "PIN/NIN must not overlap");
        check(!done && !u_done, "continuous firmware must never assert DONE");
        check(dut.response_flags[7:1] == 0 && uart_dut.response_flags[7:1] == 0,
              "continuous status must not advertise natural completion");
        if (ready && !previous_active) begin
            start_cycle = cycle;
            session_triggers = 0;
            accepted_starts = accepted_starts + 1;
        end
        if (ready) begin
            elapsed = cycle - start_cycle;
            slot = elapsed % 5000;
            check(!done, "DONE must be off while transmitting");
            check(j11 === (slot < 10), "J11 must be 200 ns every 100 us");
            check(j10 === (slot >= 100 && slot < 2600), "J10 must start at +2 us and last 50 us");
            expected_p = positive_at(slot) ? (8'b1 << dut.selected_channel) : 8'b0;
            expected_n = negative_at(slot) ? (8'b1 << dut.selected_channel) : 8'b0;
            check(p === expected_p, "selected PIN two-cycle pulse or one-hot routing mismatch");
            check(n === expected_n, "selected NIN 140 ns wait / 100 ns tail mismatch");
            if (slot == 0) session_triggers = session_triggers + 1;
        end else begin
            check({j11,j10,p,n} === 18'b0, "idle/restart/stop must suppress every output");
        end
        previous_active = ready;

        u_cycle = u_cycle + 1;
        if (u_ready && !u_previous_active)
            u_start_cycle = u_cycle;
        if (u_ready) begin
            u_slot = (u_cycle - u_start_cycle) % 5000;
            check(u_j11 === (u_slot < 10), "UART-start J11 timing mismatch");
            check(u_j10 === (u_slot >= 100 && u_slot < 2600), "UART-start J10 timing mismatch");
            u_expected_p = positive_at(u_slot) ? (8'b1 << uart_dut.selected_channel) : 8'b0;
            u_expected_n = negative_at(u_slot) ? (8'b1 << uart_dut.selected_channel) : 8'b0;
            check(up === u_expected_p && un === u_expected_n, "UART-start waveform mismatch");
        end else check({u_j11,u_j10,up,un} === 18'b0, "UART idle/stop outputs not zero");
        u_previous_active = u_ready;
        if (uart_dut.response_valid) response_count = response_count + 1;
    end

    task button_press;
        @(negedge clk); s2 = 1;
        repeat (16) @(negedge clk);
        s2 = 0;
        repeat (16) @(negedge clk);
    endtask

    reg [7:0] injected_command, injected_argument;
    task command_inject(input [7:0] cmd, input [7:0] arg);
        @(negedge clk);
        injected_command = cmd;
        injected_argument = arg;
        force dut.command = injected_command;
        force dut.argument = injected_argument;
        force dut.sequence_id = 8'h80;
        force dut.command_valid = 1'b1;
        @(posedge clk); #0.1;
        release dut.command_valid;
        release dut.command;
        release dut.argument;
        release dut.sequence_id;
        #3;
    endtask

    localparam integer BIT_TICKS = 434;
    task send_byte(input [7:0] value);
        integer b;
        @(negedge clk); serial_rx = 0;
        repeat (BIT_TICKS) @(negedge clk);
        for (b = 0; b < 8; b = b + 1) begin
            serial_rx = value[b];
            repeat (BIT_TICKS) @(negedge clk);
        end
        serial_rx = 1;
        repeat (BIT_TICKS) @(negedge clk);
    endtask
    task receive_byte(output [7:0] value);
        integer b;
        @(negedge serial_tx);
        repeat (BIT_TICKS/2) @(posedge clk);
        #1; check(serial_tx === 0, "UART response start bit");
        for (b = 0; b < 8; b = b + 1) begin
            repeat (BIT_TICKS) @(posedge clk);
            #1; value[b] = serial_tx;
        end
        repeat (BIT_TICKS) @(posedge clk);
        #1; check(serial_tx === 1, "UART response stop bit");
    endtask
    task exchange(input [7:0] cmd, arg, seq, result, active_probe, next_probe, flags);
        reg [7:0] reply [0:8];
        integer k;
        begin
            fork
                begin
                    send_byte(8'hA5); send_byte(8'h5A); send_byte(cmd);
                    send_byte(arg); send_byte(seq); send_byte(cmd ^ arg ^ seq);
                end
                begin
                    for (k = 0; k < 9; k = k + 1) receive_byte(reply[k]);
                end
            join
            check(reply[0] == 8'h5A && reply[1] == 8'hA5, "response sync bytes");
            check(reply[2] == cmd && reply[3] == seq, "response command/sequence echo");
            check(reply[4] == result && reply[5] == active_probe &&
                  reply[6] == next_probe && reply[7] == flags, "response result/session status");
            check(reply[8] == (cmd ^ seq ^ result ^ active_probe ^ next_probe ^ flags),
                  "response checksum");
            repeat (BIT_TICKS) @(negedge clk);
        end
    endtask

    integer first_cycle, before_count;
    initial begin
        repeat (20) @(negedge clk);
        check(!ready && !done && !u_ready && !u_done, "power-up must be silent with both LEDs off");
        // A pulse below the debounce limit must not advance the cursor.
        s2 = 1; @(negedge clk); s2 = 0;
        repeat (16) @(negedge clk);
        check(!ready && dut.next_channel == 0, "button glitch accepted");

        // Holding the button must preserve one continuous session and cursor.
        s2 = 1;
        wait(ready); #3;
        check(dut.selected_channel == 0, "first press must select HV1");
        first_cycle = cycle;
        repeat (16000) @(negedge clk);
        check(ready && !done && accepted_starts == 1, "holding S2 stopped/retriggered the session");
        check(session_triggers == 4 && dut.selected_channel == 0,
              "held S2 must retain HV1 across successive PRF frames");
        s2 = 0; repeat (16) @(negedge clk);
        $display("PASS: power-up, debounce, held button, continuous frames, DONE remains off");

        button_press(); check(ready && dut.selected_channel == 1, "second press must select HV2");
        // Arrange debounce acceptance within the current positive burst.
        wait(dut.frame_tick == 103); @(negedge clk);
        check(p == 8'h02, "expected HV2 burst before button interruption");
        button_press(); check(ready && dut.selected_channel == 2, "running press must immediately select HV3");
        check(dut.frame_tick < 40, "running press did not restart the PRF frame");
        button_press(); check(dut.selected_channel == 3, "fourth press must select HV4");
        button_press(); check(dut.selected_channel == 0, "fifth press must wrap to HV1");
        $display("PASS: HV1-HV4 wrap, running-button interruption, full fresh pretrigger");

        // Restart the same probe exactly while its negative tail is active.
        wait(dut.frame_tick == 154); @(negedge clk);
        check(n == 8'h01, "expected negative tail before same-channel restart");
        command_inject(8'h10, 8'd1);
        check(!ready && p == 0 && n == 0, "restart must insert a registered all-low boundary");
        wait(ready); #3;
        check(ready && dut.selected_channel == 0 && p == 0 && n == 0,
              "same-probe START failed to clear old pulse engine");
        repeat (170) @(negedge clk);
        command_inject(8'h11, 0);
        wait(ready); #3; check(dut.selected_channel == 1, "UART NEXT cursor");
        repeat (104) @(negedge clk);
        command_inject(8'h12, 0);
        check(!ready && !done && {j11,j10,p,n} == 0, "STOP must abort immediately and clear DONE");
        $display("PASS: same-probe restart during tail, UART NEXT/STOP interrupt timing");

        exchange(8'h13, 0, 8'h01, 0, 0, 1, 0);
        exchange(8'h10, 3, 8'h02, 0, 3, 4, 1);
        exchange(8'h13, 0, 8'h03, 0, 3, 4, 1);
        exchange(8'h11, 0, 8'h04, 0, 4, 1, 1);
        exchange(8'h12, 0, 8'h05, 0, 0, 1, 0);
        exchange(8'h10, 5, 8'h06, 2, 0, 1, 0);
        exchange(8'h44, 0, 8'h07, 1, 0, 1, 0);
        before_count = response_count;
        send_byte(8'hA5); send_byte(8'h5A); send_byte(8'h10);
        send_byte(1); send_byte(8'h08); send_byte(8'h00); // bad checksum
        repeat (5000) @(negedge clk);
        check(response_count == before_count && !u_ready, "bad-checksum request was acted upon");
        $display("PASS: real 115200-baud START/NEXT/STOP/STATUS and reply decoding, invalid commands/checksum");
        $display("PASS: all probe sequence integration checks");
        $finish;
    end
    initial begin
        #30000000;
        $fatal(1, "probe sequence simulation watchdog expired");
    end
endmodule

// Continuous-duration regression: never deposits/forces a timer value.
// +FULL_DURATION runs every clock for six seconds, beyond the former 5 s limit,
// checks 60,000 complete frames, and then stops through the real UART receiver.
module tb_probe_duration;
    reg clk = 0, s2 = 0;
    reg serial_rx = 1;
    always #10 clk = ~clk;
    wire ready, done, j11, j10;
    wire [7:0] p, n;
    top #(.S2_DEBOUNCE_TICKS(4)) dut (
        .clk(clk), .s2(s2), .uart_rx_b3(serial_rx), .uart_tx_c3(),
        .led_ready(ready), .led_done(done), .sync_prf_j11(j11), .sync_prf_j10(j10),
        .tx1_pin_b2(p[0]), .tx1_nin_f2(n[0]), .tx2_pin_e1(p[1]), .tx2_nin_e3(n[1]),
        .tx3_pin_j1(p[2]), .tx3_nin_g4(n[2]), .tx4_pin_h1(p[3]), .tx4_nin_k7(n[3]),
        .tx5_pin_l7(p[4]), .tx5_nin_l10(n[4]), .tx6_pin_l9(p[5]), .tx6_nin_j8(n[5]),
        .tx7_pin_f7(p[6]), .tx7_nin_k8(n[6]), .tx8_pin_l8(p[7]), .tx8_nin_k10(n[7]),
        .sdram_disable_n_k9()
    );
    integer triggers = 0, positives = 0, negatives = 0;
    integer run_ticks, expected_frames;
    reg require_running = 0;
    time started_at;
    always @(posedge j11) triggers = triggers + 1;
    always @(posedge p[0]) positives = positives + 1;
    always @(posedge n[0]) negatives = negatives + 1;
    always @(p or n) begin
        if ((p[7:1] | n[7:1]) !== 7'b0)
            $fatal(1, "unselected output activated during default-duration run");
    end
    // Event-based guards observe every change without resuming an otherwise
    // idle testbench coroutine on all 300 million clock cycles.
    always @(posedge done)
        $fatal(1, "continuous session asserted DONE");
    always @(dut.response_flags) begin
        if (dut.response_flags[7:1] != 0)
            $fatal(1, "continuous session reported natural completion");
    end
    always @(negedge ready) begin
        if (require_running)
            $fatal(1, "continuous output stopped before explicit STOP");
    end
    localparam integer BIT_TICKS = 434;
    task send_byte(input [7:0] value);
        integer bit_index;
        @(negedge clk); serial_rx = 0;
        repeat (BIT_TICKS) @(negedge clk);
        for (bit_index = 0; bit_index < 8; bit_index = bit_index + 1) begin
            serial_rx = value[bit_index];
            repeat (BIT_TICKS) @(negedge clk);
        end
        serial_rx = 1;
        repeat (BIT_TICKS) @(negedge clk);
    endtask
    initial begin
        run_ticks = $test$plusargs("FULL_DURATION") ? 300000000 : 100000;
        expected_frames = run_ticks / 5000;
        repeat (16) @(negedge clk);
        s2 = 1; wait(ready); started_at = $time;
        require_running = 1;
        // Inspect the final clock before the next PRF frame. All expected
        // frames have completed; no extra trigger has yet been counted.
        // The FPGA's real 50 MHz clock continues throughout this delay; no
        // clocks, counters or internal state are skipped or forced.
        #((64'(run_ticks) - 1) * 20 + 2);
        if ($time - started_at != (64'(run_ticks) - 1) * 20 + 2)
            $fatal(1, "duration measurement mismatch: %0t", $time - started_at);
        if (!ready || done || dut.selected_channel != 0 || dut.next_channel != 1)
            $fatal(1, "held S2 changed/stopped the continuous session");
        if (triggers != expected_frames || positives != expected_frames * 2 ||
            negatives != expected_frames)
            $fatal(1, "continuous counts mismatch: triggers=%0d positive=%0d negative=%0d",
                   triggers, positives, negatives);
        @(posedge clk); #2;
        if (!ready || !j11 || triggers != expected_frames + 1)
            $fatal(1, "continuous session failed to start the following frame");
        $display("PASS: %0d complete continuous frames (%0d clocks), still running afterward",
                 expected_frames, run_ticks);
        require_running = 0;
        // Explicit STOP traverses the production UART at 115200 baud. Do not
        // force internal command/timer state in this long-duration regression.
        send_byte(8'hA5); send_byte(8'h5A); send_byte(8'h12);
        send_byte(8'h00); send_byte(8'h55); send_byte(8'h47);
        if (ready || done || {j11,j10,p,n} != 0)
            $fatal(1, "real UART STOP failed after continuous operation");
        repeat (100) @(negedge clk);
        if (ready || done || {j11,j10,p,n} != 0)
            $fatal(1, "held S2 retriggered explicitly stopped session");
        $display("PASS: explicit UART STOP after continuous run; held S2 does not restart");
        $finish;
    end
    initial begin
        #7000000000;
        $fatal(1, "continuous duration simulation watchdog expired");
    end
endmodule
