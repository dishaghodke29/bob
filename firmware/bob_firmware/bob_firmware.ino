/*
 * BOB Firmware — Main Sketch
 * Arduino UNO Q — Cortex-M33 (Zephyr / Arduino layer)
 *
 * Handles:
 *  • Mecanum wheel drive (L298N ×2, 4 motors)
 *  • MPU-6050 IMU (roll/pitch, drift correction)
 *  • Hardware e-stop GPIO (driven LOW by Linux brain)
 *  • Serial JSON protocol with Linux brain via /dev/ttyHS1
 *
 * Wiring summary:
 *  Motor Driver A  → FL motor (IN1=D2,IN2=D3,ENA=D5)  RL motor (IN1=D4,IN2=D6,ENB=D9)
 *  Motor Driver B  → FR motor (IN1=D7,IN2=D8,ENA=D10) RR motor (IN1=D11,IN2=D12,ENB=D13)
 *  MPU-6050        → SDA=A4, SCL=A5 (I2C)
 *  E-STOP GPIO     → A0 (INPUT_PULLUP — LOW = stop)
 */

#include "mecanum.h"
#include "mpu6050_handler.h"
#include "protocol.h"
#include "servo_handler.h"

// ── State ──────────────────────────────────
static bool g_estop        = false;
static bool g_imu_ok       = false;
static bool g_calibrated   = false;
static int  g_vy = 0, g_vx = 0, g_omega = 0;  // Current drive targets
static unsigned long g_last_cmd_ms = 0;
static const unsigned long CMD_TIMEOUT_MS = 500; // Auto-stop if no cmd for 500ms

// ──────────────────────────────────────────
void setup() {
  // 1. Init servo (camera gimbal)
  servo_init();

  // 2. Init serial protocol (115200 baud to Linux brain)
  protocol_init();

  // 2. Init motors (all stopped)
  mecanum_init();
  mecanum_stop();

  // 3. Init IMU
  g_imu_ok = mpu6050_init();
  if (g_imu_ok) {
    // Calibrate with 500 samples — robot must be stationary and flat
    mpu6050_calibrate(500);
    g_calibrated = true;
  }

  // 4. Announce ready
  Serial.println(F("{\"boot\":true,\"imu\":true,\"fw\":\"1.0.0\"}"));
}

// ──────────────────────────────────────────
void loop() {
  unsigned long now = millis();

  // ── 1. Check hardware e-stop ──
  g_estop = (digitalRead(ESTOP_PIN) == LOW);
  if (g_estop) {
    mecanum_stop();
    g_vy = g_vx = g_omega = 0;
  }

  // ── 2. Command timeout safety ──
  if (!g_estop && (now - g_last_cmd_ms > CMD_TIMEOUT_MS)) {
    if (g_vy != 0 || g_vx != 0 || g_omega != 0) {
      g_vy = g_vx = g_omega = 0;
      mecanum_stop();
    }
  }

  // ── 3. Read incoming commands from Linux brain ──
  Command cmd;
  if (protocol_read(cmd)) {
    g_last_cmd_ms = now;

    switch (cmd.type) {
      case CMD_MOVE:
        if (!g_estop) {
          g_vy    = constrain(cmd.vy,    -255, 255);
          g_vx    = constrain(cmd.vx,    -255, 255);
          g_omega = constrain(cmd.omega, -255, 255);
        }
        break;

      case CMD_STOP:
      case CMD_ESTOP:
        g_vy = g_vx = g_omega = 0;
        mecanum_stop();
        break;

      case CMD_CALIBRATE:
        mecanum_stop();
        if (g_imu_ok) {
          mpu6050_calibrate(500);
          g_calibrated = true;
          Serial.println(F("{\"calibrated\":true}"));
        }
        break;

      case CMD_SERVO: {
        // Angle is stored in vx field by protocol parser
        float angle = json_get_float(_cmd_buf, "angle", SERVO_CENTRE);
        servo_set_angle(angle);
        break;
      }

      case CMD_PING:
        protocol_pong();
        break;

      default: break;
    }
  }

  // ── 4. Apply drive (IMU drift correction on straight line) ──
  if (!g_estop) {
    int vy_corrected = g_vy;
    int vx_corrected = g_vx;
    int omega_corrected = g_omega;

    // Simple heading hold: if driving straight (no omega commanded),
    // use gyro Z to counteract unwanted rotation
    if (g_imu_ok && g_omega == 0 && (g_vy != 0 || g_vx != 0)) {
      const IMUData& imu = mpu6050_get();
      // gz > 0 = spinning CW → apply CCW correction
      int correction = (int)(imu.gz * 0.5f);
      correction = constrain(correction, -30, 30);
      omega_corrected = -correction;
    }

    mecanum_drive(vy_corrected, vx_corrected, omega_corrected);
  }

  // ── 5. Update IMU ──
  if (g_imu_ok) mpu6050_update();

  // ── 6. Send telemetry ──
  const IMUData& imu = mpu6050_get();
  protocol_send_telemetry(
    imu.roll, imu.pitch,
    imu.ax, imu.ay, imu.az,
    g_estop, g_imu_ok
  );
}
