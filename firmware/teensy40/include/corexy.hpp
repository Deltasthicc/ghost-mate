#pragma once

#include <Arduino.h>

struct XY {
  float x;
  float y;
};

struct MotorSteps {
  long a;
  long b;
};

class CoreXYMotion {
 public:
  void begin();
  bool home();
  bool moveTo(float x_mm, float y_mm);
  bool moveSquareToSquare(const String& from, const String& to);
  bool park();
  bool isHomed() const { return homed_; }
  XY squareCenter(const String& square) const;
  MotorSteps inverseKinematics(float dx_mm, float dy_mm) const;

 private:
  void enableMotors(bool enabled);
  void stepBoth(long a_steps, long b_steps);

  bool homed_ = false;
  float x_mm_ = 0.0f;
  float y_mm_ = 0.0f;
};
