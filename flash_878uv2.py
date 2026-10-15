#!/usr/bin/env python3
"""
AnyTone D878UV / D878UVII bootloader flasher (Linux, pyserial).

Wire protocol reconstructed from the vendor CPS 4.00 (D878UVII.exe, VB6 native)
and cross-checked with reald/anytone-flash-tools flash_firmware.py:

  host -> "UPDATE"                          radio -> 06
  host -> 02                                radio -> 'I' + model[8] + hwver[...] ... 06   (16 bytes)
  host -> 01 AA AA AA AA <32 data> CS CS 06 radio -> 06     (repeat; AA = LE address,
                                                             CS = LE 16-bit sum of bytes 1..36,
                                                             last block zero-padded)
  host -> 18                                radio -> 06

CPS behaviour on a bad/absent reply: resend the same packet (3 attempts total),
then abort and offer to restart from "UPDATE".

Radio side: power on holding PF3 (top) + PTT -> red LED blinks, USB CDC port appears.
The PF1+PTT "Initialize the radio?" step afterwards is the stock firmware's factory
reset, not part of flashing.

USE AT YOUR OWN RISK.
"""
import argparse, os, sys, time

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
        sys.exit(f'.spi is {len(spi)} bytes; only the 50/51-byte "V200" format (UPDATE path) is supported')
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
    if not (0x08004000 <= addr and addr + size <= 0x08100000):
        sys.exit(f'refusing address range {addr:#x}..{addr+size:#x} (bootloader lives below 0x08004000)')
    return model, hwver, addr, cdd

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
    ap = argparse.ArgumentParser()
    ap.add_argument('spi'); ap.add_argument('port', nargs='?', default='/dev/ttyACM0')
    ap.add_argument('--dry-run', action='store_true', help='parse files and print first/last packets only')
    a = ap.parse_args()
    model, hwver, addr, cdd = load_set(a.spi)
    pk = list(packets(addr, cdd))
    print(f'model={model.decode()} hw={hwver.decode()} addr={addr:#010x} size={len(cdd)} packets={len(pk)}')
    if a.dry_run:
        for off, p in (pk[0], pk[1], pk[-1]):
            print(f'{off:#08x}: {p.hex()}')
        return

    import serial
    port = serial.Serial(a.port, 115200, timeout=0.2)
    input('Radio off -> hold PF3 + PTT -> power on (red LED blinks). Codeplug backed up? Enter to go...')

    if xfer(port, b'UPDATE', 1) != b'\x06':
        sys.exit('no ACK to UPDATE')
    ident = xfer(port, b'\x02', 16)
    if len(ident) != 16 or ident[0:1] != b'I' or ident[15:16] != b'\x06':
        sys.exit(f'bad ident reply: {ident.hex()}')
    r_model = ident[1:9].split(b'\x00')[0].split(b'\xff')[0].rstrip(b' ')
    r_hw = ident[9:13]
    print(f'radio: model={r_model!r} hw={r_hw!r}')
    if r_model != model or r_hw != hwver:
        sys.exit('model/hardware mismatch with update file')

    for n, (off, p) in enumerate(pk):
        for attempt in range(3):
            if xfer(port, p, 1) == b'\x06': break
        else:
            sys.exit(f'packet at {addr+off:#x} failed 3 times; power-cycle into PF3+PTT and restart')
        if n % 256 == 0: print(f'\r{100*n//len(pk):3d}%', end='', flush=True)
    print('\r100%')
    if xfer(port, b'\x18', 1) != b'\x06':
        sys.exit('no ACK to end-of-transfer')
    print('done')

if __name__ == '__main__':
    main()
