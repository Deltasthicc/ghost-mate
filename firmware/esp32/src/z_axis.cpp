#include "z_axis.hpp"
#include "config.hpp"
#include <Arduino.h>

void ZAxis::begin() {
  ledcSetup(cfg::SERVO_LEDC_CHANNEL, cfg::SERVO_LEDC_FREQ, cfg::SERVO_LEDC_BITS);
  ledcAttachPin(cfg::PIN_SERVO, cfg::SERVO_LEDC_CHANNEL);
  park();
}

void ZAxis::writePulseUs(int pulse_us) {
  const int period_us = 1000000 / cfg::SERVO_LEDC_FREQ;
  const uint32_t max_duty = (1UL << cfg::SERVO_LEDC_BITS) - 1;
  uint32_t duty = (uint32_t)((pulse_us * max_duty) / period_us);
  ledcWrite(cfg::SERVO_LEDC_CHANNEL, duty);
}

void ZAxis::park() {
  writePulseUs(cfg::SERVO_PARK_US);
  delay(250);
}

void ZAxis::engage() {
  writePulseUs(cfg::SERVO_ENGAGE_US);
  delay(250);
}
