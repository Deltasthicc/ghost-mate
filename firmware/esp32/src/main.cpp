#include <Arduino.h>

#include "config.hpp"
#include "corexy.hpp"
#include "hall_scan.hpp"
#include "protocol.hpp"
#include "safety.hpp"
#include "z_axis.hpp"

CoreXYMotion motion;
HallScanner scanner;
Safety safety;
ZAxis zaxis;

static bool emOn = false;

void setElectromagnet(bool on) {
  emOn = on;
  digitalWrite(cfg::PIN_EM, on ? HIGH : LOW);
  scanner.setScanningEnabled(!on);
  if (!on) delay(cfg::SETTLE_MS_AFTER_EM_OFF);
}

bool executeMove(const Command& c) {
  if (!motion.isHomed()) return false;

  // Safe sequence: scan before pickup, disable scan while EM is on, settle, scan after drop.
  XY src = motion.squareCenter(c.from);
  XY dst = motion.squareCenter(c.to);
  if (!motion.moveTo(src.x, src.y)) return false;

  zaxis.engage();
  setElectromagnet(true);
  delay(120);
  zaxis.park();

  if (!motion.moveTo(dst.x, dst.y)) {
    setElectromagnet(false);
    zaxis.park();
    return false;
  }

  zaxis.engage();
  setElectromagnet(false);
  zaxis.park();
  scanner.scanAndWriteJson(false);
  return true;
}

void setup() {
  Serial.begin(cfg::SERIAL_BAUD);
  pinMode(cfg::PIN_EM, OUTPUT);
  digitalWrite(cfg::PIN_EM, LOW);

  safety.begin();
  zaxis.begin();
  motion.begin();
  scanner.begin();

  Serial.println("{\"type\":\"boot\",\"ok\":true}");
}

void loop() {
  if (safety.estopActive()) {
    setElectromagnet(false);
    writeFault("estop");
    delay(500);
    return;
  }

  if (!Serial.available()) {
    delay(2);
    return;
  }

  String line = Serial.readStringUntil('\n');
  line.trim();
  if (line.length() == 0) return;

  Command c;
  String err;
  if (!parseCommand(line, c, err)) {
    writeAck(0, false, err.c_str());
    return;
  }

  if (c.cmd == "home") {
    bool ok = motion.home();
    writeAck(c.id, ok, ok ? nullptr : "home_failed");
  } else if (c.cmd == "scan") {
    writeAck(c.id, true);
    scanner.scanAndWriteJson(c.full);
  } else if (c.cmd == "move" || c.cmd == "move_square_to_square") {
    writeAck(c.id, true);
    bool ok = executeMove(c);
    if (ok) writeMotionDone(c.id);
    else writeFault("move_failed", c.from.c_str());
  } else if (c.cmd == "capture_move") {
    // First revision: host can send separate victim removal and attacker move later.
    // This handler currently moves source to destination after capture square is known.
    writeAck(c.id, true);
    bool ok = executeMove(c);
    if (ok) writeMotionDone(c.id);
    else writeFault("capture_move_failed", c.to.c_str());
  } else if (c.cmd == "park") {
    bool ok = motion.park();
    zaxis.park();
    setElectromagnet(false);
    writeAck(c.id, ok, ok ? nullptr : "park_failed");
  } else if (c.cmd == "set_em") {
    setElectromagnet(c.on);
    writeAck(c.id, true);
  } else if (c.cmd == "calibrate") {
    scanner.calibrateBaseline();
    writeAck(c.id, true);
  } else {
    writeAck(c.id, false, "unknown_cmd");
  }
}
