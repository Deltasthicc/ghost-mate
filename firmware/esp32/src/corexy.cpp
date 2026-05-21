#include "corexy.hpp"
#include "config.hpp"
#include "safety.hpp"

#include <FastAccelStepper.h>

static FastAccelStepperEngine engine;
static FastAccelStepper* stepperA = nullptr;
static FastAccelStepper* stepperB = nullptr;

void CoreXYMotion::begin() {
  engine.init();
  stepperA = engine.stepperConnectToPin(cfg::PIN_A_STEP);
  stepperB = engine.stepperConnectToPin(cfg::PIN_B_STEP);

  if (stepperA) {
    stepperA->setDirectionPin(cfg::PIN_A_DIR);
    stepperA->setEnablePin(cfg::PIN_A_EN);
    stepperA->setAutoEnable(true);
    stepperA->setSpeedInHz(12000);
    stepperA->setAcceleration(9000);
  }
  if (stepperB) {
    stepperB->setDirectionPin(cfg::PIN_B_DIR);
    stepperB->setEnablePin(cfg::PIN_B_EN);
    stepperB->setAutoEnable(true);
    stepperB->setSpeedInHz(12000);
    stepperB->setAcceleration(9000);
  }
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
  if (stepperA) stepperA->setCurrentPosition(0);
  if (stepperB) stepperB->setCurrentPosition(0);
  homed_ = true;
  return true;
}

bool CoreXYMotion::moveTo(float x_mm, float y_mm) {
  if (!homed_ || !stepperA || !stepperB) return false;
  float dx = x_mm - x_mm_;
  float dy = y_mm - y_mm_;
  MotorSteps s = inverseKinematics(dx, dy);
  stepperA->move(s.a);
  stepperB->move(s.b);
  while (stepperA->isRunning() || stepperB->isRunning()) {
    delay(1);
  }
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
