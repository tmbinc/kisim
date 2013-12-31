import wpf, threading, struct
import time
from copy import copy

from System.Windows import Application, Window, MessageBox, MessageBoxButton, MessageBoxImage
from System.Windows.Controls import TabItem, TextBox
from System.Timers import Timer
from Queue import Queue
from System import TimeSpan
from System.Windows.Threading import DispatcherTimer
from System.ComponentModel import INotifyPropertyChanged, PropertyChangedEventArgs
from System.Collections.ObjectModel import ObservableCollection
import pyevent

from cantransfer import CanUsb
from bap import Bap
from About import About
from kiicons import ki_icons

import argparse

class NotifyPropertyChangedBase(INotifyPropertyChanged):
    """INotifyProperty Helper"""
    PropertyChanged = None
    def __init__(self):
        (self.PropertyChanged, self._propertyChangedCaller) = pyevent.make_event()

    def add_PropertyChanged(self, value):
        self.PropertyChanged += value

    def remove_PropertyChanged(self, value):
        self.PropertyChanged -= value

    def OnPropertyChanged(self, propertyName):
        self._propertyChangedCaller(self, PropertyChangedEventArgs(propertyName))
    
class CanMessage(NotifyPropertyChangedBase):
    @property
    def Id(self):
        return self._Id

    @Id.setter
    def Id(self, Id):
        self._Id = Id
        self.OnPropertyChanged("Id")

    @property
    def Message(self):
        return self._Message

    @Message.setter
    def Message(self, value):
        self._Message = value
        self.OnPropertyChanged("Message")

    @property
    def Count(self):
        return self._Count

    @Count.setter
    def Count(self, value):
        self._Count = value
        self.OnPropertyChanged("Count")

class BapMessage(NotifyPropertyChangedBase):

    def __init__(self):
        NotifyPropertyChangedBase.__init__(self)
        self._LsgId = None

    @property
    def Timestamp(self):
        return self._Timestamp

    @Timestamp.setter
    def Timestamp(self, Timestamp):
        self._Timestamp = Timestamp
        self.OnPropertyChanged("Timestamp")

    @property
    def Direction(self):
        return "TO SG" if self._Direction else "FROM SG"

    @Direction.setter
    def Direction(self, Direction):
        self._Direction = Direction
        self.OnPropertyChanged("Direction")

    @property
    def CanId(self):
        return self._CanId

    @CanId.setter
    def CanId(self, CanId):
        self._CanId = CanId
        self.OnPropertyChanged("CanId")

    @property
    def Opcode(self):
        return self._Opcode

    @Opcode.setter
    def Opcode(self, Opcode):
        self._Opcode = Opcode
        self.OnPropertyChanged("Opcode")

    @property
    def LsgId(self):
        return self._LsgId

    @LsgId.setter
    def LsgId(self, LsgId):
        self._LsgId = LsgId
        self.OnPropertyChanged("LsgId")

    @property
    def FctId(self):
        Functions = {
            1: "Refresh",
            2: "SetConfig?",
            3: "List?",
            4: "Watchdog",
            13: "Ctrl?",
            14: "Setup?",
            15: "SetState?",
        }

        FunctionsLsg = {
            (43, 20):  "ScreenData",
            (43, 22):  "CurrentScreen",
        }
        
        return "%d: " % self._FctId + Functions.get(self._FctId, FunctionsLsg.get((self._LsgId, self._FctId), ""))

    @FctId.setter
    def FctId(self, FctId):
        self._FctId = FctId
        self.OnPropertyChanged("FctId")

    @property
    def Data(self):
        return self._Data.encode('hex')

    @Data.setter
    def Data(self, Data):
        self._Data = Data
        self.OnPropertyChanged("Data")
        self.OnPropertyChanged("Text")

    @property
    def Text(self):
        return ''.join(x if 32 <= ord(x) <  128 else '.' for x in self._Data)

class CanThreadInternal(threading.Thread):
    CMD_SEND_CAN, CMD_SCHEDULE, CMD_UNSCHEDULE, CMD_EXIT = range(4)

    RAW_CAN = 0

    def __init__(self, path, command_queue, output_queue, log_path):
        threading.Thread.__init__(self)
        self.command_queue = command_queue
        self.output_queue = output_queue
        self.cantransfer = CanUsb(path, log_path)
        self.scheduled_transmits = {}
        self.tick = 0
    
    def schedule_transmit(self):
        self.tick += 1
        for rate, offset, id, data in self.scheduled_transmits.values():
            if self.tick % rate == offset:
                if not self.cantransfer.send_message(id, data):
                    #print "scheduled transmit failed"
                    pass

    def run(self):
        print "Started Can Thread"
        while True:
            self.schedule_transmit()
            while not self.command_queue.empty():
                cmd, data = self.command_queue.get()
                if cmd == self.CMD_SEND_CAN:
                    self.cantransfer.send_message(*data)
                elif cmd == self.CMD_EXIT:
                    return
                elif cmd == self.CMD_SCHEDULE:
                    (schedule_id, rate, offset, id, data) = data
                    assert rate > 0, "Scheduling rate must be >0"
                    assert offset < rate, "Scheduling offset must be < rate"
                    self.scheduled_transmits[schedule_id] = (rate, offset, id, data)
                elif cmd == self.CMD_UNSCHEDULE:
                    del self.scheduled_transmits[schedule_id]

            received_msgs = self.cantransfer.poll()
            for msg in received_msgs:
                self.output_queue.put((self.RAW_CAN, msg))
        print "stopped can thread"
        self.cantransfer.close()

class CanThread(CanThreadInternal):
    def __init__(self, path, command_queue, output_queue, log_path):
        CanThreadInternal.__init__(self, path, command_queue, output_queue, log_path)

    def schedule(self, schedule_id, rate, offset, id, data):
        self.command_queue.put((CanThread.CMD_SCHEDULE, (schedule_id, rate, offset, id, data)))

    def unschedule(self, schedule_id):
        self.command_queue.put((CanThread.CMD_UNSCHEDULE, (schedule_id,)))

    def send_can(self, canid, data):
        self.command_queue.put((CanThread.CMD_SEND_CAN, (canid, data)))

class LsgHandler:
    def handle_bap(self, lsg_id, fct_id, opcode):
        return []

def b(x):
    return x.decode('hex')

class Lsg43Handler(object):
    def __init__(self, screen_callback):
        self.f19_ = None
        self.f19_changed = False
        self.screen_callback = screen_callback

    @property
    def f19(self):
        return self.f19_
    
    @f19.setter
    def f19(self, value):
        self.f19_ = value
        self.f19_changed = True

    def handle_screen(self, data):
        print "SCREENDATA", data.encode('hex')
        screen_id = ord(data[0])
        if ord(data[3]) == 7:
            curline = 0
            s = data
            s = s[4:]

            if len(s) < 2:
                return

            Offset, ntoken = struct.unpack(">BB", s[:2])
            s = s[2:]

            res = []

            for i in range(ntoken):
                assert len(s) >= 3, "len correct %r" % s
                id, l = struct.unpack("<HB", s[:3])
                text = s[3:3+l]
                s = s[3+l:]

                text = text.replace("\0", "")
                res.append((i + Offset, id, text))
            
#            for i in range(4):
#                res.append((i + Offset + ntoken, 0, ""))
            self.screen_callback(0, screen_id, res)

        elif ord(data[3]) == 4:
            data = data[4:]
            Offset, Num = struct.unpack(">BB", data[:2])
            res = []
            for i in range(Num):
                res.append((i + Offset, ord(data[2 + i]), None))

            self.screen_callback(3, screen_id, res)
        else:
            print ">> UNKNOWN SCREEN; ", data

    def handle_bap(self, lsg_id, fct_id, opcode, data):
        res = []

        #if fct_id == 19:
        #    with open("f19log.txt", "a") as log:
        #        log.write("%d/%d/%d %s (FS)\n" % (lsg_id, fct_id, opcode, data.encode('hex')))

        if fct_id == 2 and opcode == 0:
            res.append((0x67C, 1, 43, 1, ""))

        if fct_id == 1 and opcode == 4: # GetAll changed
            res.append((0x67C, 2, 43, 16, b("0003")))

        if fct_id == 16 and opcode == 4:
            res.append((0x67C, 2, 43, 17, b("0100")))

        if fct_id == 17 and opcode == 4:
            self.f19 = b("ff00ff0000ff")
            res.append((0x67C, 2, 43, 18, b("0207080000000000")))

        if fct_id == 23 and opcode == 4:
            res.append((0x67C, 0, 43, 23, b("01")))

        if fct_id == 22 and opcode in [3,4]:
            self.screen_callback(1, ord(data[0]))
            self.screen_callback(2, ord(data[0]), data)

        #if fct_id == 23 and opcode in [3, 4]:
        #    res.append((0x67C, 0, 43, 23, data[0])) # opcode 0 or 4?

        if fct_id == 20 and opcode == 4:
            res.append((0x67C, 0, 43, 21, data[0]))
        #   self.f19 = data[0] + b("00000703ff")
            #res.append((0x67C, 2, 43, 19, self.f19))

        if fct_id == 19 and opcode == 4:
            flags = 3

            # FIXME: this needs to be done programatically.
            m = {
                    "0101000201": "01000701ff",
                    "0102000201": "01000701ff", # ?
                    "0103000201": "01000701ff", # ?
                    "0104000201": "01000701ff", # ?

                    "000000ff01": "00000701ff",
                    "010000ff01": "01000002ff",

                    "000007ff01": "00000701ff",

                    "000107ff00": "00000000ff",
                    "000207ff00": "00000000ff", #?
                    "000307ff00": "00000000ff", #?
                    "000407ff00": "00000000ff",

                    "00030701ff": "0003070101",

                    "0101070101": None,
                    "0102070101": None, #?
                    "0103070101": None, #?
                    "0104070101": None, #?
                    "0001070101": None,
                    "0002070101": None,  #?
                    "0003070101": None,  #?
                    "0004070101": None,
                    "0001000302": None,
                    "0000000000": None,
            }

            print "received", data.encode('hex')
            resp = m[data[1:].encode('hex')]

            if resp is not None:
                self.f19 = data[0] + resp.decode('hex')
            

        if fct_id == 20 and opcode == 4:
            self.handle_screen(data)

        if self.f19_changed:
            print "F19 changed!"
            res.append((0x67C, 2, 43, 19, self.f19))
            res.append((0x67C, 0, 43, 23, b("01")))
            #with open("f19log.txt", "a") as log:
            #    log.write("%d/%d/%d %s (KI)\n" % (43, 19, 2, self.f19.encode('hex')))
            self.f19_changed = False

        return res

class CanKiSim:
    def __init__(self, can_thread, screen_callback):
        self.can_thread = can_thread
        self.KL15 = False
        self.bap = Bap()
        self.bap_ids = [0x63B, 0x66F, 0x62D]
        self.bap_handlers = {}
        self.bap_handlers[43] = Lsg43Handler(screen_callback = screen_callback)

    def start(self):
        for schedule_id, rate, offset, id, data in [
          ("x661", 1, 0, 0x661, "8300000000000000"),
          ("x427", 1, 0, 0x427, "090100000000"),
          ("x436", 1, 0, 0x436, "1602050000000000"),
          ("x433", 1, 0, 0x433, "1501010100000000"),
          ("x65D", 1, 0, 0x65D, "5AF41AB170606B12"),
          ("x42B", 1, 0, 0x42B, "130100000000"),
          ("x653", 1, 0, 0x653, "8101a401"),
        #  ("x661", 1, 0, 0x575, "11200000"), # not important...
          ("x575", 1, 0, 0x575, "C7200000"),
          ("x2C1", 1, 0, 0x2c1, "00020d000200"),

          # evtl?
          ("x2A1", 1, 0, 0x2a1, "00C03102FFFF3F"),
          ("x2C3", 1, 0, 0x2c3, "07"),

          # VID
          ("VID0", 10, 0, 0x65f, "0000000000575657"),
          ("VID1", 10, 3, 0x65f, "015a5a5a374e4141"),
          ("VID2", 10, 6, 0x65f, "0241303030303030"),
        ]:
            self.can_thread.schedule(schedule_id, rate, offset, id, data.decode('hex'))

    def receive_can_transfer(self, id, data, timestamp):
        bapmsg = None
        bap_to_send = None
        if id in self.bap_ids:
            bapmsg = self.bap.receive_can(id, data)
            
            if bapmsg is not None:
                can_id, opcode, lsg_id, fct_id, bap_data = bapmsg
                if lsg_id in self.bap_handlers:
                    bap_to_send = self.bap_handlers[lsg_id].handle_bap(lsg_id, fct_id, opcode, bap_data)
                    if bap_to_send:
                        print "bap frames to send:", bap_to_send
                        for (can_id, opcode, lsg_id, fct_id, data) in bap_to_send:
                            can_frames = self.bap.send(can_id, opcode, lsg_id, fct_id, data)
                            print "can frames to send", can_frames
                            for (can_id, data) in can_frames:
                                self.can_thread.send_can(can_id, data)

        return bapmsg, (bap_to_send or [])

    def bap_key(self, code = 0):
        self.can_thread.send_can(0x5C1, chr(code) + b("000060"))

    def set_vid(self, vid):
        vid = (vid + " " * 17)[:17] 
        self.can_thread.schedule("VID0", 10, 0, 0x65f, b("0000000000") + vid[:3])
        self.can_thread.schedule("VID1", 10, 3, 0x65f, b("01") + vid[3:10]),
        self.can_thread.schedule("VID2", 10, 6, 0x65f, b("02") + vid[10:17]),

    def nav_set(self, nav):
        assert len(nav) == 8
        self.can_thread.schedule("GpsNav", 1, 0, 0x5A3, nav)

class KiSimMain(Window):
    def __init__(self, canusb_path, canlog_path):
        wpf.LoadComponent(self, 'KiSim.xaml')
        self.canusb_path = canusb_path
        self.canlog_path = canlog_path
        self.can_thread = None
        self.can_command_queue = Queue()
        self.can_output_queue = Queue()

        self.can_ki_sim = None

        self.can_messages = ObservableCollection[CanMessage]()
        self.can_messages_by_id = {}
        self.CanIdView.ItemsSource = self.can_messages

        self.bap_messages = ObservableCollection[BapMessage]()
        self.bap_messages_by_id = {}
        self.BapView.ItemsSource = self.bap_messages

        self.bap_all_messages = ObservableCollection[BapMessage]()
        self.BapLog.ItemsSource = self.bap_all_messages

        # init screens

        self.screens = {}
        self.screen_data = {}
        self.screen_tabs = {}
        for i in range(16):
            tabitem = TabItem()
            tabitem.Header = "%d" % i

            screen = TextBox()
            tabitem.AddChild(screen)
            self.ScreenTabControl.AddChild(tabitem)            
            self.screens[i] = screen
            self.screen_tabs[i] = tabitem
            self.screen_data[i] = {}

    def OnClosed(self, e):
        self.can_stop()
        Window.OnClosed(self, e)

    def MenuQuit_Click(self, sender, e):
        if MessageBox.Show("Do you really want to quit?", "Confirm", MessageBoxButton.YesNo, 
                           MessageBoxImage.Question):
            self.can_stop()
            Application.Current.Shutdown()

    def MenuAbout_Click(self, sender, e):
        form = About()
        form.Show()

    def MenuRun_Click(self, sender, e):
        self.can_start()
        self.can_poll_timer = DispatcherTimer()
        self.can_poll_timer.Interval = TimeSpan.FromMilliseconds(10)
        self.can_poll_timer.Tick += self.can_poll_timer_elapsed
        self.can_poll_timer.Start()

    def MenuStop_Click(self, sender, e):
        self.can_stop()
        self.can_poll_timer.Stop()

    def can_start(self):
        if self.can_thread is not None:
            return
        self.can_thread = CanThread(self.canusb_path, 
                                    self.can_command_queue, self.can_output_queue,
                                    self.canlog_path)
        self.can_thread.start()
        self.can_ki_sim = CanKiSim(self.can_thread, self.screen_callback)
        self.can_ki_sim.start()

    def can_stop(self):
        if self.can_thread is None:
            return
        print "putting exit into queue..."
        self.can_command_queue.put((CanThread.CMD_EXIT,()))
        print "joining..."
        self.can_thread.join()
        print "Done!"
        self.can_thread = None

    def log_bap_message(self, can_id, opcode, lsg_id, fct_id, bap_data, direction = False):
        bap_id = (can_id, lsg_id, fct_id)

        if bap_id in self.bap_messages_by_id:
            m = self.bap_messages_by_id[bap_id]
        else:
            m = BapMessage()
            m.CanId = "%03xh" % can_id
            m.FctId = fct_id
            m.LsgId = lsg_id
            self.bap_messages.Add(m)
            self.bap_messages_by_id[bap_id] = m

        m.Opcode = "%d" % opcode
        m.Data = bap_data
        m.Timestamp = time.strftime("%X")
        m.Direction = direction
        self.bap_all_messages.Add(copy(m))

    def can_poll_timer_elapsed(self, *e):
        while not self.can_output_queue.empty():
            type, message = self.can_output_queue.get()
            
            if type == CanThread.RAW_CAN:
                id, data, timestamp = message
                
                bapmsg, bap_send = self.can_ki_sim.receive_can_transfer(id, data, timestamp)

                if bapmsg:
                    m = None
                    can_id, opcode, lsg_id, fct_id, bap_data = bapmsg[0], bapmsg[1], bapmsg[2], bapmsg[3], bapmsg[4]
                    self.log_bap_message(can_id, opcode, lsg_id, fct_id, bap_data)
                    data_hex = "<BAP>"
                else:
                    data_hex = data.encode('hex')

                for bapmsg in bap_send:
                    self.log_bap_message(bapmsg[0], bapmsg[1], bapmsg[2], bapmsg[3], bapmsg[4], True)

                m = None

                if id in self.can_messages_by_id:
                    m = self.can_messages_by_id[id]
                else:
                    m = CanMessage()
                    m.Id = "%04x" % id
                    m.Count = 0
                    self.can_messages.Add(m)
                    self.can_messages_by_id[id] = m
                
                m.Message = data_hex
                m.Count += 1

        self.can_poll_timer.Start()
    
    def ButtonKL15_Checked(self, sender, e):
        self.ButtonKL15.Checked = not self.ButtonKL15.Checked 
        self.can_ki_sim.KL15 = self.ButtonKL15.Checked

    def bap_key(self, code):
        self.can_ki_sim.bap_key(code)
        self.can_ki_sim.bap_key(code)
        self.can_ki_sim.bap_key(0)

    def BapKeyOk(self, sender, e):
        self.bap_key(0x28)

    def BapKeyUp(self, sender, e):
        self.bap_key(0x22)

    def BapKeyDown(self, sender, e):
        self.bap_key(0x23)

    def BapKeyBack(self, sender, e):
        self.bap_key(0x29)

    def BapKeyVoice(self, sender, e):
        self.bap_key(0x2A)

    def screen_callback(self, action, screen_id, data = None):
        print "SCREEN_CALLBACK", action, screen_id, data
        if action in [0,3]:
#            if action == 0:
#                self.screen_data[screen_id] = {}
            for d in data:
                if len(d):
                    line, id, text = d

                    if action == 3:
                        text = self.screen_data[screen_id][line][1]
                        id = (self.screen_data[screen_id][line][0] &  0xFF) | (id << 8)
                    else:
                        text = text.decode("utf-8")
                        for str, desc in ki_icons:
                            text = text.replace(str, desc)

                    self.screen_data[screen_id][line] = (id, text)
            self.update_screen(screen_id)
        elif action == 1:
            self.ScreenTabControl.SelectedIndex = screen_id
        elif action == 2:
            self.screen_data[screen_id][13] = (0, data.encode('hex') + "HELLO")
            print "SCROLL DATA", data.encode('hex')
            scroll_visible = ord(data[2])
            scroll_invisible_top = ord(data[3])
            show_scrollbar = ord(data[0]) in [2, 3] # Not sure, could be data[1] == 02?
            
            self.KiScrollbar.Visibility = self.KiScrollbar.Visibility.Visible if show_scrollbar else self.KiScrollbar.Visibility.Hidden
            self.KiScrollbar.Minimum = 0
            self.KiScrollbar.ViewportSize = scroll_visible
            self.KiScrollbar.Value = scroll_invisible_top 
            self.KiScrollbar.Maximum = 100

    def update_screen(self, screen_id):
        res = ""
        vislines = []

        # FIXME: the screen layout is really not depending on the flags 
        # (like "left-aligned"), but rather the screen_id corresponds to
        # hardcoded screen layouts:
        # screen_id     Layout
        # 1             all centered
        # 2             1 line menu header (centered), 3 selections (left-aligned)
        # 3             2 line menu header (centered), 3 selections (left-aligned)
        # 4             3 line menu header (centered), 3 selections (left-aligned)
        # 5             full screen message
        # 6             like 1
        #

        for i in range(16):
            # 8000 - visible
            # 0100 - left-aligned
            # 0200 - arrow
            # 0004 - ??
            # 0002 - ??
            # 0a00 - ??

            flags, text = self.screen_data[screen_id].get(i, (0, ""))
            dflags = " "
            if flags & 0x200:
                dflags = ">"
            res += "%04x %s %s\n" % (flags, dflags, text)

            if flags & 0x8000 and len(vislines) < 4:
                vislines.append((flags, text))

        ui_ki_texts = [self.KiText0, self.KiText1, self.KiText2, self.KiText3]
        ui_ki_lines = [self.KiLine0, self.KiLine1, self.KiLine2, self.KiLine3, self.KiLine4]
        ui_ki_focus = [self.KiFocus0, self.KiFocus1, self.KiFocus2, self.KiFocus3]

        for i in range(4):
            ui_ki_lines[i].Visibility = ui_ki_lines[i].Visibility.Hidden
            ui_ki_lines[i+1].Visibility = ui_ki_lines[i].Visibility.Hidden

        for i in range(4):
            if len(vislines) <= i:
                ui_ki_texts[i].Content = ""
                continue

            ui_ki_texts[i].Content = vislines[i][1]

            if vislines[i][0] & 0x200:
                ui_ki_lines[i].Visibility = ui_ki_lines[i].Visibility.Visible
                ui_ki_lines[i+1].Visibility = ui_ki_lines[i].Visibility.Visible
                ui_ki_focus[i].Visibility = ui_ki_focus[i].Visibility.Visible
            else:
                ui_ki_focus[i].Visibility = ui_ki_focus[i].Visibility.Hidden

            if vislines[i][0] & 0x100:
                ui_ki_texts[i].HorizontalContentAlignment = \
                    ui_ki_texts[i].HorizontalContentAlignment.Left
            else:
                ui_ki_texts[i].HorizontalContentAlignment = \
                    ui_ki_texts[i].HorizontalContentAlignment.Center

        self.screens[screen_id].Text = res

    def VidChanged(self, sender, e):
        self.can_ki_sim.set_vid(self.VidTextbox.Text)

    def FctId19Set_Click(self, sender, e):
        try:
            self.can_ki_sim.bap_handlers[43].f19 = self.FctId19.Text.decode('hex')
        except:
            pass

        self.FctId19Get_Click(sender, e)

    def FctId19Get_Click(self, sender, e):
        self.FctId19.Text = self.can_ki_sim.bap_handlers[43].f19.encode('hex')

    def NavSet_Click(self, sender, e):
        self.can_ki_sim.nav_set(self.Nav.Text.decode('hex'))
    

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--canusb", help = "LAWICEL CANUSB device path (COMx usually)", 
                         required = True)
    parser.add_argument("--canlog", help = "CAN log output")
    args = parser.parse_args() 

    Application().Run(KiSimMain(args.canusb, args.canlog))
