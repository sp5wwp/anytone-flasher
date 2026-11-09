# anytone-flasher
AnyTone D878UV / D878UVII / D890UV firmware flasher (Linux/Windows, pyserial)

>[!NOTE]
> Based on [reald's anytone-flash-tools](https://github.com/reald/anytone-flash-tools).
> Tested on actual hardware: **D890UV**, firmware 1.00 → 1.05. The D878UV/D878UVII path is not yet tested.

## Usage

First, make sure pyserial is available (`pip install pyserial`), then execute

```bash
python3 flash_anytone.py D890UV_V1.05_20260521.spi /dev/ttyACM0
```

with the radio started in update mode (see below). The `.CDI` and `.CDD` files need the same base name in the same folder (that's a total of 3 files). On Windows, pass the COM port instead, e.g. `COM15`.

The bootloader profile is picked from the model name in the `.spi` file. To force one, use `--model`:

```bash
python3 flash_anytone.py --model D890UV D890UV_V1.05_20260521.spi /dev/ttyACM0
```

### Options

| Option | Description |
|---|---|
| `--model {D878UV,D878UV2,D890UV}` | Bootloader profile to use (default: taken from the `.spi` file) |
| `--dry-run` | Parse the files and print the first/last packets, no serial port needed |
| `--probe` | Handshake and identify the radio only, nothing is written |
| `--yes` | Skip the confirmation prompt |

`--probe` confirms the radio is in update mode and that its model and hardware version match the update file. Power-cycle the radio back into update mode before the real flash.

## Entering update mode

Turn the radio off, then power it on while holding:

| Radio | Keys | Indication |
|---|---|---|
| D878UV / D878UVII | PTT + PF3 (top key) | red LED blinks |
| D890UV | PTT + PF3 (**top** emergency key) | "UPDATE MODE" on the display, green LED blinks |

>[!WARNING]
> On the D890UV, **PTT + PF2** (the lower side key) shows a very similar "UPDATE MODE" screen, but it's a different mode: it accepts a transfer and silently installs nothing. The script stops with `no ACK to UPDATE` if the radio is in that mode.

If you're flashing from a virtual machine, note that the radio re-enumerates on USB when entering update mode. Re-attach it to the VM if needed, and make sure no other program (vendor CPS, VM serial passthrough) holds the port.

## After flashing

The D890UV restarts into the new firmware as soon as the transfer ends and may show "Program Error, Please Initialize The Radio!". That's expected.

Reset the radio as the vendor instructions require: power it on while holding PTT + PF1 (the upper side key, directly below PTT) and confirm the initialization. **This wipes the codeplug**, so back it up with the CPS before flashing. Then check the firmware version in the radio's device information.

## Protocol

```
host -> "UPDATE"                           radio -> 06
host -> 02                                 radio -> 'I' + model[8] + hwver[4] ... 06   (16 bytes)
host -> 01 AA AA AA AA <32 data> CS CS 06  radio -> 06   (repeat; AA = LE address,
                                                          CS = LE 16-bit sum of bytes 1..36,
                                                          last block zero-padded)
host -> 18                                 radio -> 06 (D890UV: restarts and drops off USB instead)
```

| Radio | MCU | Writable range |
|---|---|---|
| D878UV / D878UVII | GD32F303 | `0x08004000`–`0x08100000` |
| D890UV | STM32U5 | `0x0800C000`–`0x08200000` |

The bootloader below the writable range is never touched, so a failed or interrupted flash can be retried from update mode.

In normal mode the D890UV answers `PROGRAM` with `QX` + `06` (CPS programming mode). The script uses this to detect a radio that isn't in update mode.
