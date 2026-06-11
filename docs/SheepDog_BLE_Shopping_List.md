# SheepDog BLE POC: Vetted Shopping List

*Compiled June 1, 2026. Every item checked for compatibility with the SheepDog architecture.*

---

## Quick summary

Two demos, three categories of parts. Total estimated spend: **$185–220.** Everything on Amazon, every item linked below.

### Amazon order list (all links)

| # | Item | Amazon link | Qty | Est. price |
|---|---|---|---|---|
| 1 | Feasycom FSC-BP105D beacon card | [B0GQLXMGT9](https://www.amazon.com/Feasycom-FSC-BP105D-Bluetooth-Eddystone-AltBeacon/dp/B0GQLXMGT9) | 5 (sold individually) | ~$12–18 ea |
| 2 | Seeed XIAO nRF52840 (plain, NOT Sense) | [B09T9VVQG7](https://www.amazon.com/Seeed-Studio-XIAO-nRF52840-Microcontroller/dp/B09T9VVQG7) | 2 | ~$10 ea |
| 3 | ACEIRMC QMC5883L GY-273 magnetometer (10-pack) | [B08Z3TLLGG](https://www.amazon.com/ACEIRMC-QMC5883L-Compass-Magnetometer-Accurancy/dp/B08Z3TLLGG) | 1 pack | ~$8–10 |
| 4 | Raspberry Pi 3 Model B+ (gateway) | [B0BNJPL4MW](https://www.amazon.com/Raspberry-Pi-Model-Board-Plus/dp/B0BNJPL4MW) | 1 | ~$52 |
| 5 | SanDisk 32GB MicroSD (for Pi) | [B08GY9NYRM](https://www.amazon.com/SanDisk-Ultra-microSDHC-Memory-Adapter/dp/B08GY9NYRM) | 1 | ~$8 |
| 6 | CanaKit 5V 2.5A Micro USB power supply (for Pi 3B+) | [B00MARDJZ4](https://www.amazon.com/CanaKit-Raspberry-Supply-Adapter-Listed/dp/B00MARDJZ4) | 1 | ~$10 |
| 7 | REXQualis 240pc jumper wire kit (M-F, M-M, F-F) | [B0F8VDMHRT](https://www.amazon.com/REXQualis-Rainbow-Breadboard-Compatible-Projects/dp/B0F8VDMHRT) | 1 | ~$7 |
| 8 | ELEGOO 400-point breadboard (6-pack) | [B0CYPVMK9J](https://www.amazon.com/ELEGOO-Breadboard-Solderless-Breadboards-Electronics/dp/B0CYPVMK9J) | 1 pack | ~$6 |
| 9 | Amazon Basics USB-C to USB-A cable 3ft (for XIAO) | [B085SBD8LC](https://www.amazon.com/AmazonBasics-USB-C-Cable-USB-IF-Certified/dp/B085SBD8LC) | 1 | ~$7 |
| 10 | Energizer CR2032 batteries (10-pack) | [B0CH1N7X5W](https://www.amazon.com/Energizer-2032-Batteries-Pack-Lithium/dp/B0CH1N7X5W) | 1 pack | ~$8 |

**Suggested order strategy:** Order 1 beacon card first. Confirm the FeasyBeacon app lets you set UUID/Major/Minor. Then order the remaining 4 plus everything else.

| Demo | What it proves | Needs gateway? |
|---|---|---|
| Hangtag (ePermit) | Beacon → iPad → Bird Dog pre-lookup | No. iPad reads beacons directly. |
| Occupancy sensor | Magnetometer detects car → gateway → iPad dashboard | Yes. One powered gateway per lot. |

---

## Demo 1: Hangtag Beacons (ePermit)

You need 5 pre-made iBeacon cards. These are the permit stand-ins. The iPad running Bird Dog reads them via CoreLocation iBeacon ranging.

### Recommended: Feasycom FSC-BP105D

| Detail | Value |
|---|---|
| Protocol | BLE 5.1, iBeacon + Eddystone + AltBeacon |
| Chipset | Dialog DA14531 |
| Configurable | UUID, Major, Minor via free FeasyBeacon app (password-protected) |
| Battery | CR2032 replaceable, ~6 years at default settings |
| Form factor | Credit-card thin, waterproof IP66 |
| Qty needed | 5 |
| Approx price | ~$12–18 each |
| Amazon | [Feasycom FSC-BP105D — B0GQLXMGT9](https://www.amazon.com/Feasycom-FSC-BP105D-Bluetooth-Eddystone-AltBeacon/dp/B0GQLXMGT9) |

**Why this one over MINEW:** Feasycom's card beacons are readily available on Amazon US with Prime shipping. The BP105D is the non-NFC version (cheaper, and NFC adds nothing here). Configurable UUID/Major/Minor is confirmed, which is what you need to encode permit IDs. The DA14531 chipset is well-proven for iBeacon.

**Alternative:** MINEW E8 tag beacon (~$6–10 each, nRF52832, keychain form factor instead of card). Smaller and cheaper but less like a parking hangtag. Available on [BeaconZone](https://www.beaconzone.co.uk/e8) or Alibaba. Not as easy to get on Amazon US.

**Alternative:** Feasycom FSC-BP105N (same as above but adds NFC, ~$15–20 each). Only worth it if you want NFC tap-to-configure in the field.

### Compatibility note (important)

iOS does NOT surface iBeacon data through CoreBluetooth. You must use **CoreLocation** (`CLBeaconRegion` / `CLBeaconIdentityConstraint` ranging). This is fine because Bird Dog is your own app and you control the code. You'll register for the beacon UUID and range for Major/Minor. The `BeaconPermitService` you specced already accounts for this. Just don't expect to see the iBeacon payload in generic BLE scanner apps on iOS (nRF Connect on iOS shows empty manufacturer data for iBeacons; that's normal Apple behavior, not a bug).

---

## Demo 2: Occupancy Sensor

### 2a. Microcontroller: Seeed XIAO nRF52840

| Detail | Value |
|---|---|
| Chip | Nordic nRF52840, BLE 5.0 |
| I2C pins | D4 (SDA), D5 (SCL) — Port 0 |
| Deep sleep | Spec: 5 µA. Realistic with care: 5–20 µA. |
| Voltage | 1.7V–5.5V input range (onboard regulator) |
| Qty needed | 2 (one sensor node + one spare) |
| Approx price | ~$10 each |
| Amazon | [Seeed XIAO nRF52840 — B09T9VVQG7](https://www.amazon.com/Seeed-Studio-XIAO-nRF52840-Microcontroller/dp/B09T9VVQG7) |

**Get the plain nRF52840, not the "Sense" variant.** The Sense adds an IMU and microphone you don't need, and the extra sensors draw extra sleep current. The plain version is what you want for a coin-cell-powered sensor.

### Power gotcha: CR2032 coin cell life

The XIAO has an onboard LDO regulator. Running from CR2032 (3.0V, ~230 mAh):

- At 5 µA deep sleep (best case): ~5 years theoretical, but the LDO quiescent current adds overhead.
- **Realistic for this POC: 3–6 months** with periodic wake, magnetometer read, and BLE advertise on change. That's fine for a demo. Production on Iota 800 MHz fixes this.
- To maximize life: disable the battery voltage divider (set P0.14 HIGH after reading), use Zephyr RTOS for proper deep-sleep management, and only advertise on state change (not continuously).

**For the demo, just power it via USB or a small LiPo.** Prove the concept works, don't fight coin-cell optimization yet. Coin-cell life is what Iota 800 MHz solves at production scale.

### 2b. Magnetometer: QMC5883L on GY-271 breakout

| Detail | Value |
|---|---|
| Chip | QMC5883L (HMC5883L is discontinued; GY-271 boards now ship QMC5883L) |
| I2C address | 0x0D (different from old HMC5883L at 0x1E — use the right library) |
| Voltage | 3.3V–5V on the GY-271 breakout (has onboard LDO + pull-ups) |
| Resolution | 16-bit ADC, up to 200 Hz |
| Qty needed | 2 (one + spare) |
| Approx price | ~$8–10 for a 10-pack |
| Amazon | [ACEIRMC 10-pack GY-273 QMC5883L — B08Z3TLLGG](https://www.amazon.com/ACEIRMC-QMC5883L-Compass-Magnetometer-Accurancy/dp/B08Z3TLLGG) |

**Wiring (4 wires):**

| GY-271 pin | XIAO nRF52840 pin |
|---|---|
| VCC | 3V3 |
| GND | GND |
| SDA | D4 |
| SCL | D5 |

No external pull-ups needed; the GY-271 breakout has them onboard.

**Vehicle detection approach:** Calibrate the ambient magnetic field with no vehicle present. A vehicle's ferrous mass (engine, wheels) distorts the field measurably at 1–2 feet. Set a threshold on the magnitude change. The magnetometer reads on wake, compares to baseline, and if the delta exceeds threshold, broadcasts "occupied." On departure, the field returns to baseline and it broadcasts "vacant." This is the same principle commercial parking pucks use (Nwave, BoschPLS, etc.).

**Gotcha: mounting matters.** The sensor should be flush-mounted at ground level in the center of the parking space, away from rebar and metal drain covers. For the demo, duct-taping it to the pavement surface works. Production would be epoxied into a small puck housing.

### 2c. Gateway: Raspberry Pi 3 Model B+

| Detail | Value |
|---|---|
| What it does | Sits powered in the lot, listens for BLE advertisements from occupancy sensors, relays state over WiFi to the iPad |
| Connectivity | BLE 4.2 (built-in) + WiFi 802.11ac 2.4/5GHz (built-in) + Ethernet |
| Power | USB micro, always-on, ~500 mA idle |
| RAM | 1 GB |
| Qty needed | 1 |
| Price | ~$52 |
| Amazon | [Raspberry Pi 3 Model B+ — B0BNJPL4MW](https://www.amazon.com/Raspberry-Pi-Model-Board-Plus/dp/B0BNJPL4MW) |

**Why the 3B+ instead of Pi Zero 2 W:** The Zero 2 W ($15 MSRP) is perpetually out of stock or scalper-priced on Amazon. The 3B+ costs more but is readily available, has the same BLE + WiFi, uses the same micro USB power connector, and takes the same microSD card. For a plugged-in gateway, the bigger board and higher idle draw don't matter.

**You also need for the Pi:**

| Item | Why | Approx price |
|---|---|---|
| MicroSD card (16+ GB) | OS and gateway software | ~$8 |
| USB micro power supply (5V 2.5A) | Power the Pi | ~$10 (or any phone charger) |
| MicroSD card reader | Flash the OS | ~$5 (you probably have one) |

**Gateway software approach:** Run a lightweight Python script using `bleak` (BLE library) to listen for the XIAO's advertisements. On state change, POST a JSON payload (`{ sensorId, type, payload, rssi, timestamp }`) to the iPad's IP on the lot WiFi. No MQTT broker needed for the POC. The Pi is just a BLE-to-HTTP bridge.

**Alternative: ESP32-C3 mini (~$5).** Cheaper, lower power, smaller, also has BLE + WiFi. But: less flexible to program, no full Linux, harder to debug. The Pi 3B+ is worth it for a POC because you can SSH in, run Python, and iterate fast. Switch to ESP32 for production if power/size matters.

---

## Wiring and accessories

| Item | Amazon link | Qty | Approx price | Notes |
|---|---|---|---|---|
| REXQualis 240pc jumper wire kit | [B0F8VDMHRT](https://www.amazon.com/REXQualis-Rainbow-Breadboard-Compatible-Projects/dp/B0F8VDMHRT) | 1 | ~$7 | Includes M-F, M-M, F-F in 10cm and 20cm lengths. Covers all wiring needs. |
| ELEGOO 400-point breadboard (6-pack) | [B0CYPVMK9J](https://www.amazon.com/ELEGOO-Breadboard-Solderless-Breadboards-Electronics/dp/B0CYPVMK9J) | 1 pack | ~$6 | Self-adhesive, interlocking. 6 boards so you have spares. |
| Energizer CR2032 (10-pack) | [B0CH1N7X5W](https://www.amazon.com/Energizer-2032-Batteries-Pack-Lithium/dp/B0CH1N7X5W) | 1 pack | ~$8 | Beacon cards ship with one battery each. These are spares + for XIAO coin-cell testing later. |
| Amazon Basics USB-C to USB-A 3ft | [B085SBD8LC](https://www.amazon.com/AmazonBasics-USB-C-Cable-USB-IF-Certified/dp/B085SBD8LC) | 1 | ~$7 | Data + power. For programming the XIAO. |
| SanDisk 32GB MicroSD | [B08GY9NYRM](https://www.amazon.com/SanDisk-Ultra-microSDHC-Memory-Adapter/dp/B08GY9NYRM) | 1 | ~$8 | For the Pi 3 Model B+. Comes with adapter. |
| CanaKit 5V 2.5A Micro USB power supply | [B00MARDJZ4](https://www.amazon.com/CanaKit-Raspberry-Supply-Adapter-Listed/dp/B00MARDJZ4) | 1 | ~$10 | UL-listed, works with Pi 3B+ (micro USB). Has inline switch. |

---

## Total BOM

| Category | Items | Est. cost |
|---|---|---|
| Hangtag beacons | 5x Feasycom FSC-BP105D | $60–90 |
| Occupancy MCU | 2x Seeed XIAO nRF52840 | $20 |
| Magnetometer | 2x QMC5883L GY-271 breakout (or a 5-pack) | $5–10 |
| Gateway | 1x Raspberry Pi 3 Model B+ | $52 |
| Wiring/accessories | Jumper kit, breadboard 6-pack, CR2032 10-pack, USB-C cable, MicroSD, Pi power supply | $40–50 |
| **Total** | | **$185–220** |

---

## What to buy first (if you want to phase it)

**Phase 1 (~$75): Hangtag demo only.** Buy 5 beacon cards + CR2032 batteries. The iPad you already have is the reader. Write `BeaconPermitService`, register for the beacon UUID in CoreLocation, and demo permit pre-lookup before OCR fires. No gateway, no magnetometer, no extra hardware.

**Phase 2 (~$110–145): Occupancy demo.** Buy 2x XIAO, 1x GY-273 10-pack, 1x Pi 3 Model B+, MicroSD card, Pi power supply, jumper wire kit, breadboard pack, USB-C cable. Wire the sensor, write the firmware, set up the gateway script, and demo the dashboard flip.

---

## Risk register (things that could bite you)

| Risk | Severity | Mitigation |
|---|---|---|
| Beacon cards arrive with firmware that doesn't let you set UUID/Major/Minor | Medium | Feasycom's FeasyBeacon app is documented and confirmed configurable. Test one card before buying 5. Consider buying 1 first. |
| iOS iBeacon ranging requires foreground or background-mode app | Low | Bird Dog is your app; add `location` background mode to Info.plist. Ranging works in background but monitoring (region enter/exit) is more reliable for always-on. |
| QMC5883L library confusion with HMC5883L | Medium | Use a QMC5883L-specific library (I2C address 0x0D). Do NOT use HMC5883L libraries (address 0x1E). The chips share a board layout but are different ICs. |
| Magnetometer sensitivity varies with mounting | Medium | Calibrate on-site with and without a vehicle. The delta should be large (tens of µT) for a car at 1–2 feet. Test with the actual demo vehicle before the demo day. |
| Pi Zero 2 W out of stock | ~~Low~~ Happened | Replaced with Pi 3 Model B+ ($52). Same BLE+WiFi, same micro USB power, same microSD. Bigger and draws more power but that's irrelevant for a plugged-in gateway. |
| XIAO deep sleep current higher than spec | Low (for POC) | Doesn't matter for demo; power via USB. Only matters for production coin-cell deployment, which is the Iota transition. |
