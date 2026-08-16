#pragma once
#include <Arduino.h>

// ─────────────────────────────────────────────
//  L298N 2A Dual H-Bridge — PIN DEFINITIONS
//  Two L298N modules wired for 4 mecanum motors
// ─────────────────────────────────────────────

// ── Motor Driver A (Left side) ──
#define FL_IN1  2   // Front-Left  direction A
#define FL_IN2  3   // Front-Left  direction B
#define FL_ENA  5   // Front-Left  PWM speed  (must be PWM pin)

#define RL_IN1  4   // Rear-Left   direction A
#define RL_IN2  6   // Rear-Left   direction B
#define RL_ENB  9   // Rear-Left   PWM speed  (must be PWM pin)

// ── Motor Driver B (Right side) ──
#define FR_IN1  7   // Front-Right direction A
#define FR_IN2  8   // Front-Right direction B
#define FR_ENA  10  // Front-Right PWM speed  (must be PWM pin)

#define RR_IN1  11  // Rear-Right  direction A
#define RR_IN2  12  // Rear-Right  direction B
#define RR_ENB  13  // Rear-Right  PWM speed  (must be PWM pin)

// E-STOP: GPIO driven LOW by Linux brain on obstacle
#define ESTOP_PIN A0

#define MAX_SPEED 255
#define MIN_SPEED 0

// ─────────────────────────────────────────────
//  Mecanum Kinematics
//  Standard X-configuration layout:
//
//    FL (/)   FR (\)
//    RL (\)   RR (/)
//
//  FL = Vy + Vx + ω
//  FR = Vy - Vx - ω
//  RL = Vy - Vx + ω
//  RR = Vy + Vx - ω
//
//  Vy = forward/back  [-255 .. 255]
//  Vx = strafe        [-255 .. 255]
//  omega = rotation   [-255 .. 255]
// ─────────────────────────────────────────────

void mecanum_init() {
  pinMode(FL_IN1, OUTPUT); pinMode(FL_IN2, OUTPUT); pinMode(FL_ENA, OUTPUT);
  pinMode(RL_IN1, OUTPUT); pinMode(RL_IN2, OUTPUT); pinMode(RL_ENB, OUTPUT);
  pinMode(FR_IN1, OUTPUT); pinMode(FR_IN2, OUTPUT); pinMode(FR_ENA, OUTPUT);
  pinMode(RR_IN1, OUTPUT); pinMode(RR_IN2, OUTPUT); pinMode(RR_ENB, OUTPUT);
  pinMode(ESTOP_PIN, INPUT_PULLUP);
}

// Drive a single motor: positive = forward, negative = backward, 0 = stop
static void drive_motor(uint8_t in1, uint8_t in2, uint8_t en, int speed) {
  speed = constrain(speed, -MAX_SPEED, MAX_SPEED);
  if (speed > 0) {
    digitalWrite(in1, HIGH);
    digitalWrite(in2, LOW);
    analogWrite(en, speed);
  } else if (speed < 0) {
    digitalWrite(in1, LOW);
    digitalWrite(in2, HIGH);
    analogWrite(en, -speed);
  } else {
    digitalWrite(in1, LOW);
    digitalWrite(in2, LOW);
    analogWrite(en, 0);
  }
}

// Core mecanum drive — call every loop with updated Vy, Vx, omega
void mecanum_drive(int vy, int vx, int omega) {
  // Check hardware e-stop first
  if (digitalRead(ESTOP_PIN) == LOW) {
    mecanum_stop();
    return;
  }

  int fl = vy + vx + omega;
  int fr = vy - vx - omega;
  int rl = vy - vx + omega;
  int rr = vy + vx - omega;

  // Scale down if any value exceeds MAX_SPEED (preserve direction ratio)
  int maxVal = max(max(abs(fl), abs(fr)), max(abs(rl), abs(rr)));
  if (maxVal > MAX_SPEED) {
    float scale = (float)MAX_SPEED / maxVal;
    fl = (int)(fl * scale);
    fr = (int)(fr * scale);
    rl = (int)(rl * scale);
    rr = (int)(rr * scale);
  }

  drive_motor(FL_IN1, FL_IN2, FL_ENA, fl);
  drive_motor(FR_IN1, FR_IN2, FR_ENA, fr);
  drive_motor(RL_IN1, RL_IN2, RL_ENB, rl);
  drive_motor(RR_IN1, RR_IN2, RR_ENB, rr);
}

void mecanum_stop() {
  drive_motor(FL_IN1, FL_IN2, FL_ENA, 0);
  drive_motor(FR_IN1, FR_IN2, FR_ENA, 0);
  drive_motor(RL_IN1, RL_IN2, RL_ENB, 0);
  drive_motor(RR_IN1, RR_IN2, RR_ENB, 0);
}

// Convenience wrappers
void mecanum_forward(int speed)  { mecanum_drive( speed,  0,  0); }
void mecanum_backward(int speed) { mecanum_drive(-speed,  0,  0); }
void mecanum_strafe_left(int s)  { mecanum_drive( 0, -s,  0); }
void mecanum_strafe_right(int s) { mecanum_drive( 0,  s,  0); }
void mecanum_rotate_cw(int s)    { mecanum_drive( 0,  0,  s); }
void mecanum_rotate_ccw(int s)   { mecanum_drive( 0,  0, -s); }
