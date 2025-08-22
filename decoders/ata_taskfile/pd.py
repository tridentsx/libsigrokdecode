# -------------------------------
# File: pd.py
# -------------------------------
# SPDX-License-Identifier: GPL-2.0-or-later
#
# IDE / ATA–ATAPI Task-File control-plane decoder for sigrok / PulseView
# ----------------------------------------------------------------------
# Decodes register reads/writes on the parallel ATA (PATA/IDE) bus and
# identifies ATA commands and (optionally) ATAPI PACKET CDBs.
#
# Notes
# - Focuses on the control plane (task-file registers). Data payloads are
#   ignored by default except for the short ATAPI PACKET CDB write after
#   the PACKET (0xA0) command if enabled.
# - Only D0..D7 are required for control decoding (commands/params/status).
# - LBA48 high-order bytes are captured when HOB bit in Device Control is set.
# - Optional pins (INTRQ, DMARQ, etc.) improve context but are not required.
#
# Usage (in sigrok):
#   1) Add this decoder to your sigrok decoders path, e.g.:
#      ~/.local/share/sigrok/decoders/ata_taskfile/
#      with files: __init__.py (this file), metadata, etc. (sigrok will pick
#      it up directly from a single file too in dev mode).
#   2) Wire channels as declared in `channels` below (minimum set is D0..D7,
#      DIOR-, DIOW-, CS0-, CS1-, DA0..DA2).
#   3) Set options: keep Data register ignored unless you want ATAPI CDB parse.
#
# Limitations
# - This is a clean, functional starter. Depending on your capture quality,
#   you may want to tweak edge sampling (e.g., add setup/hold delays or
#   debounce). The core decode paths and mappings are complete.
# - The sigrok PD API is stable, but if you run an older release you might
#   need to adapt small API details.

import sigrokdecode as srd

# -------------------------- Command & CDB tables ----------------------------

ATA_COMMANDS = {
    0x00: "NOP",
    0x06: "DATA SET MANAGEMENT",
    0x07: "DATA SET MANAGEMENT XL",
    0x08: "DEVICE RESET",
    0x0B: "REQUEST SENSE DATA EXT",

    0x10: "RECALIBRATE",
    0x20: "READ SECTORS",
    0x21: "READ SECTORS (no retry)",
    0x22: "READ LONG",
    0x23: "READ LONG (no retry)",
    0x24: "READ SECTORS EXT",
    0x25: "READ DMA EXT",
    0x26: "READ DMA QUEUED EXT",
    0x27: "READ NATIVE MAX ADDRESS EXT",
    0x29: "READ MULTIPLE EXT",
    0x2A: "READ STREAM DMA EXT",
    0x2B: "READ STREAM EXT",
    0x2F: "READ LOG EXT",

    0x30: "WRITE SECTORS",
    0x31: "WRITE SECTORS (no retry)",
    0x32: "WRITE LONG",
    0x33: "WRITE LONG (no retry)",
    0x34: "WRITE SECTORS EXT",
    0x35: "WRITE DMA EXT",
    0x36: "WRITE DMA QUEUED EXT",
    0x39: "WRITE MULTIPLE EXT",
    0x3A: "WRITE STREAM DMA EXT",
    0x3B: "WRITE STREAM EXT",
    0x3C: "WRITE VERIFY",
    0x3D: "WRITE DMA FUA EXT",
    0x3E: "WRITE DMA QUEUED FUA EXT",
    0x3F: "WRITE LOG EXT",

    0x40: "READ VERIFY SECTORS",
    0x41: "READ VERIFY SECTORS (no retry)",
    0x42: "READ VERIFY SECTORS EXT",
    0x44: "ZERO EXT",
    0x45: "WRITE UNCORRECTABLE EXT",
    0x47: "READ LOG DMA EXT",
    0x4A: "ZAC MANAGEMENT IN",

    0x50: "FORMAT TRACK",
    0x51: "CONFIGURE STREAM",

    0x5B: "TRUSTED NON-DATA",
    0x5C: "TRUSTED RECEIVE",
    0x5D: "TRUSTED RECEIVE DMA",
    0x5E: "TRUSTED SEND",
    0x5F: "TRUSTED SEND DMA",

    0x60: "READ FPDMA QUEUED",
    0x61: "WRITE FPDMA QUEUED",
    0x63: "NCQ NON-DATA",
    0x64: "SEND FPDMA QUEUED",
    0x65: "RECEIVE FPDMA QUEUED",

    0x70: "SEEK",

    0x77: "SET DATE & TIME EXT",
    0x78: "ACCESSIBLE MAX ADDRESS CONFIGURATION",
    0x7C: "REMOVE ELEMENT AND TRUNCATE",
    0x7D: "RESTORE ELEMENTS AND REBUILD",

    0x87: "CFA TRANSLATE SECTOR",

    0x90: "EXECUTE DEVICE DIAGNOSTIC",
    0x91: "INITIALIZE DEVICE PARAMETERS",
    0x92: "DOWNLOAD MICROCODE",
    0x93: "DOWNLOAD MICROCODE DMA",

    0x9F: "ZAC MANAGEMENT OUT",

    0xA0: "PACKET",
    0xA1: "IDENTIFY PACKET DEVICE",
    0xA2: "SERVICE",

    0xB0: "SMART",
    0xB1: "DEVICE CONFIGURATION OVERLAY",
    0xB2: "SET SECTOR CONFIGURATION EXT",
    0xB4: "SANITIZE DEVICE",
    0xB6: "NV CACHE",

    0xC0: "CFA ERASE SECTORS",
    0xC4: "READ MULTIPLE",
    0xC5: "WRITE MULTIPLE",
    0xC6: "SET MULTIPLE MODE",
    0xC7: "READ DMA QUEUED",
    0xC8: "READ DMA",
    0xC9: "READ DMA (no retry)",
    0xCA: "WRITE DMA",
    0xCB: "WRITE DMA (no retry)",
    0xCC: "WRITE DMA QUEUED",
    0xCD: "CFA WRITE MULTIPLE WITHOUT ERASE",
    0xCE: "WRITE MULTIPLE FUA EXT",

    0xD1: "CHECK MEDIA CARD TYPE",
    0xDA: "GET MEDIA STATUS",
    0xDB: "ACKNOWLEDGE MEDIA CHANGE",
    0xDE: "MEDIA LOCK",
    0xDF: "MEDIA UNLOCK",

    0xE0: "STANDBY IMMEDIATE",
    0xE1: "IDLE IMMEDIATE",
    0xE2: "STANDBY",
    0xE3: "IDLE",
    0xE4: "READ BUFFER",
    0xE5: "CHECK POWER MODE",
    0xE6: "SLEEP",
    0xE7: "FLUSH CACHE",
    0xE8: "WRITE BUFFER",
    0xE9: "READ BUFFER DMA",
    0xEA: "FLUSH CACHE EXT",
    0xEB: "WRITE BUFFER DMA",
    0xEC: "IDENTIFY DEVICE",
    0xED: "MEDIA EJECT",
    0xEE: "IDENTIFY DEVICE DMA",
    0xEF: "SET FEATURES",

    0xF1: "SECURITY SET PASSWORD",
    0xF2: "SECURITY UNLOCK",
    0xF3: "SECURITY ERASE PREPARE",
    0xF4: "SECURITY ERASE UNIT",
    0xF5: "SECURITY FREEZE LOCK",
    0xF6: "SECURITY DISABLE PASSWORD",

    0xF8: "READ NATIVE MAX ADDRESS",
    0xF9: "SET MAX ADDRESS",
}

# Vendor/custom ranges (used only for labeling hints, not enforced)
VENDOR_RANGES = [(0x80,0x8F),(0x9A,0x9E),(0xC1,0xC3),(0xF0,0xF0),(0xFA,0xFF)]

# User-extensible override map (takes precedence over ATA_COMMANDS)
CUSTOM_ATA_COMMANDS = {
    # 0xXY: 'YourVendor Foo',
}

# Common ATAPI/SCSI CDB mnemonics (subset; extend as needed)
ATAPI_CDB = {
    0x00: 'TEST UNIT READY',
    0x03: 'REQUEST SENSE',
    0x12: 'INQUIRY',
    0x1A: 'MODE SENSE(6)',
    0x1B: 'START STOP UNIT',
    0x23: 'READ FORMAT CAPACITIES',
    0x25: 'READ CAPACITY(10)',
    0x28: 'READ(10)',
    0x2A: 'WRITE(10)',
    0x2B: 'SEEK(10)',
    0x2F: 'VERIFY(10)',
    0x35: 'SYNCHRONIZE CACHE(10)',
    0x43: 'READ TOC/PMA/ATIP',
    0x44: 'READ HEADER',
    0x45: 'PLAY AUDIO(10)',
    0x47: 'PLAY AUDIO MSF',
    0x48: 'PLAY AUDIO TRACK/INDEX',
    0x4A: 'GET EVENT STATUS NOTIFICATION',
    0x5A: 'MODE SENSE(10)',
    0xA1: 'BLANK (MMC)',
    0xBB: 'SET CD SPEED (MMC)',
}

# Sony vendor CDBs (classic)
CUSTOM_ATAPI_CDB = {
    0xC1: 'SONY: READ TOC',
    0xC2: 'SONY: READ SUB-CHANNEL',
    0xC3: 'SONY: READ HEADER',
    0xC4: 'SONY: PLAYBACK STATUS',
    0xC5: 'SONY: PAUSE',
    0xC6: 'SONY: PLAY TRACK',
    0xC7: 'SONY: PLAY MSF',
    0xC8: 'SONY: PLAY AUDIO (LBA+len)',
    0xC9: 'SONY: PLAYBACK CONTROL',
}

# ---------------------------- Decoder class ---------------------------------

class Decoder(srd.Decoder):
    api_version = 3
    id = 'ata_taskfile'
    name = 'IDE/ATA-ATAPI Task-File'
    longname = 'IDE / ATA–ATAPI task-file control-plane'
    desc = 'Decodes PATA task-file register accesses and ATAPI CDBs.'
    license = 'gplv2+'
    inputs = ['logic']
    outputs = ['ata_taskfile']
    tags = ['Storage', 'Parallel']

    # Channel order matters; indices are used in wait() and sampling.
    channels = (
        # Data low byte
        {'id':'d0', 'name':'D0', 'desc':'Data bit 0'},
        {'id':'d1', 'name':'D1', 'desc':'Data bit 1'},
        {'id':'d2', 'name':'D2', 'desc':'Data bit 2'},
        {'id':'d3', 'name':'D3', 'desc':'Data bit 3'},
        {'id':'d4', 'name':'D4', 'desc':'Data bit 4'},
        {'id':'d5', 'name':'D5', 'desc':'Data bit 5'},
        {'id':'d6', 'name':'D6', 'desc':'Data bit 6'},
        {'id':'d7', 'name':'D7', 'desc':'Data bit 7'},

        # Control/address
        {'id':'diow', 'name':'DIOW-', 'desc':'I/O write strobe (active low)'},
        {'id':'dior', 'name':'DIOR-', 'desc':'I/O read strobe (active low)'},
        {'id':'cs0',  'name':'CS0-',  'desc':'Chip Select 0 (active low)'},
        {'id':'cs1',  'name':'CS1-',  'desc':'Chip Select 1 (active low)'},
        {'id':'da0',  'name':'DA0',   'desc':'Address bit 0'},
        {'id':'da1',  'name':'DA1',   'desc':'Address bit 1'},
        {'id':'da2',  'name':'DA2',   'desc':'Address bit 2'},
    )

    optional_channels = (
        {'id':'intrq','name':'INTRQ','desc':'Interrupt request'},
        {'id':'reset','name':'RESET-','desc':'Reset (active low)'},
        {'id':'iordy','name':'IORDY','desc':'I/O ready'},
        {'id':'dmarq','name':'DMARQ','desc':'DMA request'},
        {'id':'dmack','name':'DMACK-','desc':'DMA acknowledge (active low)'},
        {'id':'dasp', 'name':'DASP-','desc':'Drive active / slave present'},
        {'id':'pdiag','name':'PDIAG-','desc':'Passed diagnostics'},
        {'id':'iocs16','name':'IOCS16-','desc':'16-bit I/O indicator'},
        # Upper data byte could be added if you wish to parse payloads later.
        {'id':'d8', 'name':'D8', 'desc':'Data bit 8'},
        {'id':'d9', 'name':'D9', 'desc':'Data bit 9'},
        {'id':'d10','name':'D10','desc':'Data bit 10'},
        {'id':'d11','name':'D11','desc':'Data bit 11'},
        {'id':'d12','name':'D12','desc':'Data bit 12'},
        {'id':'d13','name':'D13','desc':'Data bit 13'},
        {'id':'d14','name':'D14','desc':'Data bit 14'},
        {'id':'d15','name':'D15','desc':'Data bit 15'},
    )

    options = (
        {'id':'parse_cdb', 'desc':'Parse ATAPI PACKET CDB', 'default':True},
        {'id':'ignore_data','desc':'Ignore Data register except CDB window','default':True},
        {'id':'squelch_dma','desc':'Hide events while DMARQ asserted','default':True},
        {'id':'emit_reads','desc':'Annotate register reads (Status/AltStatus)','default':False},
    )

    annotations = (
        ('regw',  'Register write'),
        ('regr',  'Register read'),
        ('cmd',   'ATA command'),
        ('cdb',   'ATAPI CDB'),
        ('status','Status/AltStatus'),
        ('devctl','Device Control write'),
        ('intrq', 'Interrupt'),
        ('warn',  'Warning / note'),
    )
    annotation_rows = (
        ('cmds', 'Commands', (2,3)),
        ('regs', 'Regs', (0,1,5)),
        ('ints', 'Signals', (6,7)),
    )

    def __init__(self):
        self.out_ann = None

    # ---------------------------- Lifecycle ---------------------------------
    def start(self):
        self.out_ann = self.register(srd.OUTPUT_ANN)
        self.reset()

    def reset(self):
        # Cached channel indices for speed
        def idx(id_):
            try:
                return self.channels.index(next(ch for ch in self.channels if ch['id']==id_))
            except StopIteration:
                # Fallback for optional lookups using get_sig()
                return None
        # Build a dict id->index for quick sampling
        self.ch_idx = {ch['id']: i for i,ch in enumerate(self.channels)}
        self.opt_idx = {ch['id']: (len(self.channels)+i) for i,ch in enumerate(self.optional_channels)}

        # Task-file shadow (low + high order if HOB active)
        self.tf = {
            'features':0,'sector_count':0,'lba0':0,'lba1':0,'lba2':0,'device':0,
            'hob_features':0,'hob_sector_count':0,'hob_lba0':0,'hob_lba1':0,'hob_lba2':0,
        }
        self.hob = 0  # Device Control bit7 High Order Byte select
        self.in_cdb = False
        self.cdb_bytes_expected = 0
        self.cdb_buf = []

    # -------------------------- Helpers / sampling --------------------------
    def get_sig(self, name):
        # Return (index, presentbool). Works for optional channels too.
        if name in self.ch_idx:
            return self.ch_idx[name], True
        if name in self.opt_idx:
            return self.opt_idx[name], True
        return None, False

    def rd_bit(self, name):
        idx, ok = self.get_sig(name)
        if not ok:
            return 0
        return self.samples[idx]

    def rd_bus8(self):
        v = 0
        for i,name in enumerate(['d0','d1','d2','d3','d4','d5','d6','d7']):
            v |= (1 if self.rd_bit(name) else 0) << i
        return v & 0xFF

    def rd_addr(self):
        a = (1 if self.rd_bit('da0') else 0) | ((1 if self.rd_bit('da1') else 0) << 1) | ((1 if self.rd_bit('da2') else 0) << 2)
        return a

    def cs_sel(self):
        cs0 = not self.rd_bit('cs0')  # active-low
        cs1 = not self.rd_bit('cs1')
        return cs0, cs1

    def puta(self, ss, es, aidx, text):
        self.put(ss, es, self.out_ann, [aidx, [text]])

    def reg_name(self, cs0, cs1, da, is_write):
        if cs0 and not cs1:
            # Task file
            if da == 0:
                return 'data'
            elif da == 1:
                return 'features' if is_write else 'error'
            elif da == 2:
                return 'sector_count'
            elif da == 3:
                return 'lba0'
            elif da == 4:
                return 'lba1'
            elif da == 5:
                return 'lba2'
            elif da == 6:
                return 'device'
            elif da == 7:
                return 'command' if is_write else 'status'
        elif cs1 and not cs0:
            # Control block
            if da == 6:
                return 'devctl' if is_write else 'altstatus'
            elif da == 7:
                return 'drive_addr'
        return None

    def lba_mode(self):
        return 'LBA' if (self.tf['device'] & 0x40) else 'CHS'

    def lba28(self):
        dev_low4 = self.tf['device'] & 0x0F
        return ((dev_low4 << 24) | (self.tf['lba2'] << 16) | (self.tf['lba1'] << 8) | self.tf['lba0']) & 0x0FFFFFFF

    def lba48(self):
        hi = (self.tf['hob_lba2'] << 16) | (self.tf['hob_lba1'] << 8) | self.tf['hob_lba0']
        lo = (self.tf['lba2']     << 16) | (self.tf['lba1']     << 8) | self.tf['lba0']
        return ((hi << 24) | lo) & 0xFFFFFFFFFFFF

    def sc48(self):
        return ((self.tf['hob_sector_count'] << 8) | self.tf['sector_count']) & 0xFFFF

    # ------------------------------- Decode ---------------------------------
    def decode(self):
        # acquire channel indices for fast edge wait()
        idx_diow = self.ch_idx['diow']
        idx_dior = self.ch_idx['dior']
        # minimal wait list: falling edge of read/write strobes
        waitlist = [{idx_diow: 'f'}, {idx_dior: 'f'}]

        while True:
            # Wait for a bus strobe (write/read)
            self.wait(waitlist)
            ss = self.samplenum
            # Snapshot all relevant signals at this strobe edge
            self.samples = [self.logic[i] for i in range(len(self.logic))] if hasattr(self, 'logic') else [self.matched.get(i, 0) for i in range(max(self.opt_idx.values())+1)]

            is_write = (self.matched.get(idx_diow, 1) == 0)  # DIOW- active low at this instant
            is_read  = (self.matched.get(idx_dior, 1) == 0)

            # Optional: squelch during DMA phases
            if self.options['squelch_dma']:
                idx_dmarq, ok = self.get_sig('dmarq')
                if ok and self.samples[idx_dmarq]:
                    # DMARQ high usually means DMA data phase; hide chatter
                    continue

            # Determine selection and address
            cs0, cs1 = self.cs_sel()
            da = self.rd_addr()
            reg = self.reg_name(cs0, cs1, da, is_write)

            # Only react to valid register cycles
            if not reg:
                continue

            val = self.rd_bus8()
            es = self.samplenum

            # Handle Device Control & HOB
            if reg == 'devctl' and is_write:
                self.hob = 1 if (val & 0x80) else 0
                txt = f"DEVCTL write: SRST={(val>>2)&1} nIEN={(val>>1)&1} HOB={(val>>7)&1}"
                self.puta(ss, es, 5, txt)
                continue

            # Reads (optional annotation)
            if (reg in ('status','altstatus') and is_read) or (self.options['emit_reads'] and is_read):
                self.puta(ss, es, 4, f"{reg.upper()} read: 0x{val:02X}")
                # On Status read, a device might clear INTRQ; annotate if seen.
                idx_intrq, ok = self.get_sig('intrq')
                if ok and not self.samples[idx_intrq]:
                    self.puta(ss, es, 6, 'INTRQ cleared')
                continue

            # Writes to task-file parameters
            if is_write and reg in ('features','sector_count','lba0','lba1','lba2','device'):
                if self.hob and reg in ('features','sector_count','lba0','lba1','lba2'):
                    hreg = 'hob_'+reg
                    self.tf[hreg] = val
                    self.puta(ss, es, 0, f"{hreg} = 0x{val:02X}")
                else:
                    self.tf[reg] = val
                    self.puta(ss, es, 0, f"{reg} = 0x{val:02X}")
                continue

            # Data register accesses
            if reg == 'data':
                # If we are in ATAPI PACKET CDB window, collect bytes.
                if self.in_cdb and is_write:
                    if self.options['parse_cdb']:
                        self.cdb_buf.append(val)
                        if len(self.cdb_buf) == 1:
                            c0 = self.cdb_buf[0]
                            name = CUSTOM_ATAPI_CDB.get(c0) or ATAPI_CDB.get(c0) or 'SCSI CDB'
                            self.puta(ss, es, 3, f"ATAPI CDB[0]=0x{c0:02X} {name}")
                        if self.cdb_bytes_expected and len(self.cdb_buf) >= self.cdb_bytes_expected:
                            self.in_cdb = False
                            self.puta(ss, es, 3, f"CDB complete ({len(self.cdb_buf)} bytes)")
                    else:
                        # not parsing: still mark
                        self.puta(ss, es, 3, "ATAPI CDB byte")
                    continue
                # Otherwise ignore Data reg if option enabled
                if self.options['ignore_data']:
                    continue
                # If not ignoring, annotate raw data access
                op = 'WRITE' if is_write else 'READ'
                self.puta(ss, es, 0 if is_write else 1, f"DATA {op}: 0x{val:02X}")
                continue

            # Command write: emit a full command annotation
            if reg == 'command' and is_write:
                op = val
                name = CUSTOM_ATA_COMMANDS.get(op) or ATA_COMMANDS.get(op) or 'UNKNOWN'
                # Detect ATAPI PACKET which triggers CDB window
                if op == 0xA0:
                    self.in_cdb = True
                    # ATAPI PACKET is typically 12 bytes for MMC; some devices use 16
                    self.cdb_bytes_expected = 12
                    self.cdb_buf = []
                # Build parameter summary
                mode = self.lba_mode()
                sc = self.tf['sector_count']
                lba = self.lba28()
                hob_any = any(self.tf[k] for k in ('hob_sector_count','hob_lba0','hob_lba1','hob_lba2'))
                if hob_any:
                    sc = self.sc48()
                    lba = self.lba48()
                sc_str = f"SC={sc}"
                lba_str = f"LBA48=0x{lba:012X}" if hob_any else f"LBA28=0x{lba:08X}"
                dev = self.tf['device']
                dev_str = f"DEV=0x{dev:02X}({mode})"
                self.puta(ss, es, 2, f"CMD 0x{op:02X} {name}  {sc_str}  {lba_str}  {dev_str}")
                continue

            # Other reads
            if self.options['emit_reads'] and is_read:
                self.puta(ss, es, 1, f"{reg} read: 0x{val:02X}")
