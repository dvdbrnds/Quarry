// SheepDog Occupancy Sensor — Production Firmware
// Hardware: Seeed XIAO nRF52840 + Adafruit QMC5883P magnetometer
// Broadcasts occupancy state via BLE manufacturer-specific advertisements.
//
// TODO (production): Store baseline in flash and support recalibration
// commands over BLE or GPIO trigger. Current baseline lives in RAM and
// resets on every power cycle.

#include <Wire.h>
#include <bluefruit.h>

// ── Configuration ────────────────────────────────────────────────────
#define SENSOR_ID             "A-001"  // 7 chars max — lot prefix + spot number (change per puck at flash time)
#define SENSOR_TYPE           0x01     // message type: occupancy

#define QMC_ADDR              0x2C
#define OCCUPANCY_THRESHOLD   200.0
#define SLEEP_INTERVAL        3       // seconds between magnetometer reads
#define CALIBRATION_SAMPLES   20
#define ADV_SECONDS           5       // how long to advertise after a state change
#define ADV_INTERVAL_UNITS    160     // 160 × 0.625ms = 100ms between advertisement packets

// ── LED helpers (active LOW on XIAO) ─────────────────────────────────
void showColor(bool r, bool g, bool b) {
  digitalWrite(LED_RED,   r ? LOW : HIGH);
  digitalWrite(LED_GREEN, g ? LOW : HIGH);
  digitalWrite(LED_BLUE,  b ? LOW : HIGH);
}

void ledsOff() { showColor(false, false, false); }

// ── Magnetometer ─────────────────────────────────────────────────────
bool initMagnetometer() {
  Wire.beginTransmission(QMC_ADDR);
  if (Wire.endTransmission() != 0) return false;

  // SET/RESET period
  Wire.beginTransmission(QMC_ADDR);
  Wire.write(0x0D); Wire.write(0x40);
  Wire.endTransmission();
  delay(10);

  // Continuous measurement mode
  Wire.beginTransmission(QMC_ADDR);
  Wire.write(0x0A); Wire.write(0x01);
  Wire.endTransmission();
  delay(10);

  // 10Hz ODR, 2G range, 64× oversampling
  Wire.beginTransmission(QMC_ADDR);
  Wire.write(0x0B); Wire.write(0x00);
  Wire.endTransmission();
  delay(100);

  return true;
}

bool readMagnetometer(int16_t &x, int16_t &y, int16_t &z) {
  Wire.beginTransmission(QMC_ADDR);
  if (Wire.endTransmission() != 0) return false;

  Wire.beginTransmission(QMC_ADDR);
  Wire.write(0x01);
  Wire.endTransmission();

  if (Wire.requestFrom(QMC_ADDR, (uint8_t)6) < 6) return false;

  x = Wire.read() | (Wire.read() << 8);
  y = Wire.read() | (Wire.read() << 8);
  z = Wire.read() | (Wire.read() << 8);
  return true;
}

float computeMagnitude(int16_t x, int16_t y, int16_t z) {
  return sqrt((float)x * x + (float)y * y + (float)z * z);
}

// ── Calibration ──────────────────────────────────────────────────────
float   baseline       = 0;
int     calCount       = 0;
float   calAccumulator = 0;
bool    calibrated     = false;

bool calibrateBaseline() {
  int16_t x, y, z;

  for (int i = 0; i < CALIBRATION_SAMPLES; i++) {
    if (!readMagnetometer(x, y, z))           return false;
    if (x == 0 && y == 0 && z == 0)           return false;
    calAccumulator += computeMagnitude(x, y, z);
    delay(110); // slightly longer than 10Hz sample period
  }

  baseline   = calAccumulator / CALIBRATION_SAMPLES;
  calibrated = true;
  return true;
}

// ── BLE advertising ──────────────────────────────────────────────────
//
// Manufacturer-specific data layout (11 bytes on the wire):
//   Bytes 0–1: BLE company ID  (0xFFFF = unregistered/test)
//   Bytes 2–8: sensor ID ASCII (from SENSOR_ID define, e.g. "A-001")
//   Byte  9:   message type    (SENSOR_TYPE, 0x01 = occupancy)
//   Byte  10:  state           (0x00 = vacant, 0x01 = occupied)
//
// The gateway strips the company ID and parses bytes 2–10 as the
// 9-byte payload defined in the SheepDog data contract.

uint8_t mfgData[11];

void buildMfgData(uint8_t state) {
  mfgData[0]  = 0xFF;        // company ID low  (unregistered)
  mfgData[1]  = 0xFF;        // company ID high
  memset(&mfgData[2], 0, 7); // zero-fill before copy (pad short IDs)
  memcpy(&mfgData[2], SENSOR_ID, min((size_t)7, strlen(SENSOR_ID)));
  mfgData[9]  = SENSOR_TYPE;
  mfgData[10] = state;       // 0x00 = vacant, 0x01 = occupied
}

void setupBLE() {
  Bluefruit.begin();
  Bluefruit.setTxPower(4);
  Bluefruit.setName("SheepDog");

  Bluefruit.Advertising.setType(BLE_GAP_ADV_TYPE_NONCONNECTABLE_NONSCANNABLE_UNDIRECTED);
  Bluefruit.Advertising.setInterval(ADV_INTERVAL_UNITS, ADV_INTERVAL_UNITS);
  Bluefruit.Advertising.setFastTimeout(ADV_SECONDS);
  Bluefruit.Advertising.restartOnDisconnect(false);
}

void advertiseState(uint8_t state) {
  Bluefruit.Advertising.stop();
  Bluefruit.Advertising.clearData();

  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  buildMfgData(state);
  Bluefruit.Advertising.addData(BLE_GAP_AD_TYPE_MANUFACTURER_SPECIFIC_DATA, mfgData, sizeof(mfgData));

  Bluefruit.Advertising.start(ADV_SECONDS);
}

// ── State tracking ───────────────────────────────────────────────────
bool     occupied     = false;
bool     stateKnown   = false; // false until first reading after calibration

// ── Setup ────────────────────────────────────────────────────────────
void setup() {
  pinMode(LED_RED,   OUTPUT);
  pinMode(LED_GREEN, OUTPUT);
  pinMode(LED_BLUE,  OUTPUT);
  showColor(true, false, false); // RED while initializing

  Wire.begin();
  Wire.setClock(100000);
  delay(500);

  if (!initMagnetometer()) {
    showColor(true, false, false); // RED = sensor not found
    while (true) delay(1000);      // halt; power-cycle to retry
  }

  showColor(true, true, false); // YELLOW = calibrating
  if (!calibrateBaseline()) {
    showColor(true, false, true); // PURPLE = calibration failed (zeros or read error)
    while (true) delay(1000);
  }

  setupBLE();

  showColor(false, true, false); // GREEN = ready, space assumed vacant
}

// ── Main loop ────────────────────────────────────────────────────────
// Each iteration: read sensor → compare to baseline → advertise on
// state change → low-power sleep.
//
// delay() on nRF52 + FreeRTOS uses tickless idle (WFE), keeping power
// draw in the low-µA range while sleeping. For production coin-cell
// deployments, consider System OFF with an RTC alarm for wake-up.

void loop() {
  int16_t x, y, z;

  if (!readMagnetometer(x, y, z)) {
    showColor(true, false, false); // RED = read failure
    delay(SLEEP_INTERVAL * 1000);
    return;
  }

  if (x == 0 && y == 0 && z == 0) {
    showColor(true, false, true); // PURPLE = sensor returning zeros
    delay(SLEEP_INTERVAL * 1000);
    return;
  }

  float mag   = computeMagnitude(x, y, z);
  float delta = fabs(mag - baseline);
  bool  nowOccupied = (delta > OCCUPANCY_THRESHOLD);

  if (!stateKnown || nowOccupied != occupied) {
    occupied   = nowOccupied;
    stateKnown = true;

    if (occupied) {
      showColor(false, false, true); // BLUE = occupied
    } else {
      showColor(false, true, false); // GREEN = vacant
    }

    advertiseState(occupied ? 0x01 : 0x00);
  }

  // delay() with SoftDevice active → CPU enters WFE between RTOS ticks
  delay(SLEEP_INTERVAL * 1000);
}
