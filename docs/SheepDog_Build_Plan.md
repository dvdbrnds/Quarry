# SheepDog POC: Build Plan

*Scene-by-scene build sequence. Scenes 1–3 need zero breadboard work. Scenes 4–7 are the hardware build. Scenes 3 and 7 are the only ones that touch Bird Dog code.*

---

## Scene 1: Gateway software

Pi is running, you're SSH'd in.

```bash
sudo apt update && sudo apt install -y python3-pip
pip3 install bleak --break-system-packages
```

Confirm the Pi can scan for BLE devices:

```bash
sudo hciconfig hci0 up
bluetoothctl scan on
```

You should see nearby BLE traffic scrolling. This proves the radio works. Ctrl-C out.

---

## Scene 2: Configure the beacon cards

Open one Feasycom FSC-BP105D. Download the **FeasyBeacon** app on your iPhone or iPad. Connect to the card and set:

- Mode: iBeacon
- UUID: one UUID for all Moravian permits (pick any valid UUID, use the same one across all 5 cards)
- Major: 1 (or a lot/zone ID)
- Minor: a permit number (e.g. 4471, 4472, etc.)

Each card = one fake permit. Do this for all 5 cards.

---

## Scene 3: Bird Dog reads beacons (Demo 1)

Write `BeaconPermitService` in the Bird Dog app.

1. Register for the beacon UUID via CoreLocation (`CLBeaconRegion` / `CLBeaconIdentityConstraint`).
2. Range for Major/Minor as the cart moves through the lot.
3. Map beacon ID → permit record in SwiftData.
4. Inject the result into `PlateAuthService` before OCR fires. The plate scan becomes confirmation, not lookup.

**Test:** hold a beacon card near the iPad, watch the permit pre-load.

**Demo 1 is complete.** Beacon in windshield → iPad reads it on approach → permit pre-loads → OCR confirms the plate.

---

## Scene 4: Wire the occupancy sensor

**Parts:** 1x breadboard, 1x XIAO nRF52840, 1x QMC5883L GY-273 breakout, 4x jumper wires (female-to-female or male-to-female depending on headers).

Seat the XIAO on the breadboard. Four wires from the magnetometer breakout:

| GY-273 pin | XIAO pin |
|---|---|
| VCC | 3V3 |
| GND | GND |
| SDA | D4 |
| SCL | D5 |

No external pull-ups needed (the breakout has them onboard).

Plug the XIAO into your Mac via USB-C. That's the hardware.

---

## Scene 5: Flash the XIAO firmware

Arduino IDE or PlatformIO. Install the **Seeed nRF52840 board package**.

The sketch:

1. Wake from sleep.
2. Read the QMC5883L via I2C (address **0x0D**, use a QMC5883L-specific library, **not** HMC5883L).
3. Compute the magnetic field magnitude.
4. Compare to a stored baseline (calibrated with no vehicle present).
5. If delta exceeds threshold → BLE-advertise "occupied."
6. Below threshold → BLE-advertise "vacant."
7. Advertise as manufacturer-specific data with `sensorId`, `type`, and `payload` in the advertisement bytes.
8. Sleep until next read interval.

**Test:** hold a wrench or heavy steel object near the sensor, watch the serial monitor flip between occupied and vacant.

**Gotcha:** the QMC5883L I2C address is 0x0D. The old HMC5883L was 0x1E. They share a board layout but are different chips. Use the right library.

---

## Scene 6: Gateway script on the Pi

Python script using `bleak`. Runs on the Pi, always on.

1. Scan for the XIAO's BLE advertisements (filter on MAC address or manufacturer data prefix).
2. Parse `sensorId`, `type`, `payload` from the advertisement bytes.
3. On state change, POST JSON to the iPad's IP on the lot WiFi:

```json
{
  "sensorId": "occ-001",
  "type": "occupancy",
  "payload": "occupied",
  "rssi": -42,
  "timestamp": "2026-06-08T14:30:00Z"
}
```

No MQTT broker. The Pi is just a BLE-to-HTTP bridge.

**Test from your desk:** run the script, move metal near the sensor, confirm the Pi picks up the BLE advertisement and fires the HTTP POST.

---

## Scene 7: Bird Dog receives occupancy (Demo 2)

Add an HTTP listener in Bird Dog's admin mode (or a simple endpoint the gateway POSTs to).

1. Parse the incoming JSON.
2. Update the lot/space model in SwiftData.
3. Surface occupied/vacant in the admin UI.

**Test:** metal near sensor → XIAO advertises → Pi relays → iPad dashboard flips.

**Demo 2 is complete.** Sensor detects vehicle → gateway relays → dashboard updates in real time, no camera, no officer present.

---

## Scene 8: Full dress rehearsal

Take it to a parking lot.

- 5 beacon cards in 5 windshields (hangtag permits).
- Occupancy sensor duct-taped to pavement in one space.
- Pi gateway plugged into an outdoor outlet (or running off a USB battery pack).
- iPad on the golf cart running Bird Dog.

Drive the cart past the beacons: permits pre-load before you even scan. Park a car on the sensor: dashboard flips to occupied. Pull the car out: flips back to vacant.

Both demos, one run.

---

## Reference

| Scene | Touches hardware? | Touches Bird Dog code? | Depends on |
|---|---|---|---|
| 1. Gateway software | No (Pi only) | No | Pi running |
| 2. Configure beacons | No (app config) | No | Beacon cards arrived |
| 3. BeaconPermitService | No | Yes | Scene 2 |
| 4. Wire occupancy sensor | Yes (breadboard) | No | Parts arrived |
| 5. Flash XIAO firmware | Yes (USB flash) | No | Scene 4 |
| 6. Gateway script | No (Pi only) | No | Scenes 1, 5 |
| 7. Occupancy in Bird Dog | No | Yes | Scene 6 |
| 8. Dress rehearsal | Outdoor setup | No | All scenes |
