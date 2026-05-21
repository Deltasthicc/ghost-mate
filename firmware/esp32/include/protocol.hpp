#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>

struct Command {
  uint32_t id = 0;
  String cmd;
  String from;
  String to;
  String victim;
  bool capture = false;
  bool on = false;
  bool full = false;
};

bool parseCommand(const String& line, Command& out, String& err);
void writeAck(uint32_t id, bool ok, const char* err = nullptr);
void writeFault(const char* code, const char* square = nullptr);
void writeMotionDone(uint32_t id);
