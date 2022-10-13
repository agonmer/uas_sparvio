#!/usr/bin/env python3

# upgrade.py: Flashes new firmware to the Sparvio component connected to SA1

import sys
if sys.version_info[0] < 3:
    raise Exception("Must be using Python 3")
    sys.exit(1)

import argparse
import signal
import math
import os
import time
import struct
import io
import traceback

import connect
from reactive import eventthread
#from sspt import parse
import dfufile
import app_ids

conn = None

#action = parser.add_mutually_exclusive_group(required = True)
#action.add_argument('--list', action='store_true', help='List available DfuSe interfaces')
#others = parser.add_argument_group('Other Options')
#others.add_argument('--force', '-f', action='store_true', help='Bypass sanity checks')

parser = argparse.ArgumentParser(description='Flashes new firmware to the Sparvio module connected to SA1. By default, uses the latest firmware available online.')
connect.add_default_arguments(parser)

parser.add_argument('--enter', choices=['already', 'soft', 'hard', 'auto'],
                    default='auto', help="Method of making the device enter bootloader")
#parser.add_argument('--start', action='store_true',
#                   help='Use when SA1 is already in DFU mode')
#parser.add_argument('--already', action='store_true',
#                   help='Use when the device is already in bootloader')

###### Actions
parser.add_argument('--write', type=str, metavar="FILE",
                    help='Writes a .dfu file to flash')
parser.add_argument('--writelatest', action='store_true',
                   help='Finds the latest version online and writes it if newer')
parser.add_argument('--only_enter', action='store_true',
                   help='Just makes the device enter the bootloader')
parser.add_argument('--readold', type=str, metavar="FILE",
                   help='Reads out the existing firmware to FILE')
parser.add_argument('--check', action='store_true',
                   help='Prints information about the current firmware')
parser.add_argument('--readeeprom', action='store_true',
                    help='Reads (emulated) EEPROM to eeprom_data.bin')
parser.add_argument('--writeeeprom', action='store_true',
                    help='Writes eeprom_data.bin to (emulated) EEPROM')
parser.add_argument('--cleareeprom', action='store_true',
                    help='Clears (emulated) EEPROM')

###### Action modifiers
parser.add_argument('--app', type=str, metavar="APP",
                    help='Uses a different application, for writelatest')
parser.add_argument('--force', action='store_true',
                   help='Writes also firmware with same or lower version number')
parser.add_argument('--verify', action='store_true',
                    help='Reads out the firmware after writing, verifying correctness')

###### General
parser.add_argument('--log', action='store_true',
                   help='Write the activity to devicelog.txt')
parser.add_argument('--note',
                   help='Optional note to add to the action log entry')
try:
    args = parser.parse_args()
except:
    print('Error parsing arguments')
    sys.exit(1)


import struct
class DfuDevice(object):
    """Handles a Sparvio device in bootloader mode, accessed via direct
       connection to SA1"""
    def __init__(self, sa1):
        self.sa1 = sa1

        #Filled in by read_info():
        self.bootloader_ver = None
        self.page_count = None
        self.page_size = None
        self.hw_model = None
        self.hw_rev = None
        self.appVersion = None
        self.app_id = None  #integer, where 0 = unspecified, 1 = default, ...

    def read_info(self):
        info = self.sa1.dfuReadDevInfo()
        # devInfo is the payload, stripped from the message header:
        # [0] = ver
        # [1:2] = page count
        # [3:4] = page size
        # [5..] = hw_model + ' ' + hw_version + '\0'
        print('Got %d byte devinfo %s' % (len(info), str(info)))
        if len(info) < 7:
            raise Exception("Unexpected info size %d. Is bootloader missing?" % len(info))
        (self.bootloader_ver, self.page_count, self.page_size) = struct.unpack("<BHH", info[:5])
        if (self.bootloader_ver == 0 or self.bootloader_ver > 10 or
            self.page_count > 1024 or \
            (self.page_size != 0x800 and self.page_size != 0x400)):
            print('Strange data', (self.bootloader_ver, self.page_count,
                                   self.page_size))
            raise Exception('It looks like a valid device is not connected')
        text = info[5:]
        zero_ix = text.find(0)
        if zero_ix == -1:
            raise Exception("No null byte found in dev info")
        text = text[:zero_ix].decode('ascii')
        parts = text.split(' ', 1)
        self.hw_model = parts[0]
        if len(parts) > 1:
            self.hw_rev = parts[1]

    def read_flash(self, addr, size):
        #Read in chunks of 16 bytes
        data = bytearray()
        while size > 0:
            part_size = min(size, 16)
            part_data = self.sa1.dfuReadMem(addr, part_size)
            if len(part_data) != part_size:
                print('Error: Read %d bytes, expected %d bytes: %s' % \
                    (len(part_data), part_size, repr(part_data)))
                raise Exception()
            data += part_data
            addr += part_size
            size -= part_size
        return data

    def verify_flash(self, addr, correct_data):
        """Compares data at <addr> with <correct_data>, returning False
           as soon as a mismatch is detected"""
        full_size = len(correct_data)
        while len(correct_data) > 0:
            part_size = min(len(correct_data), 16)
            cmd = [DfuDevice.DFU_CMD_READ, struct.pack("<I", addr), part_size]
            part_data = self.sa1.dfuReadMem(addr, part_size)
            if len(part_data) != part_size:
                raise Exception()
            if not correct_data.startswith(part_data):
                print('Mismatch around addr 0x%08X' % addr)
                return False
            addr += part_size
            correct_data = correct_data[part_size:]
            sys.stdout.write("\rVerified %.1f %%" % (100 * (full_size-len(correct_data)) / float(full_size)))
            sys.stdout.flush()
        print()
        return True

    def write_flash(self, addr, data, on_progress=None):
        #Write <data> in chunks of 64 bytes
        #The bootloader can handle 1K data, but any (future) intermediate
        #SSP nodes have limited buffer size
        written = 0
        while len(data) > 0:
            part_size = min(len(data), 64)
            part_data = data[:part_size]
            try:
                self.sa1.dfuWriteMem(addr, part_data)
            except Exception as ex:
                #print('Unexpected reply to write:', repr(result))
                raise Exception('Unexpected write result: ' + str(ex))
            data = data[part_size:]
            addr += part_size
            written += part_size
            if on_progress:
                on_progress(written)

    def read_all_to_file(self, filename):
        f = open(filename, 'wb')
        addr = self.get_start_address()
        size = self.get_user_page_count() * self.page_size
        #TODO: When appSize is implemented in appInfo, use that instead
        print('Reading whole flash start=0x%08X size=%d B to %s' % (addr, size, filename))
        f.write(self.read_flash(addr, size))
        f.close()
        print('Done reading to', filename)

    def read_config(self):
        start_address = self.get_start_address()
        if start_address is None:
            raise Exception()
        #uint32 Checksum, uint32 appVersion, uint32 size, uint32 reserved
        binary = self.read_flash(start_address + 192, 16)
        binary = binary[:16]
        (checksum, appVersion, size, app_id) = struct.unpack("<IIII", binary)
        if app_id == 0xFFFFFFFF or appVersion == 0xFFFFFFFF:
            #The numbers are not even programmed into flash
            app_id = 0
            appVersion = 0
        self.appVersion = appVersion
        self.app_id = app_id
        return (checksum, size)

    def read_stm32f0_serial(self):
        a = self.read_flash(0x1FFFF7AC, 4)
        return "%X" % struct.unpack('<I', a)[0]
        #return '0x' + ''.join("%02X" % ord(c) for c in a)

    def get_loginfo(self):
        serial = self.read_stm32f0_serial()
        (checksum, size) = self.read_config()

        loginfo = {'pageCount': self.page_count,
                   'pageSize': self.page_size,
                   'BL': self.bootloader_ver,
                   'hwModel': self.hw_model,
                   'hwRev': self.hw_rev,
                   'serial': serial,
                   'crc': checksum,
                   'appVer': self.appVersion,
                   'appSize': size,
                   'appId': self.app_id}
        return loginfo

    def erase_pages(self, start_address, page_count):
        """Returns true if SA1 reports success (queried from the device).
           The device will still erase pages after return so the caller must wait."""
        try:
            #Arguments: uint32 startAddress, uint16 pageCount
            self.sa1.dfuEraseMem(start_address, page_count)
        except:
            return False
        time.sleep(0.1)
        return True

    def get_start_address(self):
        "Start address of application code (including interrupt vector and info)"
        if self.page_size == 0x400:
            return 0x08001400
        elif self.page_size == 0x800:
            return 0x08001800
        else:
            return None

    def get_user_page_count(self):
        "The number of pages usable for application, including trailing EEPROM emulation"
        if self.page_count is None:
            return None
        if self.page_size == 0x400:
            #Five pages (1KB * 5) used by bootloader
            return self.page_count - 5
        elif self.page_size == 0x800:
            #Three pages (2KB * 3) used by bootloader
            return self.page_count - 3
        else:
            return None

    def erase_device(self):
        "Saves the EEPROM contents"
        start_address = self.get_start_address()
        if start_address is None or self.get_user_page_count() is None:
            raise Exception("Did not get valid metadata from the device")
        #The last two pages are used for EEPROM emulation so don't erase them
        page_count = self.get_user_page_count() - 2
        if self.erase_pages(start_address, page_count):
            #Erasing started
            print('Erasing old flash... (takes 15 sec)')
            time.sleep(15)
        else:
            print('Erasing failed')
            raise Exception()

    def get_eeprom_address_and_page_count(self):
        "Returns (address, page_count) for flash area emulating EEPROM"
        if self.page_size is None:
            raise Exception("Not inited")
        address = self.get_start_address()
        address += self.page_size * (self.get_user_page_count() - 2)
        return (address, 2)

    def leave_dfu(self):
        "Only makes SA1 leave DFU master mode. Doesn't affect the connected device."
        self.sa1.dfuMaster = False

    def start_application(self):
        "Also leaves SA1 DFU mode"
        self.sa1.dfuExit()


def print_loginfo(loginfo):
    flash_size = loginfo['pageCount'] * loginfo['pageSize']
    print('MCU flash size: %d B (%d pages of %d B) minus bootloader and EEPROM area' % \
        (flash_size, loginfo['pageCount'], loginfo['pageSize']))
    print('Device bootloader ver:', loginfo['BL'])
    print('Device HW model:', loginfo['hwModel'])
    print('Device HW revision:', loginfo['hwRev'])
    print('Device serial number:', loginfo['serial'])
    appName = app_ids.id_to_long_name(loginfo['appId'])
    if appName is None:
        appName = '?'
    print('Application id: %s (%d)' % (appName, loginfo['appId']))
    if loginfo['crc'] == 0:
        checksum = "?"
    else:
        checksum = '0x%04X' % loginfo['crc']
    print('Application checksum:', checksum)
    if loginfo['appVer'] == 0 or loginfo['appVer'] == 0xFFFFFFFF:
        appVersion = "?"
    else:
        appVersion = loginfo['appVer']
    print('Application version:', appVersion)
    if loginfo['appSize'] == 0 or loginfo['appSize'] == 0xFFFFFFFF:
        size = '?'
    else:
        size = loginfo['appSize']
    print('Application size:', size)
    if loginfo['appVer'] == 0xFFFFFFFF and loginfo['appSize'] == 0xFFFFFFFF:
        print('Error: No application detected')
    elif loginfo['appSize'] > flash_size:
        print('Error: Invalid application size reported')

def get_latest_fw_version(hw_model, hw_rev, app_id):
    "Returns (version, url) or None"
    dir_name = hw_model.lower()
    #if app_id != 0 and app_id != 1:
    #    dir_name += ("_%d" % app_id)
    url = "http://sparv.io/fw/%s/latest" % dir_name
    import urllib.request, urllib.error, urllib.parse
    try:
        response = urllib.request.urlopen(url)
    #except urllib2.URLError as error:
    #    #Internet not available
    #    print error
    #    return None
    except urllib.error.HTTPError as error:
        #"Not found"
        print('Could not download %s. Reason: %s' % (url, error))
        return None
    contents = response.read().decode("ascii")
    for line in contents.split('\n'):
        parts = [x.strip() for x in line.split(',')]
        if len(parts) != 4:
            continue
        if parts[0].lower() == (hw_model + ' ' + str(hw_rev)).lower():
            id_str = parts[1].strip()
            if id_str != str(app_id) and id_str != '0' and app_id != 0:
                continue
            version = parts[2]
            url = parts[3]
            #TODO: Check if URL is relative dir and resolve
            return (version, url)
    return None

def list_all_apps(hw_model, hw_rev):
    "Returns list of app ids"
    dir_name = hw_model.lower()
    url = "http://sparv.io/fw/%s/latest" % dir_name
    import urllib.request, urllib.error, urllib.parse
    try:
        response = urllib.request.urlopen(url)
    #except urllib2.URLError as error:
    #    #Internet not available
    #    print error
    #    return None
    except urllib.error.HTTPError as error:
        #"Not found"
        print('Could not download %s. Reason: %s' % (url, error))
        return None
    contents = response.read()
    apps = []
    print(hw_model, hw_rev)
    for line in contents.split('\n'):
        print(repr(line))
        parts = [x.strip() for x in line.split(',')]
        if len(parts) != 4:
            continue
        if parts[0].lower() == (hw_model + ' ' + str(hw_rev)).lower():
            _id = int(parts[1].strip())
            if not _id in apps:
                apps.append(_id)
    return apps

size = 0
def on_write_progress(written):
    sys.stdout.write("\rWrote %.1f %%" % (100 * written / float(size)))
    sys.stdout.flush()


######################################################################

def find_device(sa1):
    "Returns the OID of the SSP device connected to SA1"
    neighbors = sa1.neig
    for neighbor in neighbors:
        if neighbor == vis.id:
            continue
        return neighbor
    return None

def enter_bootloader_soft(sa1):
    "Returns true if successful"
    if sa1.dfuMaster:
        # Exit DFU mode to check for connected device. Unclear if this will work...
        print("Exiting DFU mode to try soft bootloader entry")
        sa1.dfuMaster = False

    time.sleep(2)  #Necessary?
    oid = find_device(sa1)
    if oid is None:
        print("Wait for dynamic remoteobject to initialize")
        time.sleep(2)
        oid = find_device(sa1)
    if oid is None:
        #print("SSP device not online")
        return False
    #print('Device id is ', oid)
    device = vis.get_object(oid)
    #print('device', device)
    if device is None:
        return False
    #print('dir(device)', dir(device))
    if 'enterBl' in dir(device) and callable(device.enterBl):
        # S2 doesn't implement sending the reply before entering
        # bootloader, so don't do regular call()
        device._proxy.call_oneway('enterBl') #The network may go offline here
        sa1.dfuMaster = True
        time.sleep(0.1)  #Wait for device to enter bootloader
        return True
    print("SSP device doesn't support soft bootloader entry")
    return False

max_acceptable_voltage = 3.0  #was 2.5, but pullup on I2C lines registers too
def enter_bootloader_hard(sa1):
    """Make the device connected to SA1 enter bootloader by turning off
       power and then turning on power with I2C SDA and SCL held
       low. This depends only on the device bootloader and not the
       device application, but only works when the device is powered
       through SA1 (not battery). Returns true if successful.
    """
    #Turn off voltage output, then check voltage.
    if True:  #sa1.extPwr != 0:
        print('Turning off power to the device')
        sa1.extPwr = 0
        #Voltage decreases during a couple of seconds after turning off power
        for i in range(30):
            bat = sa1.bat
            if args.verbose >= 1:
                print('V: %.2f' % bat)
            if bat < 1: #max_acceptable_voltage:
                break
            time.sleep(0.2)

    bat = sa1.bat
    if bat is None:
        print("Could not read supply line voltage; won't do hard bootloader entry")
        return False
    if bat > max_acceptable_voltage:
        print('Supply line voltage: %.3f V' % bat)
        print("ERROR: Device is not using power from SA1. Won't do hard bootloader entry.")
        return False
    if args.verbose >= 1:
        print('Supply line voltage: %.3f V' % bat)

    sa1._proxy.call('dfuMasterEnter', timeout=4)
    return True

def check_if_in_bootloader(sa1):
    if not sa1.dfuMaster:
        sa1.dfuMaster = 1  # Just make SA1 enter DFU mode
    try:
        # This creates a duplicate DfuDevice() and checks twice. This
        # overhead doesn't matter.
        dfu = DfuDevice(sa1)
        dfu.read_info()
    except:
        return False
    return True

def main(args):
    #sparvio.print_messages = (args.verbose >= 3)
    if len(vis._base.links) == 0:
        print("Error: No link to SA1")
        return
    link = vis._base.links[0]  #Assumes the first link is the one
    if not link.is_online():
        print("Error: SA1 not online")
        return
    sa1 = vis.add_link_component(link)
    #time.sleep(1.5)  #Time to fetch variables and functions

    main_sa1(args, sa1)
    # Always leave SA1 in normal mode
    sa1.dfuMaster = False

def main_sa1(args, sa1):
    ##################################################
    # Putting SA1 into DFU mode and S2 into bootloader

    # 1. SA1 already in DFU mode
    # 2. SA1 in normal mode

    # A. S2 already in bootloader - Set SA1 in DFU and try getInfo
    # B. soft enter - send SSP command enterBl()
    # C. hard enter (power cycle) - forbidden if external power
    # Automatic: D1. If device is present and device.enterBl is present, use soft (B)
    #            D2. If device is not present, it may already be in bootloader;
    #                try A
    #            D3. Try hard enter (C)
    if args.enter == 'auto':
        # Find the most suitable way to make the device enter bootloader
        # All branches will leave SA1 in DFU mode (if bootloader entry was successful)
        if not enter_bootloader_soft(sa1):
            if not check_if_in_bootloader(sa1):
                if not enter_bootloader_hard(sa1):
                    print("Error: Failed to put device in bootloader mode")
                    return
    elif args.enter == 'soft':
        if not enter_bootloader_soft(sa1):
            print("Error: Failed to do soft bootloader entry")
            return
    elif args.enter == 'hard':
        if not enter_bootloader_hard(sa1):
            print("Error: Failed to do hard bootloader entry")
            return
    elif args.enter == 'already':
        if not check_if_in_bootloader(sa1):
            print("Error: Failed to find a device in bootloader mode")
            return
    else:
        print("Error: Invalid 'enter' option")
        return

    ##############################
    # Check device in bootloader

    global dfu
    global size
    dfu = DfuDevice(sa1)

    try:
        dfu.read_info()
    except Exception as ex:
        print('No connected device detected (%s)' % ex)
        dfu.leave_dfu()
        return

    if args.only_enter:
        dfu.leave_dfu()
        print('Only made device enter DFU mode.')
        #print 'Only made SA1 and device enter DFU mode. Finished.'
        return

    if args.check:
        loginfo = dfu.get_loginfo()
        print_loginfo(loginfo)

    if args.readold:
        dfu.read_all_to_file(args.readold)

    if args.readeeprom:
        (addr, page_count) = dfu.get_eeprom_address_and_page_count()
        size = page_count * dfu.page_size
        eeprom_data = dfu.read_flash(addr, size)
        f = open('eeprom_data.bin', 'wb')
        f.write(eeprom_data)
        f.close()
        print('Has read to eeprom_data.bin')

    if args.cleareeprom or args.writeeeprom:
        (addr, page_count) = dfu.get_eeprom_address_and_page_count()
        size = page_count * dfu.page_size
        dfu.erase_pages(addr, page_count)

    if args.writeeeprom:
        eeprom_data = dfu.read_flash(addr, size)
        f = open('eeprom_data.bin', 'rb')
        eeprom_data = f.read()
        f.close()
        dfu.write_flash(addr, eeprom_data)
        print('Has written eeprom_data.bin (%d bytes)' % len(eeprom_data))

    dfu_handle = None   #An open file handle
    dfu_filename = None  #Reported to user as source of dfu_handle
    dfu_url = None  #Used if DFU file should be downloaded

    dfu.read_config()

    if args.app == '?':
        apps = list_all_apps(dfu.hw_model, dfu.hw_rev)
        if len(apps) == 0:
            print('No available apps')
        else:
            print('Available apps:')
            for app in apps:
                print('  %d: %s' % (app, app_ids.id_to_long_name(app)))
        restore(dfu)
        return

    if args.writelatest:
        if dfu.hw_model is None:
            print('No hardware information could be read from the device')
            restore(dfu)
            return
        if args.app is not None:
            app = app_ids.deduce_id(args.app)
            if app is None:
                print("Error: No app matching argument %s found" % args.app)
                restore(dfu)
                return
        else:
            app = dfu.app_id
        print('Finding latest firmware online for %s %s %d...' % (dfu.hw_model, dfu.hw_rev, app))
        import traceback
        try:
            (new_appRev, url) = get_latest_fw_version(dfu.hw_model, dfu.hw_rev, app)
        except Exception as ex:
            print('Error finding latest firmware version online for %s %s %d' %\
                (dfu.hw_model, dfu.hw_rev, app))
            print(ex)
            traceback.print_exc()
            restore(dfu)
            return

        #Only check versions if staying with the same app
        if app == dfu.app_id or app == 0 or dfu.app_id == 0:
            if dfu.appVersion is None or dfu.appVersion == 0:
                print('No version stored in current firmware')
            elif float(new_appRev) <= dfu.appVersion:
                if args.force:
                    print('Forcing write of version %s over current %s' % \
                        (str(new_appRev), str(dfu.appVersion)))
                else:
                    print('No newer version (currently at %s)' % \
                        str(dfu.appVersion))
                    restore(dfu)
                    return

        dfu_url = url

    elif args.write:
        if args.write.startswith("http:") or args.write.startswith("https:"):
            dfu_url = args.write
        elif os.path.exists(args.write):
            try:
                dfu_handle = open(args.write, 'rb')
            except:
                print('Could not open file', args.write)
                restore(dfu)
                return
            dfu_filename = os.path.split(args.write)[-1]
        else:
            print('Could not find file', args.write)
            restore(dfu)
            return

    ###########################
    # Done processing arguments

    if dfu_url:
        import urllib.request, urllib.error, urllib.parse
        print('Downloading firmware', dfu_url)
        start = time.time()
        response = urllib.request.urlopen(dfu_url)
        contents = response.read()
        if args.verbose >= 1:
            print('Downloaded file of size %d B in %.2f sec' % \
                (len(contents), time.time() - start))
        dfu_handle = io.BytesIO(contents)
        if dfu_filename is None:
            dfu_filename = dfu_url

    if dfu_handle:
        f = dfufile.DfuFile(dfu_handle)
        if args.verbose >= 1:
            print('File %s:' % dfu_filename)
            print('  fwVersion:', repr(f.devInfo['fwVersion']))
            #print '  Targets:', len(f.targets)
            for i, target in enumerate(f.targets):
                print('  Target %d:' % i)
                print('    Name: %s' % target['name'])
                print('    Alternate: %s' % repr(target['alternate']))
                print('    Size:', [len(e['data']) for e in target['elements']])
        dfu.erase_device()
        #TODO: Select compatible target
        target = f.targets[0]
        #TODO: Check if same major version. If not, erase EEPROM as
        #symbols index could have changed
        for element in target['elements']:
            print('Writing %d bytes at 0x%08X' % (len(element['data']), element['address']))
            size = len(element['data'])  #Used in callback
            dfu.write_flash(element['address'], element['data'], on_write_progress)
            print()
        if args.verify:
            for element in target['elements']:
                print('Verifying %d bytes at 0x%08X' % (len(element['data']), element['address']))
                verified = dfu.verify_flash(element['address'], element['data'])
                if verified:
                    print('Verification complete')
                else:
                    print('VERIFICATION MISMATCH')
                    break

        if args.log:
            time.sleep(0.1)
            loginfo = dfu.get_loginfo()
            t = time.gmtime()
            loginfo['utc'] = "%i-%02i-%02i %02d:%02d:%02d" % (t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec)
            loginfo['action'] = 'flash'
            loginfo['file'] = dfu_filename
            if args.note:
                loginfo['note'] = args.note
            if args.verify:
                loginfo['verified'] = verified
            log = open("devicelog.txt", 'a')
            log.write(repr(loginfo) + '\n')
            log.close()
            print('Logged the action')

        dfu_handle.close()
        time.sleep(0.1)
        print('Success upgrading firmware!')

    if not sys.flags.interactive:
        restore(dfu)

def restore(dfu):
        dfu.start_application()
        time.sleep(0.5)

if __name__ == "__main__":
    config = connect.get_config("config_interactive.py", args)
    config['web_hostname'] = None
    config['influx_host'] = None
    config['grafana_port'] = None
    try:
        vis = connect.launch(config)
    except connect.TerminateException:
        # Handled error. No additional message.
        eventthread.stop()
        sys.exit(1)

    if args.note:
        args.log = True

    if args.write or args.writelatest or args.only_enter or args.check or \
       args.readeeprom or args.writeeeprom or args.ports:
        pass
    else:
        #Default action:
        args.writelatest = True

    try:
        main(args)
    except connect.TerminateException:
        pass  # Handled error. No additional message.
    except:
        print('Caught exception:')
        print(traceback.print_exc())

    if not sys.flags.interactive:
        eventthread.stop()
