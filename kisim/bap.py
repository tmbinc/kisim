import struct

class Bap:
    def __init__(self):
        self.pktlen = {}
        self.data = {}
        self.target = {}

    def receive_can(self, can_id, data):
        header = struct.unpack(">H", data[:2])[0]

        logical_channel = can_id
        if header & 0x8000 == 0x8000:
            logical_channel |= ((header >> 12) & 3) << 16

        if header & 0xC000 == 0x8000: # start
            self.pktlen[logical_channel] = header & 0xFFF
            header = struct.unpack(">H", data[2:4])[0]
            self.target[logical_channel] = header
            self.data[logical_channel] = data[4:]
        elif header & 0xC000 == 0xC000 and self.data.get(logical_channel) is not None: # data
            self.data[logical_channel] += data[1:]
        else:
            self.target[logical_channel] = header
            self.data[logical_channel] = data[2:]
            self.pktlen[logical_channel] = len(self.data[logical_channel])

        # check for message completion

        if len(self.data[logical_channel]) == self.pktlen[logical_channel]:

            header = self.target[logical_channel]
            opcode = (header >> 12) & 7
            lsg_id = (header >> 6) & 0x3F
            fct_id = (header >> 0) & 0x3F

            res = (can_id, opcode, lsg_id, fct_id, self.data[logical_channel])
            del self.data[logical_channel]

            return res

        return None

    def send(self, id, opcode, lsg_id, fct_id, data = ""):
        res = []
        header = struct.pack(">H", (opcode << 12) | (lsg_id << 6) | fct_id)
        if len(data) <= 6:
            res.append((id, header + data))
        else:
            res.append((id, struct.pack(">H", 0x8000 | len(data)) + header + data[:4]))
            data = data[4:]
            idx = 0xC0
            while len(data):
                res.append((id, chr(idx) + data[:7]))
                data = data[7:]
            idx += 1

        return res
