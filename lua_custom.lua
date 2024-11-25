local my_protocol = Proto("MyProtocol", "Custom UDP Protocol")

local f_msg_type = ProtoField.uint8("myprotocol.msg_type", "Message Type", base.DEC)
local f_sequence_number = ProtoField.uint32("myprotocol.sequence_number", "Sequence Number", base.DEC)
local f_crc = ProtoField.uint32("myprotocol.crc", "CRC", base.HEX)
local f_data = ProtoField.bytes("myprotocol.data", "Data")


my_protocol.fields = {f_msg_type, f_sequence_number, f_crc, f_data}


local function get_message_type_name(msg_type)
    local msg_types = {
        [0] = "Default",
        [1] = "SYN",
        [2] = "SYN-ACK",
        [3] = "ACK",
        [4] = "FIN",
        [5] = "Keep-Alive",
        [6] = "Fragment",
        [7] = "Last Fragment",
        [8] = "File Info",
        [9] = "File Fragment",
        [10] = "Last File Fragment",
        [12] = "Fragment NAK"
    }
    return msg_types[msg_type] or "Unknown"
end


function my_protocol.dissector(buffer, pinfo, tree)
    -- Validate packet length
    if buffer:len() < 9 then
        return -- Not enough data for header
    end

    -- Update name
    pinfo.cols.protocol = my_protocol.name

    local subtree = tree:add(my_protocol, buffer(), "Custom UDP Protocol Data")

    -- we parse fields
    local msg_type = buffer(0, 1):uint()
    local sequence_number = buffer(1, 4):uint()
    local crc = buffer(5, 4):uint()
    local data = buffer(9):bytes()

    subtree:add(f_msg_type, buffer(0, 1)):append_text(" (" .. get_message_type_name(msg_type) .. ")")
    subtree:add(f_sequence_number, buffer(1, 4))
    subtree:add(f_crc, buffer(5, 4))
    subtree:add(f_data, buffer(9)):append_text(" (" .. data:len() .. " bytes)")

    pinfo.cols.info:set("Type: " .. get_message_type_name(msg_type) .. ", Seq: " .. sequence_number)

    if msg_type == 8 or msg_type == 9 or msg_type == 10 then
        subtree:set_text(" Data Message")
        pinfo.cols.info:append(" [DATA]")
    elseif msg_type == 5 then
        subtree:set_text("Overhead Message")
        pinfo.cols.info:append(" [KEEP-ALIVE]")
    else
        subtree:set_text("Other Message")
    end
end


local udp_port = DissectorTable.get("udp.port")
udp_port:add(65432, my_protocol)
