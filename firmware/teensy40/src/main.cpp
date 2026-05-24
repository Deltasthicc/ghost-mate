#include <Arduino.h>

static String line;
static const uint32_t BAUD = 115200;

int getId(String s) {
  s.replace(" ", "");
  int p = s.indexOf("\"id\":");
  if (p < 0) return -1;
  p += 5;
  return s.substring(p).toInt();
}

bool hasCmd(String s, const char* cmd) {
  s.replace(" ", "");
  String target = String("\"cmd\":\"") + cmd + "\"";
  return s.indexOf(target) >= 0;
}

void ack(int id, bool ok, const char* err = nullptr) {
  Serial.print("{\"id\":");
  Serial.print(id);
  Serial.print(",\"ok\":");
  Serial.print(ok ? "true" : "false");
  Serial.print(",\"err\":");
  if (err) {
    Serial.print("\"");
    Serial.print(err);
    Serial.println("\"}");
  } else {
    Serial.println("null}");
  }
}

void motionDone(int id) {
  Serial.print("{\"type\":\"motion_done\",\"id\":");
  Serial.print(id);
  Serial.println("}");
}

void scanEvent() {
  Serial.print("{\"type\":\"scan\",\"ts_ms\":");
  Serial.print(millis());
  Serial.print(",\"cells\":{");

  bool first = true;
  for (char f = 'a'; f <= 'h'; f++) {
    for (char r = '1'; r <= '8'; r++) {
      if (!first) Serial.print(",");
      first = false;
      Serial.print("\"");
      Serial.print(f);
      Serial.print(r);
      Serial.print("\":{\"o\":0,\"p\":0,\"m\":0}");
    }
  }

  Serial.println("}}");
}

void handle(String s) {
  s.trim();
  if (!s.length()) return;

  int id = getId(s);

  if (hasCmd(s, "ping") || hasCmd(s, "version")) {
    Serial.print("{\"id\":");
    Serial.print(id);
    Serial.println(",\"ok\":true,\"controller\":\"teensy40\",\"fw\":\"minimal\"}");
    return;
  }

  if (hasCmd(s, "scan")) {
    ack(id, true);
    scanEvent();
    return;
  }

  if (hasCmd(s, "home") || hasCmd(s, "park") || hasCmd(s, "move") || hasCmd(s, "capture_move")) {
    ack(id, true);
    motionDone(id);
    return;
  }

  if (hasCmd(s, "set_em") || hasCmd(s, "set_electromagnet")) {
    ack(id, true);
    return;
  }

  ack(id, false, "unknown_command");
}

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  Serial.begin(BAUD);
  while (!Serial && millis() < 1500) delay(10);
  Serial.println("{\"type\":\"boot\",\"controller\":\"teensy40\",\"fw\":\"minimal\",\"baud\":115200}");
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      handle(line);
      line = "";
    } else if (c != '\r') {
      line += c;
      if (line.length() > 400) line = "";
    }
  }

  static uint32_t last = 0;
  if (millis() - last > 500) {
    last = millis();
    digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
  }
}
