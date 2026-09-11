// USB-C debugger UART bridge, 115200 8N1 by default (FPGA RX=B3, TX=C3).
// Request:  A5 5A cmd arg seq xor(cmd,arg,seq).
// Response: 5A A5 cmd seq result active next flags xor(cmd..flags).
// Only a complete request with a valid UART stop bit/checksum emits a command.
// Command semantics and response snapshots belong to the parent controller.
// Host must keep one request outstanding. TX can additionally queue one response
// (e.g. an urgent STOP); further responses while BOTH slots are full are dropped.
// response_busy means transmitting OR queued, not "queue full". RX stays enabled.
module probe_uart_control #(
    parameter integer CLK_FREQ_HZ = 50_000_000,
    parameter integer UART_BAUD = 115200
) (
    input wire clk,
    input wire rx,
    output wire tx,
    output reg command_valid = 1'b0,
    output reg [7:0] command = 8'd0,
    output reg [7:0] argument = 8'd0,
    output reg [7:0] sequence_id = 8'd0,
    input wire response_valid,
    input wire [7:0] response_command,
    input wire [7:0] response_sequence,
    input wire [7:0] response_result,
    input wire [7:0] response_active,
    input wire [7:0] response_next,
    input wire [7:0] response_flags,
    output wire response_busy
);
    localparam integer BIT_TICKS = (CLK_FREQ_HZ + UART_BAUD/2) / UART_BAUD;
    localparam integer HALF_TICKS = BIT_TICKS / 2;
    localparam integer BIT_WIDTH = (BIT_TICKS < 2) ? 1 : $clog2(BIT_TICKS);
    localparam integer TIMEOUT_TICKS = (CLK_FREQ_HZ / 100 < 1) ? 1 : CLK_FREQ_HZ / 100;
    localparam integer TIMEOUT_WIDTH = (TIMEOUT_TICKS < 2) ? 1 : $clog2(TIMEOUT_TICKS);

    reg [2:0] rx_sync = 3'b111;
    reg rx_previous = 1'b1;
    reg [2:0] rx_state = 3'd0;
    reg [BIT_WIDTH-1:0] rx_ticks = 0;
    reg [2:0] rx_bit = 0;
    reg [7:0] rx_shift = 0;
    reg [7:0] rx_byte = 0;
    reg rx_valid = 1'b0;
    reg rx_error = 1'b0;

    always @(posedge clk) begin
        rx_sync <= {rx_sync[1:0], rx};
        rx_previous <= rx_sync[2];
        rx_valid <= 1'b0;
        rx_error <= 1'b0;
        case (rx_state)
            0: if (rx_previous && !rx_sync[2]) begin
                rx_ticks <= HALF_TICKS - 1;
                rx_state <= 1;
            end
            1: if (rx_ticks != 0) rx_ticks <= rx_ticks - 1'b1;
               else if (!rx_sync[2]) begin
                   rx_ticks <= BIT_TICKS - 1;
                   rx_bit <= 0;
                   rx_state <= 2;
               end else begin
                   rx_state <= 0; // Reject a start glitch shorter than half a bit.
                   rx_error <= 1'b1;
               end
            2: if (rx_ticks != 0) rx_ticks <= rx_ticks - 1'b1;
               else begin
                   rx_shift[rx_bit] <= rx_sync[2];
                   rx_ticks <= BIT_TICKS - 1;
                   if (rx_bit == 7) rx_state <= 3;
                   else rx_bit <= rx_bit + 1'b1;
               end
            3: if (rx_ticks != 0) rx_ticks <= rx_ticks - 1'b1;
               else if (rx_sync[2]) begin
                   rx_byte <= rx_shift;
                   rx_valid <= 1'b1;
                   rx_state <= 0;
               end else begin
                   rx_error <= 1'b1;
                   rx_state <= 4;
               end
            4: if (rx_sync[2]) rx_state <= 0; // Break: require idle before recovery.
            default: rx_state <= 0;
        endcase
    end

    reg [2:0] parse_state = 0;
    reg [7:0] request_command = 0;
    reg [7:0] request_argument = 0;
    reg [7:0] request_sequence = 0;
    reg [TIMEOUT_WIDTH-1:0] parse_ticks = 0;
    always @(posedge clk) begin
        command_valid <= 1'b0;
        if (rx_error) begin
            parse_state <= 0;
            parse_ticks <= 0;
        end else if (rx_valid) begin
            parse_ticks <= 0;
            case (parse_state)
                0: if (rx_byte == 8'hA5) parse_state <= 1;
                1: if (rx_byte == 8'h5A) parse_state <= 2;
                   else if (rx_byte != 8'hA5) parse_state <= 0;
                2: begin request_command <= rx_byte; parse_state <= 3; end
                3: begin request_argument <= rx_byte; parse_state <= 4; end
                4: begin request_sequence <= rx_byte; parse_state <= 5; end
                5: begin
                    parse_state <= 0;
                    if (rx_byte == (request_command ^ request_argument ^ request_sequence)) begin
                        command <= request_command;
                        argument <= request_argument;
                        sequence_id <= request_sequence;
                        command_valid <= 1'b1;
                    end
                end
                default: parse_state <= 0;
            endcase
        end else if (parse_state != 0) begin
            if (parse_ticks == TIMEOUT_TICKS - 1) begin
                parse_state <= 0;
                parse_ticks <= 0;
            end else parse_ticks <= parse_ticks + 1'b1;
        end else parse_ticks <= 0;
    end

    function [89:0] response_frame;
        input [7:0] cmd, seq, result, active, next_probe, flags;
        reg [7:0] checksum;
        begin
            checksum = cmd ^ seq ^ result ^ active ^ next_probe ^ flags;
            // Rightmost bit goes first; each byte is start, LSB first, stop.
            response_frame = {1'b1, checksum, 1'b0,
                              1'b1, flags, 1'b0,
                              1'b1, next_probe, 1'b0,
                              1'b1, active, 1'b0,
                              1'b1, result, 1'b0,
                              1'b1, seq, 1'b0,
                              1'b1, cmd, 1'b0,
                              1'b1, 8'hA5, 1'b0,
                              1'b1, 8'h5A, 1'b0};
        end
    endfunction
    wire [89:0] incoming_frame = response_frame(response_command, response_sequence,
        response_result, response_active, response_next, response_flags);
    reg [89:0] tx_shift = {90{1'b1}};
    reg [89:0] pending_frame = {90{1'b1}};
    reg pending_valid = 1'b0;
    reg tx_active = 1'b0;
    reg [6:0] tx_remaining = 0;
    reg [BIT_WIDTH-1:0] tx_ticks = 0;
    assign tx = tx_active ? tx_shift[0] : 1'b1;
    assign response_busy = tx_active || pending_valid;

    always @(posedge clk) begin
        if (!tx_active || (tx_ticks == 0 && tx_remaining == 1)) begin
            // Packet boundary: an old queued response always precedes a new one.
            if (pending_valid) begin
                tx_shift <= pending_frame;
                tx_active <= 1'b1;
                tx_remaining <= 90;
                tx_ticks <= BIT_TICKS - 1;
                pending_valid <= response_valid;
                if (response_valid) pending_frame <= incoming_frame;
            end else if (response_valid) begin
                tx_shift <= incoming_frame;
                tx_active <= 1'b1;
                tx_remaining <= 90;
                tx_ticks <= BIT_TICKS - 1;
            end else begin
                tx_active <= 1'b0;
                tx_remaining <= 0;
            end
        end else begin
            if (tx_ticks == 0) begin
                tx_shift <= {1'b1, tx_shift[89:1]};
                tx_remaining <= tx_remaining - 1'b1;
                tx_ticks <= BIT_TICKS - 1;
            end else tx_ticks <= tx_ticks - 1'b1;
            if (response_valid && !pending_valid) begin
                pending_frame <= incoming_frame;
                pending_valid <= 1'b1;
            end
        end
    end
endmodule
