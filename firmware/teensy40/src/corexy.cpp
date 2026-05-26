#include "corexy.hpp"
#include "config.hpp"

#include <Arduino.h>

void CoreXYMotion::begin() {
  pinMode(cfg::PIN_A_STEP, OUTPUT);
  pinMode(cfg::PIN_A_DIR, OUTPUT);
  pinMode(cfg::PIN_A_EN, OUTPUT);
  pinMode(cfg::PIN_B_STEP, OUTPUT);
  pinMode(cfg::PIN_B_DIR, OUTPUT);
  pinMode(cfg::PIN_B_EN, OUTPUT);
  digitalWrite(cfg::PIN_A_STEP, LOW);
  digitalWrite(cfg::PIN_B_STEP, LOW);
  enableMotors(false);
}

void CoreXYMotion::enableMotors(bool enabled) {
  // TMC/Pololu-style EN is usually active-low.
  digitalWrite(cfg::PIN_A_EN, enabled ? LOW : HIGH);
  digitalWrite(cfg::PIN_B_EN, enabled ? LOW : HIGH);
}

MotorSteps CoreXYMotion::inverseKinematics(float dx_mm, float dy_mm) const {
  MotorSteps s;
  s.a = lroundf((dx_mm + dy_mm) * cfg::STEPS_PER_MM);
  s.b = lroundf((dx_mm - dy_mm) * cfg::STEPS_PER_MM);
  return s;
}

XY CoreXYMotion::squareCenter(const String& square) const {
  if (square.length() != 2) return {0, 0};
  int file = square.charAt(0) - 'a';
  int rank = square.charAt(1) - '1';
  return {
    cfg::ORIGIN_X_MM + (file + 0.5f) * cfg::SQUARE_MM,
    cfg::ORIGIN_Y_MM + (rank + 0.5f) * cfg::SQUARE_MM
  };
}

bool CoreXYMotion::home() {
  // Conservative placeholder homing: real build should move slowly until endstops trigger.
  // This keeps first firmware bring-up safe and avoids uncontrolled motion before pin verification.
  x_mm_ = 0.0f;
  y_mm_ = 0.0f;
  homed_ = true;
  return true;
}

void CoreXYMotion::stepBoth(long a_steps, long b_steps) {
  const bool a_dir = a_steps >= 0;
  const bool b_dir = b_steps >= 0;
  unsigned long a_total = labs(a_steps);
  unsigned long b_total = labs(b_steps);
  unsigned long total = max(a_total, b_total);

  if (total == 0) return;

  digitalWrite(cfg::PIN_A_DIR, a_dir ? HIGH : LOW);
  digitalWrite(cfg::PIN_B_DIR, b_dir ? HIGH : LOW);
  enableMotors(true);

  unsigned long a_accum = 0;
  unsigned long b_accum = 0;
  for (unsigned long i = 0; i < total; i++) {
    bool pulse_a = false;
    bool pulse_b = false;

    a_accum += a_total;
    if (a_accum >= total) {
      a_accum -= total;
      pulse_a = true;
    }

    b_accum += b_total;
    if (b_accum >= total) {
      b_accum -= total;
      pulse_b = true;
    }

    if (pulse_a) digitalWriteFast(cfg::PIN_A_STEP, HIGH);
    if (pulse_b) digitalWriteFast(cfg::PIN_B_STEP, HIGH);
    delayMicroseconds(cfg::STEP_PULSE_US);
    if (pulse_a) digitalWriteFast(cfg::PIN_A_STEP, LOW);
    if (pulse_b) digitalWriteFast(cfg::PIN_B_STEP, LOW);
    delayMicroseconds(cfg::STEP_INTERVAL_US);
  }
}

bool CoreXYMotion::moveTo(float x_mm, float y_mm) {
  if (!homed_) return false;
  float dx = x_mm - x_mm_;
  float dy = y_mm - y_mm_;
  MotorSteps s = inverseKinematics(dx, dy);
  stepBoth(s.a, s.b);
  x_mm_ = x_mm;
  y_mm_ = y_mm;
  return true;
}

bool CoreXYMotion::moveSquareToSquare(const String& from, const String& to) {
  XY src = squareCenter(from);
  XY dst = squareCenter(to);
  if (!moveTo(src.x, src.y)) return false;
  return moveTo(dst.x, dst.y);
}

bool CoreXYMotion::park() {
  if (!homed_) return false;
  return moveTo(0.0f, 0.0f);
}
