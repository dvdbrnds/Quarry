/**
 * SheepDog Occupancy Sensor
 *
 * Hardware: Seeed XIAO nRF52840 + QMC5883L magnetometer (GY-273 breakout)
 * Wiring:   VCC→3V3, GND→GND, SDA→D4, SCL→D5
 *
 * Reads the magnetic field, compares to a calibrated baseline,
 * and BLE-advertises "occupied" or "vacant" on state change.
 *
 * I2C address: 0x0D (QMC5883L, NOT 0x1E which is the old HMC5883L)
 */

#include <Wire.h>
#include <bluefruit.h>

// QMC5883L registers
#define QMC5883L_ADDR   0x0D
#define QMC5883L_DATA   0x00  // X LSB through Z MSB (6 bytes)
#define QMC5883L_STATUS 0x06
#define QMC5883L_CTRL1  0x09
#define QMC5883L_CTRL2  0x0A
#define QMC5883L_SETPERIOD 0x0B

// Sensor config
const float THRESHOLD_UT = 30.0;        // µT delta to trigger occupied (tune on-site)
const unsigned long READ_INTERVAL = 2000; // ms between reads
const char* SENSOR_ID = "occ-001";

// Manufacturer data format: [sensorId(7), type(1), state(1)]
// type: 0x01 = occupancy
// state: 0x01 = occupied, 0x00 = vacant
uint8_t mfgData[] = {
  'o','c','c','-','0','0','1',  // sensorId (7 bytes)
  0x01,                          // type: occupancy
  0x00                           // state: vacant
};

// Baseline magnetic field (calibrated with no vehicle)
float baselineX = 0, baselineY = 0, baselineZ = 0;
bool baselineSet = false;
bool currentlyOccupied = false;

BLEAdvertising* pAdvertising;

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("SheepDog Occupancy Sensor starting...");

  // I2C
  Wire.begin();
  initQMC5883L();

  // BLE
  Bluefruit.begin();
  Bluefruit.setName("SheepDog-OCC-001");
  Bluefruit.setTxPower(4);  // range vs battery tradeoff

  // Calibrate baseline (average of first 10 readings)
  calibrateBaseline();

  // Start advertising
  startAdvertising();

  Serial.println("Ready. Monitoring for vehicle presence...");
}

void loop() {
  float x, y, z;
  if (readMagnetometer(&x, &y, &z)) {
    float deltaX = x - baselineX;
    float deltaY = y - baselineY;
    float deltaZ = z - baselineZ;
    float magnitude = sqrt(deltaX*deltaX + deltaY*deltaY + deltaZ*deltaZ);

    bool occupied = (magnitude > THRESHOLD_UT);

    Serial.print("Field delta: ");
    Serial.print(magnitude, 1);
    Serial.print(" µT → ");
    Serial.println(occupied ? "OCCUPIED" : "VACANT");

    if (occupied != currentlyOccupied) {
      currentlyOccupied = occupied;
      mfgData[8] = occupied ? 0x01 : 0x00;
      updateAdvertising();
      Serial.println("*** STATE CHANGE ***");
    }
  }

  delay(READ_INTERVAL);
}

// --- QMC5883L Functions ---

void initQMC5883L() {
  // Soft reset
  writeReg(QMC5883L_CTRL2, 0x80);
  delay(50);

  // Set/Reset period
  writeReg(QMC5883L_SETPERIOD, 0x01);

  // Continuous mode, 200Hz, 8G range, 512 oversampling
  writeReg(QMC5883L_CTRL1, 0x1D);
  delay(10);

  Serial.println("QMC5883L initialized at 0x0D");
}

bool readMagnetometer(float* x, float* y, float* z) {
  Wire.beginTransmission(QMC5883L_ADDR);
  Wire.write(QMC5883L_DATA);
  Wire.endTransmission();

  Wire.requestFrom(QMC5883L_ADDR, 6);
  if (Wire.available() < 6) return false;

  int16_t rawX = Wire.read() | (Wire.read() << 8);
  int16_t rawY = Wire.read() | (Wire.read() << 8);
  int16_t rawZ = Wire.read() | (Wire.read() << 8);

  // 8 Gauss range: 3000 LSB/Gauss, 1 Gauss = 100 µT
  *x = rawX / 30.0;  // convert to µT
  *y = rawY / 30.0;
  *z = rawZ / 30.0;

  return true;
}

void calibrateBaseline() {
  Serial.println("Calibrating baseline (no vehicle should be present)...");
  float sumX = 0, sumY = 0, sumZ = 0;
  int count = 0;

  for (int i = 0; i < 10; i++) {
    float x, y, z;
    if (readMagnetometer(&x, &y, &z)) {
      sumX += x;
      sumY += y;
      sumZ += z;
      count++;
    }
    delay(200);
  }

  if (count > 0) {
    baselineX = sumX / count;
    baselineY = sumY / count;
    baselineZ = sumZ / count;
    baselineSet = true;
    Serial.print("Baseline set: ");
    Serial.print(baselineX, 1); Serial.print(", ");
    Serial.print(baselineY, 1); Serial.print(", ");
    Serial.println(baselineZ, 1);
  } else {
    Serial.println("ERROR: Could not read magnetometer during calibration!");
  }
}

void writeReg(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(QMC5883L_ADDR);
  Wire.write(reg);
  Wire.write(val);
  Wire.endTransmission();
}

// --- BLE Functions ---

void startAdvertising() {
  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  Bluefruit.Advertising.addManufacturerData(mfgData, sizeof(mfgData));
  Bluefruit.Advertising.restartOnDisconnect(true);
  Bluefruit.Advertising.setInterval(160, 244);  // 100-152.5ms
  Bluefruit.Advertising.setFastTimeout(30);
  Bluefruit.Advertising.start(0);  // advertise forever
}

void updateAdvertising() {
  Bluefruit.Advertising.stop();
  Bluefruit.Advertising.clearData();
  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  Bluefruit.Advertising.addManufacturerData(mfgData, sizeof(mfgData));
  Bluefruit.Advertising.start(0);
}
