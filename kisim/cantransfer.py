import serial

#
# this implements an interface to receive and send CAN frames (ID + 0..8 bytes 
# of data). For now this only talks with a LAWICEL CANUSB device over pyserial.
#

class CanTransferInterface:
    pass

class CanUsb(CanTransferInterface):
    OK = "\r"
    ERR = "\7"
    TRANSMITTED0 = "z\r"
    TRANSMITTED1 = "Z\r"

    def __init__(self, path, log_filename = None):
        CanTransferInterface.__init__(self)
        self.can = None
        self.log_filename = log_filename
        self.log = None
        self.open(path)

    def read_single_result(self):
        a = ""
        while True:
            v = self.can.read(1)
            if v == "" and not a:
                return None
            a += v
            if v in ("\r", "\7"):
                break
        return a
    
    def read_result(self, poll = False):
        while True:
            r = self.read_single_result()
            if r is None:
                if not poll:
                    continue
                return None
            if r.startswith("t"):
                id = int(r[1:4], 0x10)
                l = int(r[4], 0x10)
                data = r[5:5+l*2].decode('hex')
                timestamp = int(r[5+l*2:5+l*2+4], 0x10)
                self.pending_receive.append((id, data, timestamp))
                if poll:
                    return None
            else:
                return r

    def cmd(self, cmd):
        self.can.write(bytes(cmd + "\r"))
        res = self.read_result()
        if res != "\x7A\x0D":
            print "cmd %s, res %s" % (cmd, res.encode('hex'))
        return res
    
    def open(self, path):
        assert self.can is None
        self.can = serial.Serial(path, timeout = .01)
        self.can.read(1024)
        self.pending_receive = []
        self.version = self.cmd("V")
        assert self.version is not None and self.version[:3] == "V10"
        assert self.cmd("C")
        assert self.cmd("S3") == self.OK
        assert self.cmd("O") == self.OK
        if self.log_filename is not None:
            self.log = open(self.log_filename, "w")

    def close(self):
        self.can.close()
        self.can = None

        if self.log is not None:
            self.log.close()
            self.log = None

    def send_message(self, id, data):
        msg = "t%03x%1x" % (id, len(data)) + data.encode('hex')
        if self.log is not None:
            self.log.write(msg + "\n")
        success = self.cmd(msg) == self.TRANSMITTED0
        return success

    def poll(self):
        r = self.read_result(True)
        if r is not None:
            print "unknown message: " +    r
        res = self.pending_receive
        self.pending_receive = []
        return res
