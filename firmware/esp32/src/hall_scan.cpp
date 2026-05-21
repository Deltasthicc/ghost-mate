#include "hall_scan.hpp"
#include "config.hpp"

void HallScanner::begin() {
  pinMode(cfg::PIN_MUX_S0, OUTPUT);
  pinMode(cfg::PIN_MUX_S1, OUTPUT);
  pinMode(cfg::PIN_MUX_S2, OUTPUT);
  pinMode(cfg::PIN_MUX_S3, OUTPUT);
  for (int i = 0; i < 4; i++) {
    pinMode(cfg::ADC_PINS[i], INPUT);
  }
  analogReadResolution(12);
  calibrateBaseline();
}

void HallScanner::setMuxChannel(int channel) {
  digitalWrite(cfg::PIN_MUX_S0, channel & 0x01);
  digitalWrite(cfg::PIN_MUX_S1, (channel >> 1) & 0x01);
  digitalWrite(cfg::PIN_MUX_S2, (channel >> 2) & 0x01);
  digitalWrite(cfg::PIN_MUX_S3, (channel >> 3) & 0x01);
  delayMicroseconds(8);
}

int HallScanner::readCellRaw(int muxIndex, int channel) {
  setMuxChannel(channel);
  long sum = 0;
  for (int i = 0; i < cfg::HALL_OVERSAMPLES; i++) {
    sum += analogRead(cfg::ADC_PINS[muxIndex]);
    delayMicroseconds(80);
  }
  return (int)(sum / cfg::HALL_OVERSAMPLES);
}

String HallScanner::squareName(int muxIndex, int channel) const {
  // Mapping: each mux covers 16 sequential squares in row-major order.
  int index = muxIndex * 16 + channel;
  int rank = index / 8;
  int file = index % 8;
  char buf[3];
  buf[0] = 'a' + file;
  buf[1] = '1' + rank;
  buf[2] = '\0';
  return String(buf);
}

void HallScanner::calibrateBaseline() {
  for (int mux = 0; mux < 4; mux++) {
    for (int ch = 0; ch < 16; ch++) {
      int index = mux * 16 + ch;
      baseline_[index] = readCellRaw(mux, ch);
    }
  }
}

void HallScanner::scanAndWriteJson(bool full) {
  if (!scanning_enabled_) return;

  StaticJsonDocument<4096> doc;
  doc["type"] = "scan";
  doc["ts_ms"] = millis();
  JsonObject cells = doc.createNestedObject("cells");

  for (int mux = 0; mux < 4; mux++) {
    for (int ch = 0; ch < 16; ch++) {
      int index = mux * 16 + ch;
      int raw = readCellRaw(mux, ch);
      int delta = raw - baseline_[index];
      int mag = abs(delta);
      bool occ = mag >= cfg::HALL_OCC_THRESHOLD;
      int polarity = occ ? (delta >= 0 ? 1 : -1) : 0;

      bool changed = occ != lastOcc_[index] || abs(mag - lastMag_[index]) > 20;
      if (full || changed) {
        JsonObject c = cells.createNestedObject(squareName(mux, ch));
        c["o"] = occ ? 1 : 0;
        c["p"] = polarity;
        c["m"] = mag;
      }

      lastOcc_[index] = occ;
      lastMag_[index] = mag;
    }
  }

  serializeJson(doc, Serial);
  Serial.println();
}
