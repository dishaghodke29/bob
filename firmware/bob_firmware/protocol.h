#pragma once
#include <Arduino.h>

// ─────────────────────────────────────────────
//  Serial JSON Protocol between MCU ↔ Linux Brain
//  Uses ttyHS1 high-speed UART on the UNO Q
//
//  COMMANDS (Linux → MCU):
//  {"cmd":"move","vy":150,"vx":0,"omega":0}
//  {"cmd":"stop"}
//  {"cmd":"estop"}
//  {"cmd":"calibrate"}
//  {"cmd":"ping"}
//
//  TELEMETRY (MCU → Linux)  — sent every 50ms:
//  {"t":12345,"roll":-1.2,"pitch":0.4,"ax":0.01,"ay":-0.01,"az":0.99,"estop":false,"ok":true}
// ─────────────────────────────────────────────

#define SERIAL_BAUD   115200
#define TX_INTERVAL_MS  50    // Send telemetry every 50ms
#define CMD_BUFFER_SIZE 128

static char   _cmd_buf[CMD_BUFFER_SIZE];
static uint8_t _cmd_len = 0;
static unsigned long _last_tx = 0;

// ── Tiny JSON value extractor (no external lib needed) ──
// Finds "key":VALUE in a flat JSON string and returns the integer/float value
static float json_get_float(const char* json, const char* key, float def = 0.0f) {
  char search[32];
  snprintf(search, sizeof(search), "\"%s\":", key);
  const char* pos = strstr(json, search);
  if (!pos) return def;
  pos += strlen(search);
  while (*pos == ' ') pos++;
  return atof(pos);
}

static bool json_has_key(const char* json, const char* key) {
  char search[32];
  snprintf(search, sizeof(search), "\"%s\"", key);
  return strstr(json, search) != nullptr;
}

static bool json_get_bool(const char* json, const char* key, bool def = false) {
  char search[32];
  snprintf(search, sizeof(search), "\"%s\":true", key);
  if (strstr(json, search)) return true;
  snprintf(search, sizeof(search), "\"%s\":false", key);
  if (strstr(json, search)) return false;
  return def;
}

// Extract string value like "cmd":"stop" → fills buf with "stop"
static bool json_get_str(const char* json, const char* key, char* buf, uint8_t buflen) {
  char search[32];
  snprintf(search, sizeof(search), "\"%s\":\"", key);
  const char* pos = strstr(json, search);
  if (!pos) return false;
  pos += strlen(search);
  uint8_t i = 0;
  while (*pos && *pos != '"' && i < buflen - 1) buf[i++] = *pos++;
  buf[i] = '\0';
  return true;
}

// ── Command type enum ──
enum CmdType { CMD_NONE, CMD_MOVE, CMD_STOP, CMD_ESTOP, CMD_CALIBRATE, CMD_PING, CMD_SERVO };

struct Command {
  CmdType type;
  int vy, vx, omega;  // for CMD_MOVE
};

// ── Protocol init ──
void protocol_init() {
  Serial.begin(SERIAL_BAUD);
  while (!Serial) delay(10);
}

// ── Parse incoming line into a Command struct ──
Command protocol_parse(const char* line) {
  Command c = { CMD_NONE, 0, 0, 0 };
  char cmd_str[16];
  if (!json_get_str(line, "cmd", cmd_str, sizeof(cmd_str))) return c;

  if      (strcmp(cmd_str, "move")      == 0) {
    c.type  = CMD_MOVE;
    c.vy    = (int)json_get_float(line, "vy");
    c.vx    = (int)json_get_float(line, "vx");
    c.omega = (int)json_get_float(line, "omega");
  }
  else if (strcmp(cmd_str, "stop")      == 0) c.type = CMD_STOP;
  else if (strcmp(cmd_str, "estop")     == 0) c.type = CMD_ESTOP;
  else if (strcmp(cmd_str, "calibrate") == 0) c.type = CMD_CALIBRATE;
  else if (strcmp(cmd_str, "ping")      == 0) c.type = CMD_PING;
  else if (strcmp(cmd_str, "servo")     == 0) c.type = CMD_SERVO;

  return c;
}

// ── Read one complete JSON line (non-blocking) ──
// Returns true and fills _cmd_buf when a full '\n'-terminated line arrives
bool protocol_read(Command& out) {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      _cmd_buf[_cmd_len] = '\0';
      _cmd_len = 0;
      if (_cmd_buf[0] == '{') {
        out = protocol_parse(_cmd_buf);
        return true;
      }
    } else if (_cmd_len < CMD_BUFFER_SIZE - 1) {
      _cmd_buf[_cmd_len++] = c;
    }
  }
  return false;
}

// ── Send telemetry JSON (call every loop, rate-limited) ──
void protocol_send_telemetry(float roll, float pitch,
                              float ax, float ay, float az,
                              bool estop_active, bool imu_ok) {
  unsigned long now = millis();
  if (now - _last_tx < TX_INTERVAL_MS) return;
  _last_tx = now;

  // Hand-built JSON — avoids ArduinoJson overhead
  Serial.print(F("{\"t\":"));
  Serial.print(now);
  Serial.print(F(",\"roll\":"));   Serial.print(roll,   2);
  Serial.print(F(",\"pitch\":"));  Serial.print(pitch,  2);
  Serial.print(F(",\"ax\":"));     Serial.print(ax,     3);
  Serial.print(F(",\"ay\":"));     Serial.print(ay,     3);
  Serial.print(F(",\"az\":"));     Serial.print(az,     3);
  Serial.print(F(",\"estop\":"));  Serial.print(estop_active ? "true" : "false");
  Serial.print(F(",\"ok\":"));     Serial.print(imu_ok   ? "true" : "false");
  Serial.println(F("}"));
}

// ── Send a simple ACK/PONG ──
void protocol_pong() {
  Serial.println(F("{\"pong\":true}"));
}
