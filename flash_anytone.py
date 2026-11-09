#!/usr/bin/env python3
"""
AnyTone bootloader flasher (Linux/Windows, pyserial).

Supported radios: D878UV, D878UVII, D890UV.

Wire protocol reconstructed from the vendor CPS 4.00 (D878UVII.exe, VB6 native),
cross-checked with reald/anytone-flash-tools flash_firmware.py, and confirmed
against the D890UV CPS 1.05 (traced under Wine) and a real D890UV:

  host -> "UPDATE"                          radio -> 06
  host -> 02                                radio -> 'I' + model[8] + hwver[4] ... 06   (16 bytes)
  host -> 01 AA AA AA AA <32 data> CS CS 06 radio -> 06     (repeat; AA = LE address,
                                                             CS = LE 16-bit sum of bytes 1..36,
                                                             last block zero-padded)
  host -> 18                                radio -> 06, or (D890UV) the radio restarts
                                                     into the new firmware and drops off USB

Entering the bootloader (power on while holding):
  D878UV/UVII: PTT + PF3 (top key), red LED blinks.
  D890UV:      PTT + PF3, where PF3 is the TOP (emergency) key. "UPDATE MODE"
               on the display, green LED blinks.

D890UV pitfall: PTT + PF2 (lower side key) shows a similar "UPDATE MODE" screen
but is a different mode. It ignores "UPDATE", answers "PROGRAM" with 06 and
acknowledges data packets without installing anything. The script refuses to
continue if "UPDATE" is not acknowledged.

After flashing, reset the radio (power on holding PTT + PF1) as the vendor
instructions require. This wipes the codeplug, so back it up first.

USE AT YOUR OWN RISK.
"""
import argparse, os, sys, time

# Per-model bootloader profiles.
#   lo: lowest writable address (the bootloader lives below it)
#   hi: end of MCU flash
PROFILES = {
    'D878UV':  dict(lo=0x08004000, hi=0x08100000),  # GD32F303, 1 MB
    'D878UV2': dict(lo=0x08004000, hi=0x08100000),  # GD32F303, 1 MB
    'D890UV':  dict(lo=0x0800C000, hi=0x08200000),  # STM32U5, 2 MB
}

def load_set(spi_path):
    base = spi_path[:-4]
    spi = open(spi_path, 'rb').read()
    def sib(ext):
        for e in (ext.upper(), ext.lower()):
            p = base + '.' + e
            if os.path.exists(p): return open(p, 'rb').read()
        sys.exit(f'missing {base}.{ext.upper()}')
    cdi, cdd = sib('CDI'), sib('CDD')

    if len(spi) not in (50, 51):
        sys.exit(f'.spi is {len(spi)} bytes; only the 50/51-byte "V200" format is supported')
    if int.from_bytes(spi[0:4], 'little') != 0x20:
        sys.exit('.spi header magic != 0x20')
    size = int.from_bytes(spi[6:10], 'little')
    model = spi[14:22].rstrip(b' \x00')          # 8-char field, e.g. b'D878UV2'
    hwver = spi[22:26]                           # e.g. b'V100'
    if len(cdi) != 278:
        sys.exit(f'.CDI is {len(cdi)} bytes, expected 278')
    addr = int.from_bytes(cdi[256:260], 'little')
    size2 = int.from_bytes(cdi[260:264], 'little')
    if size != size2 or size != len(cdd):
        sys.exit(f'size mismatch: spi={size} cdi={size2} cdd={len(cdd)}')
    return model.decode(), hwver, addr, cdd

def packets(addr, data):
    for off in range(0, len(data), 32):
        chunk = data[off:off+32].ljust(32, b'\x00')
        body = bytes([0x01]) + (addr + off).to_bytes(4, 'little') + chunk
        cs = sum(body[1:]) & 0xffff
        yield off, body + cs.to_bytes(2, 'little') + b'\x06'

def xfer(port, data, want, timeout=1.0):
    port.reset_input_buffer()
    port.write(data)
    buf, t0 = b'', time.time()
    while len(buf) < want and time.time() - t0 < timeout:
        buf += port.read(want - len(buf))
    return buf

def main():
    ap = argparse.ArgumentParser(description='AnyTone D878UV/D878UVII/D890UV bootloader flasher')
    ap.add_argument('spi', help='.spi file; the matching .CDI and .CDD must sit next to it')
    ap.add_argument('port', nargs='?', default='COM15' if os.name == 'nt' else '/dev/ttyACM0',
                    help='serial port (default: /dev/ttyACM0, or COM15 on Windows)')
    ap.add_argument('--model', choices=sorted(PROFILES),
                    help='bootloader profile to use (default: taken from the .spi file)')
    ap.add_argument('--dry-run', action='store_true', help='parse files and print first/last packets only')
    ap.add_argument('--probe', action='store_true', help='handshake + ident only, write nothing')
    ap.add_argument('--yes', action='store_true', help='skip the confirmation prompt')
    a = ap.parse_args()

    model, hwver, addr, cdd = load_set(a.spi)
    prof_name = a.model or model
    if prof_name not in PROFILES:
        sys.exit(f'unknown model {prof_name!r} in .spi; pass --model {{{",".join(sorted(PROFILES))}}}')
    prof = PROFILES[prof_name]
    if not (prof['lo'] <= addr and addr + len(cdd) <= prof['hi']):
        sys.exit(f'refusing address range {addr:#x}..{addr+len(cdd):#x} for {prof_name} '
                 f'(allowed {prof["lo"]:#x}..{prof["hi"]:#x}; bootloader lives below {prof["lo"]:#x})')

    pk = list(packets(addr, cdd))
    print(f'file: model={model} hw={hwver.decode()} addr={addr:#010x} size={len(cdd)} packets={len(pk)}')
    print(f'profile: {prof_name}')
    if a.dry_run:
        for off, p in (pk[0], pk[1], pk[-1]):
            print(f'{off:#08x}: {p.hex()}')
        return

    import serial
    # Open the port only after the radio is in bootloader mode: entering the
    # bootloader re-enumerates USB, so a handle opened earlier would be stale.
    if not a.yes:
        input('Radio off -> hold PTT + PF3 (top key) -> power on (UPDATE MODE). Codeplug backed up? Enter to go...')
    if a.port.startswith('/') and not os.path.exists(a.port):
        sys.exit(f'{a.port} does not exist - is the radio in UPDATE MODE and connected to this machine?')
    port = serial.Serial(a.port, 115200, timeout=0.2)
    time.sleep(0.5)

    # UPDATE is only retried while the radio has not acknowledged it.
    for attempt in range(3):
        r = xfer(port, b'UPDATE', 3)
        if r == b'\x06': break
        if r == b'QX\x06':
            sys.exit('radio answered QX: it is in normal mode, not UPDATE MODE')
        print(f'UPDATE attempt {attempt+1}: got {r.hex() or "nothing"}')
        time.sleep(0.5)
    else:
        hint = (' - on the D890UV, enter update mode with PTT + PF3 (top key), not PTT + PF2'
                if prof_name == 'D890UV' else '')
        sys.exit('no ACK to UPDATE' + hint)

    ident = xfer(port, b'\x02', 16)
    if len(ident) != 16 or ident[0:1] != b'I' or ident[15:16] != b'\x06':
        sys.exit(f'bad ident reply: {ident.hex()}')
    r_model = ident[1:9].split(b'\x00')[0].split(b'\xff')[0].rstrip(b' ').decode(errors='replace')
    r_hw = ident[9:13]
    print(f'radio: model={r_model} hw={r_hw.decode(errors="replace")}')
    if r_model != model or r_hw != hwver:
        sys.exit('model/hardware mismatch with update file')
    if a.probe:
        print('probe OK, nothing written - power-cycle into UPDATE MODE before flashing')
        return

    for n, (off, p) in enumerate(pk):
        for attempt in range(3):
            r = xfer(port, p, 1)
            if r == b'\x06': break
            if r == b'\x15': print(f'\nNAK for packet at {addr+off:#x}')
        else:
            sys.exit(f'packet at {addr+off:#x} failed 3 times; power-cycle into UPDATE MODE and restart')
        if n % 256 == 0: print(f'\r{100*n//len(pk):3d}%', end='', flush=True)
    print('\r100%')

    try:
        r = xfer(port, b'\x18', 1)
    except serial.SerialException:
        # The D890UV bootloader restarts into the new firmware right after the
        # end-of-transfer command, so the USB port disappears instead of ACKing.
        r = b'\x06'
        print('radio disconnected after end-of-transfer (restarting into the new firmware)')
    if r != b'\x06':
        sys.exit('no ACK to end-of-transfer')
    print('done - check the firmware version on the radio'
          ' (stock firmware: power on holding PTT + PF1 to reset)')

if __name__ == '__main__':
    main()
