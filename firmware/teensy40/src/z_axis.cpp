#include "z_axis.hpp"
#include "config.hpp"

#include <Arduino.h>
#include <Servo.h>

static Servo zServo;

void ZAxis::begin() {
  zServo.attach(cfg::PIN_SERVO);
  park();
}

void ZAxis::writePulseUs(int pulse_us) {
  zServo.writeMicroseconds(pulse_us);
}

void ZAxis::park() {
  writePulseUs(cfg::SERVO_PARK_US);
  delay(250);
}

void ZAxis::engage() {
  writePulseUs(cfg::SERVO_ENGAGE_US);
  delay(250);
}
