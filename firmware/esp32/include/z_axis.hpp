#pragma once

class ZAxis {
 public:
  void begin();
  void park();
  void engage();
 private:
  void writePulseUs(int pulse_us);
};
