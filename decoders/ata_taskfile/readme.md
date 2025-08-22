
# IDE / ATA–ATAPI Task-File (sigrok/PulseView) Decoder

Decodes **PATA/IDE task-file** register accesses (Features/SC/LBA0..2/Device/Status/Command) and optionally the **ATAPI PACKET CDB** (12/16 bytes) after `PACKET (0xA0)`—while skipping bulk data phases.

## Install

Create a folder and place the files:
```
~/.local/share/sigrok/decoders/ata_taskfile/
  ├── pd.py            # the decoder (rename the canvas file to pd.py)
  ├── metadata.json
  └── README.md
```
On Windows, use `%APPDATA%/sigrok/decoders/ata_taskfile/`.
Restart PulseView and add the decoder from the *Protocol Decoders* list.

## Channels
Required (minimum):
- `D0..D7`, `DIOR-`, `DIOW-`, `CS0-`, `CS1-`, `DA0..DA2`

Optional (recommended):
- `INTRQ`, `RESET-`, `IORDY`, `DMARQ`, `DMACK-`, `DASP-`, `PDIAG-`, `IOCS16-`, `D8..D15`

> **Tip:** Only `D0..D7` are needed for control-plane decode. Keep probes short; IDE is 5V TTL—use level shifters for 3.3V analyzers.

## Options
- **Parse ATAPI PACKET CDB** (`parse_cdb`, default **on**) – interprets 12/16-byte CDB written after `0xA0`.
- **Ignore Data register** (`ignore_data`, default **on**) – hides payload reads/writes except during a CDB window.
- **Hide during DMA** (`squelch_dma`, default **on**) – suppresses annotations while `DMARQ` is asserted.
- **Emit register reads** (`emit_reads`, default **off**) – annotate `STATUS`/`ALTSTATUS` reads.

## Address map (task-file)
With **CS0- = 0**:
- `DA=000` Data (ignored unless CDB window)
- `001` Features (W) / Error (R)
- `010` SectorCount
- `011` LBA0
- `100` LBA1
- `101` LBA2
- `110` Device/Head
- `111` Command (W) / Status (R)

With **CS1- = 0**:
- `DA=110` Device Control (W) / Alt Status (R)
- `DA=111` Drive Address (legacy)

## LBA48 / HOB handling
On **Device Control**, bit 7 (HOB) selects the *High-Order Byte* latch. Writes to Features/SC/LBA0..2 while HOB=1 are stored separately and combined to LBA48/SC48 for command annotations.

## Quick demo (what you should see)
- **Command setup** (writes to params):
  - `features = 0x01`, `sector_count = 0x08`, `lba0 = 0x89`, `lba1 = 0x67`, `lba2 = 0x45`, `device = 0x40` (LBA)
- **Command write**: 
  - `CMD 0x24 READ SECTORS EXT  SC=8  LBA48=0x000000456789  DEV=0x40(LBA)`
- **ATAPI**: after `CMD 0xA0 PACKET`, a small burst to `Data` shows:
  - `ATAPI CDB[0]=0x28 READ(10)` then `CDB complete (12 bytes)`.

## Usage with sigrok-cli
List decoders and options:
```
sigrok-cli -L | grep ata_taskfile
sigrok-cli -i capture.sr -P ata_taskfile:parse_cdb=1,ignore_data=1,squelch_dma=1
```

## Triggers / capture advice
If the LA supports triggers, trigger on **DIOW- falling** with `CS0- low` and `DA2..0 = 111` (Command register write). Use 50–100 MHz if possible; 24 MHz often suffices for PIO commands.

## Vendor / custom commands
Add your mappings in `CUSTOM_ATA_COMMANDS` and `CUSTOM_ATAPI_CDB` in `pd.py`. The decoder prefers custom labels over built-ins.

## License
GPL-2.0-or-later. Contributions welcome.
```
```

---

## Example annotation walkthrough (synthetic)
```text
[t=0.000000s] features = 0x01
[t=0.000001s] sector_count = 0x08
[t=0.000002s] lba0 = 0x89
[t=0.000003s] lba1 = 0x67
[t=0.000004s] lba2 = 0x45
[t=0.000005s] device = 0x40
[t=0.000006s] CMD 0x24 READ SECTORS EXT  SC=8  LBA48=0x000000456789  DEV=0x40(LBA)
[t=0.000120s] STATUS read: 0x50
[t=0.010500s] INTRQ cleared

# ATAPI CDB window
[t=1.000000s] CMD 0xA0 PACKET  SC=0  LBA28=0x00456789  DEV=0xA0(LBA)
[t=1.000010s] ATAPI CDB[0]=0x28 READ(10)
[t=1.000050s] CDB complete (12 bytes)
```

---

## Folder layout recap
```
ata_taskfile/
  pd.py         # (rename the canvas decoder file to pd.py)
  metadata.json
  README.md
```