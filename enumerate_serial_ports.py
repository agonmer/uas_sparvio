# Function available from PySerial 2.6
#Needed to make it possible to import is_64bit after packing with py2exe?
from serial.tools import list_ports


def enum_ports():
    usb_ports = list_ports.grep('FTDIBUS.*|USB.*')
    bt_ports = list_ports.grep('Standard Serial over Bluetooth link.*')
    def bt_filter(listportinfo):
        return ('BTHENUM' in listportinfo.hwid) and ('_PID' in listportinfo.hwid)
    bt_ports = [x for x in bt_ports if bt_filter(x)]
    ports = [port[0] for port in usb_ports]
    ports.extend([port[0] for port in bt_ports])
    return ports

def is_bluetooth_port(com_port):
    ports = list_ports.grep(com_port)
    ports = [x for x in ports]  #Remove iterator
    if not ports:
        return False
    return ports[0][1].startswith("Standard Serial over Bluetooth link")
