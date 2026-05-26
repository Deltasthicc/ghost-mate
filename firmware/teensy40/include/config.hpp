#pragma once

#include <Arduino.h>

namespace cfg {

// USB serial. Teensy USB CDC is not timing-sensitive, but keep this aligned
// with host defaults and PlatformIO monitor settings for consistency.
static constexpr uint32_t SERIAL_BAUD = 115200;

// Board geometry
static constexpr float SQUARE_MM = 50.0f;
static constexpr float ORIGIN_X_MM = 0.0f;
static constexpr float ORIGIN_Y_MM = 0.0f;
static constexpr float STEPS_PER_MM = 80.0f;  // 1/16 microstep, 20T GT2 pulley.

// Teensy 4.0 pin map. Verify against the carrier board before powering motors.
// TMC2209-style step/dir/en pins for the two CoreXY motors.
static constexpr int PIN_A_STEP = 2;
static constexpr int PIN_A_DIR = 3;
static constexpr int PIN_A_EN = 4;
static constexpr int PIN_B_STEP = 5;
static constexpr int PIN_B_DIR = 6;
static constexpr int PIN_B_EN = 7;

// Endstops and emergency stop. Use INPUT_PULLUP and wire switches to GND.
static constexpr int PIN_X_MIN = 8;
static constexpr int PIN_Y_MIN = 9;
static constexpr int PIN_ESTOP = 10;

// Electromagnet MOSFET gate.
static constexpr int PIN_EM = 11;

// Z servo control.
static constexpr int PIN_SERVO = 12;
static constexpr int SERVO_PARK_US = 1000;
static constexpr int SERVO_ENGAGE_US = 1900;

// CD74HC4067 shared address lines.
static constexpr int PIN_MUX_S0 = 18;
static constexpr int PIN_MUX_S1 = 19;
static constexpr int PIN_MUX_S2 = 20;
static constexpr int PIN_MUX_S3 = 21;

// Four mux signal returns into Teensy analog-capable pins.
static constexpr int ADC_PINS[4] = {A0, A1, A2, A3};

static constexpr int HALL_OVERSAMPLES = 12;
static constexpr int HALL_OCC_THRESHOLD = 120;
static constexpr uint32_t SETTLE_MS_AFTER_EM_OFF = 180;

// Conservative blocking stepper pulse generation for first Teensy bring-up.
static constexpr uint32_t STEP_PULSE_US = 3;
static constexpr uint32_t STEP_INTERVAL_US = 120;

}  // namespace cfg
