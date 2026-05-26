#include "protocol.hpp"

bool parseCommand(const String& line, Command& out, String& err) {
  JsonDocument doc;
  DeserializationError e = deserializeJson(doc, line);
  if (e) {
    err = "bad_json";
    return false;
  }
  if (!doc["id"].is<uint32_t>() || !doc["cmd"].is<const char*>()) {
    err = "missing_id_or_cmd";
    return false;
  }
  out.id = doc["id"].as<uint32_t>();
  out.cmd = String(doc["cmd"].as<const char*>());
  out.from = String(doc["from"] | "");
  out.to = String(doc["to"] | "");
  out.victim = String(doc["victim"] | "");
  out.capture = doc["capture"] | false;
  out.on = doc["on"] | false;
  out.full = doc["full"] | false;
  return true;
}

void writeAck(uint32_t id, bool ok, const char* err) {
  JsonDocument doc;
  doc["id"] = id;
  doc["ok"] = ok;
  if (!ok && err) doc["err"] = err;
  serializeJson(doc, Serial);
  Serial.println();
}

void writeFault(const char* code, const char* square) {
  JsonDocument doc;
  doc["type"] = "fault";
  doc["code"] = code;
  if (square) doc["square"] = square;
  serializeJson(doc, Serial);
  Serial.println();
}

void writeMotionDone(uint32_t id) {
  JsonDocument doc;
  doc["type"] = "motion_done";
  doc["id"] = id;
  serializeJson(doc, Serial);
  Serial.println();
}
