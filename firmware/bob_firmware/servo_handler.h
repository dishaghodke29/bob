/*
 * BOB Firmware — Servo Handler
 * Add this header to bob_firmware.ino
 *
 * Controls a standard 50Hz PWM servo on SERVO_PIN.
 * Receives angle via serial JSON: {"cmd":"servo","angle":90.0}
 *
 * Pulse width: 544µs (0°) – 2400µs (180°)  [standard hobby servo]
 */

#pragma once
#include <Arduino.h>
#include <Servo.h>

// Servo signal pin — must be PWM-capable on your wiring
// Use pin A1 (free after motor pins are assigned)
#define SERVO_PIN      A1
#define SERVO_MIN_DEG  0
#define SERVO_MAX_DEG  180
#define SERVO_CENTRE   90

static Servo _servo;
static float _servo_angle = SERVO_CENTRE;

void servo_init() {
  _servo.attach(SERVO_PIN);
  _servo.write(SERVO_CENTRE);
  _servo_angle = SERVO_CENTRE;
}

void servo_set_angle(float angle) {
  angle = constrain(angle, SERVO_MIN_DEG, SERVO_MAX_DEG);
  _servo.write((int)angle);
  _servo_angle = angle;
}

float servo_get_angle() { return _servo_angle; }
