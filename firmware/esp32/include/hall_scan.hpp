#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>

class HallScanner {
 public:
  void begin();
  void calibrateBaseline();
  void scanAndWriteJson(bool full);
  void setScanningEnabled(bool enabled) { scanning_enabled_ = enabled; }
 private:
  int readCellRaw(int muxIndex, int channel);
  void setMuxChannel(int channel);
  String squareName(int muxIndex, int channel) const;

  int baseline_[64] = {0};
  int lastMag_[64] = {0};
  bool lastOcc_[64] = {false};
  bool scanning_enabled_ = true;
};
