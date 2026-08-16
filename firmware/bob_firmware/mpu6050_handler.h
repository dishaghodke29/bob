#pragma once
#include <Arduino.h>
#include <Wire.h>

// ─────────────────────────────────────────────
//  MPU-6050  I2C Addresses
// ─────────────────────────────────────────────
#define MPU6050_ADDR        0x68   // AD0 = LOW (default)
#define MPU6050_ADDR_ALT    0x69   // AD0 = HIGH

// MPU-6050 Register Map
#define MPU_PWR_MGMT_1      0x6B
#define MPU_ACCEL_XOUT_H    0x3B
#define MPU_GYRO_XOUT_H     0x43
#define MPU_CONFIG          0x1A
#define MPU_GYRO_CONFIG     0x1B
#define MPU_ACCEL_CONFIG    0x1C
#define MPU_SMPLRT_DIV      0x19

// Scale factors
#define ACCEL_SCALE  16384.0f   // ±2g  → LSB/g
#define GYRO_SCALE     131.0f  // ±250°/s → LSB/(°/s)

// Complementary filter coefficient (0.98 = favour gyro)
#define COMP_ALPHA      0.98f

struct IMUData {
  float ax, ay, az;     // Acceleration (g)
  float gx, gy, gz;     // Gyro rate (°/s)
  float roll, pitch;    // Fused orientation (°)
  bool  ok;             // Sensor healthy flag
};

static IMUData _imu;
static unsigned long _imu_last_ms = 0;

// ─── Calibration offsets (run calibrate() once at setup) ───
static float _ax_off = 0, _ay_off = 0, _az_off = 0;
static float _gx_off = 0, _gy_off = 0, _gz_off = 0;

static void mpu_write(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(reg);
  Wire.write(val);
  Wire.endTransmission(true);
}

static int16_t mpu_read16(uint8_t reg) {
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(reg);
  Wire.endTransmission(false);
  Wire.requestFrom((uint8_t)MPU6050_ADDR, (uint8_t)2, (uint8_t)true);
  return (Wire.read() << 8) | Wire.read();
}

bool mpu6050_init() {
  Wire.begin();
  Wire.setClock(400000);  // 400kHz fast mode

  // Wake up MPU-6050 (clear sleep bit)
  mpu_write(MPU_PWR_MGMT_1, 0x00);
  delay(100);

  // Sample rate 1kHz / (1+9) = 100Hz
  mpu_write(MPU_SMPLRT_DIV, 0x09);
  // DLPF bandwidth ~94Hz
  mpu_write(MPU_CONFIG, 0x02);
  // Gyro ±250°/s
  mpu_write(MPU_GYRO_CONFIG, 0x00);
  // Accel ±2g
  mpu_write(MPU_ACCEL_CONFIG, 0x00);

  // Verify WHO_AM_I register (0x75) should return 0x68
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(0x75);
  Wire.endTransmission(false);
  Wire.requestFrom((uint8_t)MPU6050_ADDR, (uint8_t)1, (uint8_t)true);
  uint8_t who = Wire.read();
  _imu.ok = (who == 0x68);
  _imu_last_ms = millis();
  return _imu.ok;
}

// Calibration: robot must be flat and still — averages 500 samples
void mpu6050_calibrate(int samples = 500) {
  float sax=0,say=0,saz=0,sgx=0,sgy=0,sgz=0;
  for (int i = 0; i < samples; i++) {
    sax += mpu_read16(MPU_ACCEL_XOUT_H)     / ACCEL_SCALE;
    say += mpu_read16(MPU_ACCEL_XOUT_H + 2) / ACCEL_SCALE;
    saz += mpu_read16(MPU_ACCEL_XOUT_H + 4) / ACCEL_SCALE;
    sgx += mpu_read16(MPU_GYRO_XOUT_H)      / GYRO_SCALE;
    sgy += mpu_read16(MPU_GYRO_XOUT_H + 2)  / GYRO_SCALE;
    sgz += mpu_read16(MPU_GYRO_XOUT_H + 4)  / GYRO_SCALE;
    delay(2);
  }
  _ax_off = sax/samples; _ay_off = say/samples;
  _az_off = (saz/samples) - 1.0f;  // subtract 1g gravity
  _gx_off = sgx/samples; _gy_off = sgy/samples; _gz_off = sgz/samples;
}

// Update IMU — call every loop. Returns reference to updated IMUData.
const IMUData& mpu6050_update() {
  if (!_imu.ok) return _imu;

  unsigned long now = millis();
  float dt = (now - _imu_last_ms) / 1000.0f;
  if (dt <= 0) return _imu;
  _imu_last_ms = now;

  // Raw readings
  float ax = mpu_read16(MPU_ACCEL_XOUT_H)     / ACCEL_SCALE - _ax_off;
  float ay = mpu_read16(MPU_ACCEL_XOUT_H + 2) / ACCEL_SCALE - _ay_off;
  float az = mpu_read16(MPU_ACCEL_XOUT_H + 4) / ACCEL_SCALE - _az_off;
  float gx = mpu_read16(MPU_GYRO_XOUT_H)      / GYRO_SCALE  - _gx_off;
  float gy = mpu_read16(MPU_GYRO_XOUT_H + 2)  / GYRO_SCALE  - _gy_off;
  float gz = mpu_read16(MPU_GYRO_XOUT_H + 4)  / GYRO_SCALE  - _gz_off;

  _imu.ax = ax; _imu.ay = ay; _imu.az = az;
  _imu.gx = gx; _imu.gy = gy; _imu.gz = gz;

  // Accel-derived angles
  float roll_acc  = atan2(ay, az) * 180.0f / PI;
  float pitch_acc = atan2(-ax, sqrt(ay*ay + az*az)) * 180.0f / PI;

  // Complementary filter: blend gyro integration with accel correction
  _imu.roll  = COMP_ALPHA * (_imu.roll  + gx * dt) + (1.0f - COMP_ALPHA) * roll_acc;
  _imu.pitch = COMP_ALPHA * (_imu.pitch + gy * dt) + (1.0f - COMP_ALPHA) * pitch_acc;

  return _imu;
}

const IMUData& mpu6050_get() { return _imu; }
