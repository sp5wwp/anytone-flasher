# anytone-flasher
AnyTone D878UV / D878UVII flasher (Linux, pyserial)

## Usage

First, make sure pyserial is available (`pip install pyserial`), then execute

```bash
python3 flash_878uv2.py D878UVII_V4.00_20250725.spi /dev/ttyACM0
```

with the radio started in PF3+PTT mode (keep these buttons pressed while turning the radio on).
The `.CDI` and `.CDD` files need the same base name in the same folder (that's a total of 3 files).
