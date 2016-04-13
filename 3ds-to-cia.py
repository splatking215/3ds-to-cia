#!/usr/bin/env python2

#####
#ncchinfo.bin format
#
#4 bytes = 0xFFFFFFFF Meant to prevent previous versions of padgen from using these new files
#4 bytes   ncchinfo.bin version or'd with 0xF0000000, to prevent previous versions of padgen from using these new files
#4 bytes   Number of entries
#4 bytes   Reserved
#
#entry (168 bytes in size):
#  16 bytes   Counter
#  16 bytes   KeyY
#   4 bytes   Size in MB(rounded up)
#   4 bytes   Reserved
#   4 bytes   Uses 9x SeedCrypto (0 or 1)
#   4 bytes   Uses 7x crypto? (0 or 1)
#   8 bytes   Title ID
# 112 bytes   Output file name in UTF-8 (format used: "/titleId.CRC32.partitionName.sectionName.xorpad")
#####

import os
import sys
import glob
import struct
from ctypes import *

import zipfile
import tempfile
import shutil
import binascii
import re

import hashlib
import subprocess
import platform
import stat

# pip install colorama
import colorama

# Taked from ncchinfo_gen_exh.py (https://github.com/d0k3/Decrypt9WIP)
mediaUnitSize = 0x200

class ncchHdr(Structure):
    _fields_ = [
        ('signature', c_uint8 * 0x100),
        ('magic', c_char * 4),
        ('ncchSize', c_uint32),
        ('titleId', c_uint8 * 0x8),
        ('makerCode', c_uint16),
        ('formatVersion', c_uint8),
        ('formatVersion2', c_uint8),
        ('padding0', c_uint32),
        ('programId', c_uint8 * 0x8),
        ('padding1', c_uint8 * 0x10),
        ('logoHash', c_uint8 * 0x20),
        ('productCode', c_uint8 * 0x10),
        ('exhdrHash', c_uint8 * 0x20),
        ('exhdrSize', c_uint32),
        ('padding2', c_uint32),
        ('flags', c_uint8 * 0x8),
        ('plainRegionOffset', c_uint32),
        ('plainRegionSize', c_uint32),
        ('logoOffset', c_uint32),
        ('logoSize', c_uint32),
        ('exefsOffset', c_uint32),
        ('exefsSize', c_uint32),
        ('exefsHashSize', c_uint32),
        ('padding4', c_uint32),
        ('romfsOffset', c_uint32),
        ('romfsSize', c_uint32),
        ('romfsHashSize', c_uint32),
        ('padding5', c_uint32),
        ('exefsHash', c_uint8 * 0x20),
        ('romfsHash', c_uint8 * 0x20),
    ]

class ncchSection:
    exheader = 1
    exefs = 2
    romfs = 3

class ncch_offsetsize(Structure):
    _fields_ = [
        ('offset', c_uint32),
        ('size', c_uint32),
    ]

class ncsdHdr(Structure):
    _fields_ = [
        ('signature', c_uint8 * 0x100),
        ('magic', c_char * 4),
        ('mediaSize', c_uint32),
        ('titleId', c_uint8 * 0x8),
        ('padding0', c_uint8 * 0x10),
        ('offset_sizeTable', ncch_offsetsize * 0x8),
        ('padding1', c_uint8 * 0x28),
        ('flags', c_uint8 * 0x8),
        ('ncchIdTable', c_uint8 * 0x40),
        ('padding2', c_uint8 * 0x30),
    ]

ncsdPartitions = [b'Main', b'Manual', b'DownloadPlay', b'Partition4', b'Partition5', b'Partition6', b'Partition7', b'UpdateData']

def reverseCtypeArray(ctypeArray): #Reverses a ctype array and converts it to a hex string.
    return ''.join('%02X' % x for x in ctypeArray[::-1])
    #Is there a better way to do this?

def ncchinfo_gen(files):
    def roundUp(numToRound, multiple):  #From http://stackoverflow.com/a/3407254
        if (multiple == 0):
            return numToRound

        remainder = abs(numToRound) % multiple
        if (remainder == 0):
            return numToRound
        if (numToRound < 0):
            return -(abs(numToRound) - remainder)
        return numToRound + multiple - remainder

    def getNcchAesCounter(header, type): #Function based on code from ctrtool's source: https://github.com/Relys/Project_CTR
        counter = bytearray(b'\x00' * 16)
        if header.formatVersion == 2 or header.formatVersion == 0:
            counter[:8] = bytearray(header.titleId[::-1])
            counter[8:9] = chr(type)
        elif header.formatVersion == 1:
            x = 0
            if type == ncchSection.exheader:
                x = 0x200 #ExHeader is always 0x200 bytes into the NCCH
            if type == ncchSection.exefs:
                x = header.exefsOffset * mediaUnitSize
            if type == ncchSection.romfs:
                x = header.romfsOffset * mediaUnitSize
            counter[:8] = bytearray(header.titleId)
            for i in xrange(4):
                counter[12+i] = chr((x>>((3-i)*8)) & 0xFF)

        return bytes(counter)

    def parseNCSD(fh, crc32):
        print 'Parsing NCSD in file "%s":' % os.path.basename(fh.name)
        entries = 0
        data = ''

        fh.seek(0)
        header = ncsdHdr()
        fh.readinto(header) #Reads header into structure

        for i in xrange(len(header.offset_sizeTable)):
            if header.offset_sizeTable[i].offset:
                result = parseNCCH(fh, crc32, header.offset_sizeTable[i].offset * mediaUnitSize, i, reverseCtypeArray(header.titleId), 0)
                entries += result[0]
                data = data + result[1]
        return [entries, data]

    def parseNCCH(fh, crc32, offs=0, idx=0, titleId='', standAlone=1):
        tab = '    ' if not standAlone else '  '
        if not standAlone:
            print '  Parsing %s NCCH' % ncsdPartitions[idx]
        else:
            print 'Parsing NCCH in file "%s":' % os.path.basename(fh.name)
        entries = 0
        data = ''

        fh.seek(offs)
        header = ncchHdr()
        fh.readinto(header) #Reads header into structure

        if titleId == '':
            titleId = reverseCtypeArray(header.titleId)

        keyY = bytearray(header.signature[:16])

        if not standAlone:
            print tab + 'NCCH Offset: %08X' % offs
        print tab + 'Product code: ' + str(bytearray(header.productCode)).rstrip('\x00')
        if not standAlone:
            print tab + 'Partition number: %d' % idx
        print tab + 'KeyY: %s' % binascii.hexlify(keyY).upper()
        print tab + 'Title ID: %s' % reverseCtypeArray(header.titleId)
        print tab + 'Format version: %d' % header.formatVersion

        fixed_key_flag = 0
        ncchFlag7 = bytearray(header.flags)[7]
        if ncchFlag7 == 0x1:
            fixed_key_flag = ncchFlag7
            print tab + 'Uses fixed crypto key'

        print ''

        if header.exhdrSize:
            data = data + parseNCCHSection(header, ncchSection.exheader, 0, fixed_key_flag, 1, tab)
            data = data + genOutName(titleId, crc32, ncsdPartitions[idx], b'exheader')
            entries += 1
            print ''

        print ''

        return [entries, data]

    def parseNCCHSection(header, type, ncchFlag3, ncchFlag7, doPrint, tab):
        if type == ncchSection.exheader:
            sectionName = 'ExHeader'
            offset = 0x200 #Always 0x200
            sectionSize = header.exhdrSize
        elif type == ncchSection.exefs:
            sectionName = 'ExeFS'
            offset = header.exefsOffset * mediaUnitSize
            sectionSize = header.exefsSize * mediaUnitSize
        elif type == ncchSection.romfs:
            sectionName = 'RomFS'
            offset = header.romfsOffset * mediaUnitSize
            sectionSize = header.romfsSize * mediaUnitSize
        else:
            print 'Invalid NCCH section type was somehow passed in. :/'
            sys.exit()

        counter = getNcchAesCounter(header, type)
        keyY = bytearray(header.signature[:16])
        titleId = struct.unpack('<Q',(bytearray(header.programId[:8])))[0]

        sectionMb = roundUp(sectionSize, 1024*1024) / (1024*1024)
        if sectionMb == 0:
            sectionMb = 1 #Should never happen, but meh.

        if doPrint:
            print tab + '%s offset:  %08X' % (sectionName, offset)
            print tab + '%s counter: %s' % (sectionName, binascii.hexlify(counter))
            print tab + '%s bytes: %d' % (sectionName, sectionSize)
            print tab + '%s Megabytes(rounded up): %d' % (sectionName, sectionMb)

        return struct.pack('<16s16sIIIIQ', str(counter), str(keyY), sectionMb, 0, ncchFlag7, ncchFlag3, titleId)

    def genOutName(titleId, crc32, partitionName, sectionName):
        outName = b'/%s.%08lx.%s.%s.xorpad' % (titleId, crc32, partitionName, sectionName)
        if len(outName) > 112:
            print "Output file name too large. This shouldn't happen."
            sys.exit()

        return outName + (b'\x00'*(112-len(outName))) #Pad out so whole entry is 160 bytes (48 bytes are set before filename)

    print ''

    entries = 0
    data = ''

    for file in files:
        result = []
        filename, crc32 = file

        with open(filename,'rb') as fh:
            fh.seek(0x100)
            magic = fh.read(4)
            if magic == b'NCSD':
                result = parseNCSD(fh, crc32)
                print ''
            elif magic == b'NCCH':
                result = parseNCCH(fh, crc32)
                print ''

        if result:
            entries += result[0]
            data = data + result[1]

    with open('ncchinfo.bin', 'wb') as fh:
        fh.write(struct.pack('<IIII', 0xFFFFFFFF, 0xF0000004, entries, 0))
        fh.write(data)

    print 'Done!'

# Apply a xorpad
def xor(bytes, xorpad):
    if len(bytes) > len(xorpad):
        raise Exception("xorpad is too small")

    result = b""
    for x in range(len(bytes)):
        result += struct.pack("B", bytes[x] ^ xorpad[x])
    return bytearray(result)

# Calculate the sha256 of a string
def sha256(s):
    h = hashlib.sha256()
    h.update(s)
    return h.digest()

# Verify is the xorpad is the correct one
def verify_xorpad(filename, xorpad_file):
    with open(filename, "rb") as fh:
        offset = 0
        fh.seek(0x100)
        magic = fh.read(4)
        if magic == b'NCSD':
            fh.seek(0)
            header = ncsdHdr()
            fh.readinto(header) #Reads header into structure
            for i in xrange(len(header.offset_sizeTable)):
                if header.offset_sizeTable[i].offset:
                    offset = header.offset_sizeTable[i].offset * \
                        mediaUnitSize
                    break

        xorpad = bytearray(open(xorpad_file, "rb").read(0x400))
        # get exheader
        fh.seek(offset + 0x200)
        exheader = bytearray(fh.read(0x400))
        # decrypt exheader
        exheader = xor(exheader, xorpad)
        # verify exheader sha256sum
        fh.seek(offset + 0x160)
        orig_sha256 = fh.read(0x20)
        return sha256(exheader) == orig_sha256

# Set SD flag in exheader and updates SHA256 in CXI
def fix_cxi(filename, xorpad_file):
    f = open(filename, "r+b")
    xorpad = bytearray(open(xorpad_file, "rb").read(0x400))
    # get exheader
    f.seek(0x200)
    exheader = bytearray(f.read(0x400))
    # decrypt exheader
    exheader = xor(exheader, xorpad)
    # set sd flag in exheader
    exh_flags = exheader[0xD]
    exh_flags = exh_flags | 2
    exheader = exheader[:0xD] + struct.pack("B", exh_flags) + exheader[0xE:]
    # write back modified exheader
    f.seek(0x200)
    f.write(xor(exheader, xorpad))
    # reset the hash
    f.seek(0x160)
    f.write(sha256(exheader))

# Fix save data size in CIA
def fix_cia(file, xorpad_file):
    f = open(file, "r+b")
    xorpad = bytearray(open(xorpad_file, "rb").read(0x400))

    def roundup(x, y):
        x = int(x)
        y = int(y)
        m = x % y
        return x if m == 0 else (x - m + y)

    # first locate cxi & exheader in the cia file
    header_size = struct.unpack('<I', f.read(4))[0]
    f.seek(0x08)
    cert_size = struct.unpack('<I', f.read(4))[0]
    f.seek(0x0C)
    ticket_size = struct.unpack('<I', f.read(4))[0]
    f.seek(0x10)
    tmd_size = struct.unpack('<I', f.read(4))[0]
    cxi_ofs = roundup(header_size, 0x40) + roundup(cert_size, 0x40) + roundup(ticket_size, 0x40) + roundup(tmd_size, 0x40)
    exh_ofs = cxi_ofs + 0x200
    # extract exheader
    f.seek(exh_ofs, 0)
    exheader = bytearray(f.read(0x400))
    # decrypt exheader
    exheader = xor(exheader, xorpad)
    # locate save data size in tmd
    tmd_ofs = roundup(header_size, 0x40) + roundup(cert_size, 0x40) + roundup(ticket_size, 0x40)
    f.seek(tmd_ofs)
    tmd_sig_type = struct.unpack('>I', f.read(4))[0]
    if tmd_sig_type == 0x010000:
        tmd_hdr_ofs = tmd_ofs + 0x240
    elif tmd_sig_type == 0x010001:
        tmd_hdr_ofs = tmd_ofs + 0x140
    elif tmd_sig_type == 0x010002:
        tmd_hdr_ofs = tmd_ofs + 0x80
    elif tmd_sig_type == 0x010003:
        tmd_hdr_ofs = tmd_ofs + 0x240
    elif tmd_sig_type == 0x010004:
        tmd_hdr_ofs = tmd_ofs + 0x140
    elif tmd_sig_type == 0x010005:
        tmd_hdr_ofs = tmd_ofs + 0x80
    else:
        print("HURP?")
    # fix save data size
    save_data_size = exheader[0x1C0:0x1C4]
    f.seek(tmd_hdr_ofs + 0x5A)
    f.write(save_data_size)

def get_titleid(filename):
    with open(filename, "rb") as fh:
        header = ncsdHdr()
        fh.readinto(header) #Reads header into structure
        return reverseCtypeArray(header.titleId)

def find_xorpad(titleid, crc32):
    expectedname = "%s.%08lx.Main.exheader.xorpad" % (titleid, crc32)
    legacyname = titleid + ".Main.exheader.xorpad"

    xorpads = glob.glob(os.path.join("xorpads", "*.[xX][oO][rR][pP][aA][dD]"))
    xorpads += glob.glob(os.path.join("xorpads", "*.[zZ][iI][pP]"))

    for xorpad in xorpads:
        if zipfile.is_zipfile(xorpad):
            with zipfile.ZipFile(xorpad, "r") as e:
                for entry in e.infolist():
                    filename = os.path.join(tmpdir, expectedname)
                    basename = os.path.basename(entry.filename)
                    if basename.lower() == expectedname.lower():
                        source = e.open(entry, "r")
                        target = file(filename, "wb")
                        with source, target:
                            shutil.copyfileobj(source, target)
                        return filename
        else:
            basename = os.path.basename(xorpad)
            if basename.lower() == expectedname.lower() or \
               basename.lower() == legacyname.lower():

                return xorpad

def convert_to_cia(filename, crc32):
    titleid = get_titleid(filename)
    xorpad = find_xorpad(titleid, crc32)
    tools_path = get_tools_path()

    if verify_xorpad(filename, xorpad) == False:
        print "Xorpad file is not valid."
        return False

    # Extract cxi and cfa
    subprocess.call([os.path.join(tools_path, "rom_tool"), "--extract=" + tmpdir, filename])

    # Remove any update data
    for x in glob.iglob(os.path.join(tmpdir, "*_UPDATEDATA.[cC][fF][aA]")):
        os.remove(x)

    # Fix cxi
    fix_cxi(glob.glob(os.path.join(tmpdir, "*_APPDATA.cxi"))[0], xorpad)

    # Generate CIA file
    contents = glob.glob(os.path.join(tmpdir, "*.[cC][xX][iI]"))
    contents += glob.glob(os.path.join(tmpdir, "*.[cC][fF][aA]"))

    # Generate makerom command line
    cmdline = []
    i = 0
    for content in contents:
        cmdline += ["-content", content + ":" + str(i) + ":" + str(i)]
        i += 1

    ciafilename = os.path.join("cia", os.path.splitext(os.path.basename(filename))[0]) + ".cia"

    # Generate CIA file
    subprocess.call([os.path.join(tools_path, "makerom"), "-v", "-f", "cia", "-o", ciafilename] + cmdline)

    fix_cia(ciafilename, xorpad)
    for content in contents:
        os.remove(content)

def get_tools_path():
    is_64 = platform.machine().endswith("64")

    if not is_64:
        print colorama.Fore.RED + "Sorry, 32 bit OSes are not supported yet."
        print colorama.Style.RESET_ALL
        sys.exit(1)

    if getattr(sys, 'frozen', False):
        # we are running in a bundle
        bundle_dir = sys._MEIPASS
    else:
        # we are running in a normal Python environment
        bundle_dir = os.path.dirname(os.path.abspath(__file__))

    if sys.platform == "win32":
        return os.path.join(bundle_dir, "tools", "win64")
    elif sys.platform == "linux" or sys.platform == "linux2":
        return os.path.join(bundle_dir, "tools", "linux64")

    print colorama.Fore.RED + "Sorry, your OS is not supported yet."
    print colorama.Style.RESET_ALL
    sys.exit(1)

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.realpath(sys.argv[0])))

    colorama.init()

    roms = glob.glob(os.path.join("roms", "*.[3zZ][dDiI][sSpP]"))
    tmpdir = tempfile.mkdtemp()
    try:
        if roms == []:
            print "No valid files in rom directory found."
            sys.exit(1)

        print colorama.Fore.GREEN + "Work in progress... Please wait..."
        print colorama.Style.RESET_ALL

        check = True
        while True:
            missing_xorpads = []
            if check:
                print colorama.Style.BRIGHT + "Checking for xorpads..."
            else:
                print colorama.Style.BRIGHT + "Creating CIA..."
            print colorama.Style.RESET_ALL
            for rom in roms:
                if zipfile.is_zipfile(rom):
                    print rom
                    with zipfile.ZipFile(rom, "r") as e:
                        for entry in e.infolist():
                            basename = os.path.basename(entry.filename)
                            if not basename or not basename.lower().endswith(".3ds"):
                                continue
                            if check:
                                sys.stdout.write("\t-> " + entry.filename)
                            else:
                                print "\t-> " + entry.filename
                                print ""
                            crc32 = entry.CRC & 0xFFFFFFFF
                            filename = os.path.join(tmpdir, basename)
                            source = e.open(entry, "r")
                            if check:
                                with open(filename, "wb") as target:
                                    target.write(e.open(entry, 'r').read(0x10000))
                                titleid = get_titleid(filename)
                                if not find_xorpad(titleid, crc32):
                                    print colorama.Fore.RED + " [NOT FOUND]"
                                    missing_xorpads.append([filename, crc32])
                                else:
                                    os.remove(filename)
                                    print colorama.Fore.GREEN + " [FOUND]"
                            else:
                                target = file(filename, "wb")
                                with source, target:
                                    shutil.copyfileobj(source, target)
                                convert_to_cia(filename, crc32)
                                os.remove(filename)
                                print colorama.Fore.GREEN + "[OK]"

                            sys.stdout.write(colorama.Style.RESET_ALL)
                            sys.stdout.flush()
                else:
                    if check:
                        sys.stdout.write(rom)
                    else:
                        print rom
                        print ""
                    crc32 = 0
                    with open(rom, "rb") as fh:
                        while True:
                            buf = fh.read(0x10000)
                            if not buf: break
                            crc32 = binascii.crc32(buf, crc32)
                        crc32 = crc32 & 0xFFFFFFFF
                    if check:
                        titleid = get_titleid(rom)
                        if not find_xorpad(titleid, crc32):
                            print colorama.Fore.RED + " [NOT FOUND]"
                            missing_xorpads.append([rom, crc32])
                        else:
                            print colorama.Fore.GREEN + " [FOUND]"
                    else:
                        convert_to_cia(rom, crc32)
                        print colorama.Fore.GREEN + "[OK]"
                    sys.stdout.write(colorama.Style.RESET_ALL)
                    sys.stdout.flush()

                print ""

            if check == False:
                break

            if missing_xorpads != []:
                ncchinfo_gen(missing_xorpads)

                print "Copy ncchinfo.bin to your 3DS and make it generates the required xorpads"
                print "Then copy the generated xorpads in the 'xorpads' directory"
                print ""
                raw_input("Press Enter to continue...")
            else:
                check = False

    finally:
        shutil.rmtree(tmpdir)
        raw_input("Press Enter to continue...")
