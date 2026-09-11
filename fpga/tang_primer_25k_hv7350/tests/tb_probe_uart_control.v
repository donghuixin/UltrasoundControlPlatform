`timescale 1ns/1ps
// Run with: iverilog -g2012 -s tb_probe_uart_control -o /tmp/probe_uart_test
//           src/probe_uart_control.v tests/tb_probe_uart_control.v
//           vvp /tmp/probe_uart_test
module tb_probe_uart_control;
    localparam integer BIT_TICKS = 434; // Rounded 50MHz / 115200, production values.
    localparam integer BIT_NS = BIT_TICKS * 20;
    reg clk = 0;
    always #10 clk = !clk;
    reg rx = 1;
    wire tx, command_valid, response_busy;
    wire [7:0] command, argument, sequence_id;
    reg response_valid = 0;
    reg [7:0] response_command = 8'h10, response_sequence = 0, response_result = 0;
    reg [7:0] response_active = 1, response_next = 2, response_flags = 1;
    probe_uart_control dut(.*);

    integer commands = 0;
    reg command_was_valid = 0;
    reg [7:0] last_command, last_argument, last_sequence;
    always @(posedge clk) begin
        if (command_valid && command_was_valid) $fatal(1, "command_valid is not a one-cycle pulse");
        command_was_valid <= command_valid;
        if (command_valid) begin
            commands <= commands + 1;
            last_command <= command;
            last_argument <= argument;
            last_sequence <= sequence_id;
        end
    end

    task send_byte;
        input [7:0] value;
        input bad_stop;
        integer bit_index;
        begin
            rx = 0; #(BIT_NS);
            for (bit_index=0; bit_index<8; bit_index=bit_index+1) begin
                rx = value[bit_index]; #(BIT_NS);
            end
            rx = !bad_stop; #(BIT_NS);
        end
    endtask

    task send_request;
        input [7:0] cmd, arg, seq;
        input bad_checksum;
        begin
            send_byte(8'hA5, 0); send_byte(8'h5A, 0);
            send_byte(cmd, 0); send_byte(arg, 0); send_byte(seq, 0);
            send_byte((cmd ^ arg ^ seq) ^ (bad_checksum ? 8'h01 : 8'h00), 0);
            #(BIT_NS);
        end
    endtask

    task expect_commands;
        input integer expected;
        begin
            if (commands != expected) $fatal(1, "expected %0d commands, got %0d", expected, commands);
        end
    endtask

    task issue_response;
        input [7:0] seq;
        begin
            @(negedge clk); response_sequence = seq; response_valid = 1;
            @(negedge clk); response_valid = 0;
        end
    endtask

    task receive_byte;
        output [7:0] value;
        integer bit_index;
        begin
            @(negedge tx); #(BIT_NS/2);
            if (tx !== 0) $fatal(1, "TX start bit invalid");
            for (bit_index=0; bit_index<8; bit_index=bit_index+1) begin
                #(BIT_NS); value[bit_index] = tx;
            end
            #(BIT_NS);
            if (tx !== 1) $fatal(1, "TX stop bit invalid");
        end
    endtask

    task expect_response;
        input [7:0] seq;
        reg [7:0] value;
        reg [7:0] expected [0:8];
        integer index;
        begin
            expected[0]=8'h5A; expected[1]=8'hA5; expected[2]=8'h10; expected[3]=seq;
            expected[4]=0; expected[5]=1; expected[6]=2; expected[7]=1;
            expected[8]=8'h10 ^ seq ^ 8'd1 ^ 8'd2 ^ 8'd1;
            for (index=0; index<9; index=index+1) begin
                receive_byte(value);
                if (value !== expected[index])
                    $fatal(1, "TX byte %0d expected %02x got %02x", index, expected[index], value);
            end
        end
    endtask

    initial begin
        #1000;
        if (tx !== 1 || response_busy !== 0) $fatal(1, "bad initial TX state");
        // Valid command, then continuous back-to-back bytes with overlapping A5 header.
        send_request(8'h10, 3, 8'h42, 0);
        expect_commands(1);
        if (last_command !== 8'h10 || last_argument !== 3 || last_sequence !== 8'h42)
            $fatal(1, "wrong decoded fields");
        send_byte(8'hA5, 0);
        send_request(8'h11, 0, 8'h43, 0);
        expect_commands(2);
        // Wrong checksum and noise must never execute a command.
        send_request(8'h12, 0, 8'h44, 1);
        send_byte(8'hFF, 0); send_byte(8'h5A, 0); #(BIT_NS);
        expect_commands(2);
        // Incomplete request expires after 10ms, then parser recovers.
        send_byte(8'hA5, 0); send_byte(8'h5A, 0); send_byte(8'h10, 0);
        #10010000;
        send_byte(1, 0); send_byte(2, 0); send_byte(8'h13, 0); #(BIT_NS);
        expect_commands(2);
        send_request(8'h13, 0, 8'h45, 0);
        expect_commands(3);
        // A bad stop bit plus a long break flushes parser and does not invent bytes.
        send_byte(8'hA5, 0); send_byte(8'h5A, 1);
        #(BIT_NS*30); rx = 1; #(BIT_NS*2);
        send_request(8'h12, 0, 8'h46, 0);
        expect_commands(4);
        // Start glitch before a fresh valid request.
        rx = 0; #(BIT_NS/4); rx = 1; #(BIT_NS*2);
        send_request(8'h10, 4, 8'h47, 0);
        expect_commands(5);
        // RX remains live during TX; queue a second response and validate both.
        fork
            begin
                issue_response(8'h61);
                #(BIT_NS*4);
                if (!response_busy) $fatal(1, "busy missing while transmitting");
                issue_response(8'h62);
                send_request(8'h12, 0, 8'h48, 0);
                expect_commands(6);
            end
            begin
                expect_response(8'h61);
                expect_response(8'h62);
            end
        join
        #(BIT_NS*2);
        if (response_busy || tx !== 1) $fatal(1, "TX did not return to idle");
        $display("PASS probe_uart_control: RX, noise, checksum, timeout, framing, break, TX, queue, duplex");
        $finish;
    end

    initial begin
        #50000000;
        $fatal(1, "UART test timeout");
    end
endmodule
