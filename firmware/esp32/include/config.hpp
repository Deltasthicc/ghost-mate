#pragma once

#include <Arduino.h>

namespace cfg {

// Serial
static constexpr uint32_t SERIAL_BAUD = 115200;

// Board geometry
static constexpr float SQUARE_MM = 50.0f;
static constexpr float ORIGIN_X_MM = 0.0f;
static constexpr float ORIGIN_Y_MM = 0.0f;
static constexpr float STEPS_PER_MM = 80.0f;  // 1/16 microstep, 20T GT2 pulley: 4000 / 50 mm = 80

// Stepper pins. Verify with your driver board before powering motors.
static constexpr int PIN_A_STEP = 26;
static constexpr int PIN_A_DIR = 27;
static constexpr int PIN_A_EN = 25;
static constexpr int PIN_B_STEP = 14;
static constexpr int PIN_B_DIR = 12;
static constexpr int PIN_B_EN = 13;

// Endstops. Use INPUT_PULLUP and wire switches to GND.
static constexpr int PIN_X_MIN = 32;
static constexpr int PIN_Y_MIN = 33;
static constexpr int PIN_ESTOP = 4;

// Electromagnet MOSFET gate.
static constexpr int PIN_EM = 23;

// Servo PWM through ESP32 LEDC.
static constexpr int PIN_SERVO = 18;
static constexpr int SERVO_LEDC_CHANNEL = 0;
static constexpr int SERVO_LEDC_FREQ = 50;
static constexpr int SERVO_LEDC_BITS = 16;
static constexpr int SERVO_PARK_US = 1000;
static constexpr int SERVO_ENGAGE_US = 1900;

// CD74HC4067 shared address lines.
static constexpr int PIN_MUX_S0 = 16;
static constexpr int PIN_MUX_S1 = 17;
static constexpr int PIN_MUX_S2 = 5;
static constexpr int PIN_MUX_S3 = 15;  // boot strap pin; keep pulldown during reset.

// Four mux signal returns into ADC1 pins.
static constexpr int ADC_PINS[4] = {36, 39, 34, 35};

static constexpr int HALL_OVERSAMPLES = 12;
static constexpr int HALL_OCC_THRESHOLD = 120;
static constexpr uint32_t SETTLE_MS_AFTER_EM_OFF = 180;

}  // namespace cfg
