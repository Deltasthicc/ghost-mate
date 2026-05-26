#include "safety.hpp"
#include "config.hpp"

void Safety::begin() {
  pinMode(cfg::PIN_X_MIN, INPUT_PULLUP);
  pinMode(cfg::PIN_Y_MIN, INPUT_PULLUP);
  pinMode(cfg::PIN_ESTOP, INPUT_PULLUP);
}

bool Safety::estopActive() const {
  return digitalRead(cfg::PIN_ESTOP) == LOW;
}

bool Safety::xMinActive() const {
  return digitalRead(cfg::PIN_X_MIN) == LOW;
}

bool Safety::yMinActive() const {
  return digitalRead(cfg::PIN_Y_MIN) == LOW;
}
