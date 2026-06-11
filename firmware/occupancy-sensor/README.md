# Occupancy Sensor: XIAO nRF52840 + QMC5883L

## Hardware

- Seeed XIAO nRF52840 (plain, NOT Sense)
- QMC5883L magnetometer on GY-273 breakout

## Wiring

| GY-273 | XIAO |
|--------|------|
| VCC    | 3V3  |
| GND    | GND  |
| SDA    | D4   |
| SCL    | D5   |

No external pull-ups needed (breakout has them onboard).

## Flashing

1. Install Arduino IDE or PlatformIO.
2. Add the Seeed nRF52840 board package (URL: `https://files.seeedstudio.com/arduino/package_seeeduino_boards_index.json`).
3. Select board: "Seeed XIAO nRF52840".
4. Open `occupancy-sensor.ino`, compile, upload via USB-C.

## Calibration

On power-up, the sensor takes 10 magnetometer readings with no vehicle present and averages them as the baseline. Make sure no car is parked over the sensor when you power it on.

## Tuning

`THRESHOLD_UT` (default 30.0 µT) controls sensitivity. A vehicle at 1-2 feet produces tens of µT of distortion. Lower the threshold for higher sensitivity (more false positives from rebar, drain covers). Tune on-site with the actual demo vehicle.

## BLE Advertisement Format

Manufacturer data (9 bytes):
- Bytes 0-6: sensor ID (`occ-001`)
- Byte 7: type (`0x01` = occupancy)
- Byte 8: state (`0x00` = vacant, `0x01` = occupied)
