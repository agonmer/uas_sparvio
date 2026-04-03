# This is a rudimentary model of communication between two Sparvio
# processes on the same computer. Each process sends to one UDP port
# and listens on another port. These are manual arguments.

import socket
import time

from . import ssplink
from . import framing
from reactive.eventthread import EventThread
from .ssplink import Link

class _UdpRxThread(Link, EventThread):
    def __init__(self, rx_port, protocol):
        EventThread.__init__(self, "UdpRx(%d)" % rx_port)
        self.rx_port = rx_port
        self.protocol = protocol

    def start(self):
        self._rx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._rx_sock.bind(("127.0.0.1", self.rx_port))
        #Causes receiving to break 5 times per second, so the thread
        #can check _alive
        self._rx_sock.settimeout(0.2)
        return EventThread.start(self)

    def run(self):
        while self._alive:
            try:
                data, addr = self._rx_sock.recvfrom(1024) # Receive max 1024 bytes
                print("Received UDP packet %s from %s" % (repr(data), repr(addr)))
                # While it's expected that each received UDP packet
                # will be exactly one SSP message, in theory there can
                # be IP fragmentation into multiple packets (if the
                # message size is larger than the MTU of any IP link).
                # Therefore, use LineReader for SSP frame
                # reassembly. Still, in theory IP datagrams could
                # arrive non-ordered and interleaved with other
                # packets.
            except socket.timeout:
                continue  #Next iteration will start by checking _alive
            self.protocol.data_received(data)

class UdpLink(Link):
    def __init__(self, rx_port, tx_port, protocol_class,
                 link_id, componentbase = None):
        Link.__init__(self, componentbase=componentbase, link_id=link_id)
        assert rx_port != tx_port
        self._rx_port = rx_port
        self._tx_port = tx_port
        self.protocol = protocol_class(self.handle_message)

    def start(self):
        self._rx_thread = _UdpRxThread(self._rx_port, self.protocol).start()

    def handle_message(self, to, msg, timestamp=None):
        if timestamp is None:
            timestamp = time.time()
        if self.componentbase:
            self.componentbase.handle_message(self, to, msg, timestamp)
        else:
            print('UdpLink no componentbase')

    def stop(self):
        self._rx_thread.stop()
        self._rx_thread = None

    def send(self, to, msg):
        encoded = self.protocol.encode(to, msg)
        print('UDP sending %s to %d as %s' % (str(msg), to, repr(encoded)))
        self._rx_thread._rx_sock.sendto(encoded, ("127.0.0.1", self._tx_port))
