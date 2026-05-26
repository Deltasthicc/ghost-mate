#pragma once

#include <Arduino.h>

class Safety {
 public:
  void begin();
  bool estopActive() const;
  bool xMinActive() const;
  bool yMinActive() const;
};
