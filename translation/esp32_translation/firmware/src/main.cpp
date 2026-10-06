#include <Arduino.h>
#include <ArduinoJson.h>
#include <HardwareSerial.h>
#include <NimBLEDevice.h>
#include <Preferences.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <esp_system.h>
#include <esp_task_wdt.h>
#include <time.h>

#include "artistic_config.h"
#include "board_profiles.h"
#include "runtime_core.h"
#include "score_data.h"
#include "semantic_framing.h"

#if __has_include("deployment_config.h")
#include "deployment_config.h"
#else
#define BWM_WIFI_SSID ""
#define BWM_WIFI_PASSWORD ""
#define BWM_MQTT_HOST ""
#define BWM_MQTT_PORT 1883
#endif

namespace {

constexpr char kFirmwareVersion[] = "esp32-translation-1";
constexpr char kActivationTopic[] = "bwm/installation/activation";
constexpr char kWhisperStateTopic[] = "bwm/whisper/state";
constexpr char kWhisperInteractionTopic[] = "bwm/whisper/interaction";
constexpr char kBleServiceUuid[] = "7a9e4c10-5b8d-4bd6-9c17-2f3e8a4b1001";
constexpr char kBleCharacteristicUuid[] = "7a9e4c10-5b8d-4bd6-9c17-2f3e8a4b1002";
constexpr size_t kMaxSemanticFrame = 8192;
constexpr uint32_t kButtonDeadtimeMs = 400;
constexpr uint32_t kReconnectMs = 5000;
constexpr uint8_t kChannelCount = 6;
constexpr bwm::SafetyLimits kSafetyLimits{500, 40, 10000, 160, 9000};

enum class TriggerMode : uint8_t { kWhisperInteraction, kWhisperState };
constexpr TriggerMode kTriggerMode = TriggerMode::kWhisperInteraction;

struct ScheduledPulse {
  uint32_t due_ms = 0;
  uint32_t generation = 0;
  uint16_t duration_ms = 0;
  uint8_t channel = 0;
  bool reaction = false;
  bool used = false;
};

struct SemanticFrame { char bytes[kMaxSemanticFrame + 1]; };

ScheduledPulse pulse_queue[256];
size_t reaction_pending = 0;
uint32_t reaction_busy_until = 0;
bool reaction_window_active = false;
bwm::Reaction current_reaction = bwm::Reaction::kCascade;
uint32_t accepted_pulses = 0;
uint32_t rejected_pulses = 0;
uint32_t duplicate_messages = 0;
uint32_t invalid_messages = 0;
uint32_t dropped_busy = 0;
uint32_t generation = 0;
uint32_t planned_free_ms[kChannelCount]{};
bool fault_latched = false;
bool last_button = true;
uint32_t button_dead_until = 0;
char last_whisper_state[32] = "unknown";
uint32_t next_wifi_attempt = 0;
uint32_t next_mqtt_attempt = 0;
uint32_t next_diagnostic = 0;

HardwareSerial whisper_uart(1);
WiFiClient wifi_client;
PubSubClient mqtt(wifi_client);
Preferences preferences;
bwm::RecentIds recent_ids;
bwm::SessionState session;
QueueHandle_t ble_frames = nullptr;

String wifi_ssid;
String wifi_password;
String mqtt_host;
uint16_t mqtt_port = BWM_MQTT_PORT;

void writeOutput(uint8_t channel, bool high) {
  if (channel < kChannelCount) digitalWrite(bwm::kBoard.outputs[channel], high ? HIGH : LOW);
}
bwm::ActuatorSafety<kChannelCount> safety(kSafetyLimits, writeOutput);

void clearPulseQueue() {
  for (auto& pulse : pulse_queue) pulse.used = false;
  reaction_pending = 0;
  memset(planned_free_ms, 0, sizeof(planned_free_ms));
}

void enterFault(const char* reason) {
  if (!fault_latched) {
    Serial.printf("[FAULT] %s\n", reason);
    fault_latched = true;
  }
  clearPulseQueue();
  reaction_window_active = false;
  reaction_busy_until = 0;
  safety.latchFault(millis());
  session.deactivate();
}

bool schedulePulse(uint8_t channel, uint16_t duration_ms, uint32_t due_ms, bool reaction) {
  if (channel >= kChannelCount || duration_ms == 0 || duration_ms > kSafetyLimits.max_pulse_ms) {
    enterFault("scheduler created invalid pulse");
    return false;
  }
  // The Pi backend serializes each channel's queue. Reproduce that practical
  // behavior with a bounded local schedule and the 40 ms emergency OFF floor.
  if (planned_free_ms[channel] && !bwm::reached(due_ms, planned_free_ms[channel] + kSafetyLimits.min_off_ms)) {
    due_ms = planned_free_ms[channel] + kSafetyLimits.min_off_ms;
  }
  for (auto& item : pulse_queue) {
    if (!item.used) {
      item.due_ms = due_ms;
      item.generation = generation;
      item.duration_ms = duration_ms;
      item.channel = channel;
      item.reaction = reaction;
      item.used = true;
      planned_free_ms[channel] = due_ms + duration_ms;
      if (reaction) ++reaction_pending;
      return true;
    }
  }
  enterFault("bounded pulse queue exhausted");
  return false;
}

void servicePulseQueue(uint32_t now) {
  safety.service(now);
  for (auto& item : pulse_queue) {
    if (!item.used || !bwm::reached(now, item.due_ms)) continue;
    const bool was_reaction = item.reaction;
    if (item.generation == generation && session.active() && !fault_latched) {
      const bwm::AdmissionResult result = safety.admit(item.channel, item.duration_ms, now);
      if (result == bwm::AdmissionResult::kAccepted) {
        ++accepted_pulses;
      } else {
        ++rejected_pulses;
        if (result == bwm::AdmissionResult::kInvalidChannel ||
            result == bwm::AdmissionResult::kInvalidDuration ||
            result == bwm::AdmissionResult::kFaultLatched) {
          enterFault("actuator admission rejected invalid internal work");
        }
      }
    }
    item.used = false;
    if (was_reaction && reaction_pending) --reaction_pending;
  }
}

bool reactionBusy(uint32_t now) {
  return reaction_pending != 0 || (reaction_busy_until && !bwm::reached(now, reaction_busy_until));
}

void teardown(bool publish, const char* reason);

String timestampNow(bool& synchronized) {
  struct tm utc{};
  const time_t current = time(nullptr);
  synchronized = current >= 1609459200;
  char buffer[32];
  if (synchronized && gmtime_r(&current, &utc)) {
    strftime(buffer, sizeof(buffer), "%Y-%m-%dT%H:%M:%SZ", &utc);
  } else {
    const uint32_t seconds = millis() / 1000;
    snprintf(buffer, sizeof(buffer), "1970-01-%02luT%02lu:%02lu:%02luZ",
             1UL + (seconds / 86400UL) % 28UL, (seconds / 3600UL) % 24UL,
             (seconds / 60UL) % 60UL, seconds % 60UL);
  }
  return String(buffer);
}

String newEventId() {
  uint8_t raw[16];
  esp_fill_random(raw, sizeof(raw));
  raw[6] = (raw[6] & 0x0f) | 0x40;
  raw[8] = (raw[8] & 0x3f) | 0x80;
  char id[37];
  snprintf(id, sizeof(id), "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
           raw[0], raw[1], raw[2], raw[3], raw[4], raw[5], raw[6], raw[7], raw[8], raw[9],
           raw[10], raw[11], raw[12], raw[13], raw[14], raw[15]);
  return String(id);
}

void publishAuthoritative(const char* state) {
  JsonDocument doc;
  bool synced = false;
  doc["version"] = 1;
  doc["id"] = newEventId();
  doc["type"] = "installation.activation";
  doc["origin"] = "translation_pi";
  doc["timestamp"] = timestampNow(synced);
  doc["payload"]["state"] = state;
  doc["diagnostics"]["timestamp_quality"] = synced ? "ntp" : "monotonic_fallback";
  serializeJson(doc, whisper_uart);
  whisper_uart.write('\n');
}

void activate(bool publish) {
  const uint32_t now = millis();
  const bwm::SessionSelection selection = bwm::selectSegment(
      bwm::kScoreEvents, bwm::kScoreEventCount, bwm::kSegmentDurationMs, esp_random());
  if (!session.activate(now, selection, bwm::kSolenoidAdmissionDelayMs, bwm::kSessionTimeoutMs)) return;
  ++generation;
  clearPulseQueue();
  reaction_window_active = false;
  reaction_busy_until = 0;
  Serial.printf("[Session] ACTIVE source=%lu..%lu ms events=%u admission=%lu ms\n",
                static_cast<unsigned long>(selection.source_start_ms),
                static_cast<unsigned long>(selection.source_end_ms),
                static_cast<unsigned>(selection.end - selection.begin),
                static_cast<unsigned long>(bwm::kSolenoidAdmissionDelayMs));
  if (publish) publishAuthoritative("active");
}

void teardown(bool publish, const char* reason) {
  if (!session.deactivate()) return;
  ++generation;
  clearPulseQueue();
  reaction_window_active = false;
  reaction_busy_until = 0;
  safety.forceAllOff(millis());
  Serial.printf("[Session] IDLE reason=%s outputs=LOW\n", reason);
  if (publish) publishAuthoritative("inactive");
}

void toggleLocal() {
  if (session.active()) teardown(true, "local_button");
  else activate(true);
}

bwm::Reaction reactionForSilero(float value) {
  for (size_t i = 0; i < 5; ++i) if (value < bwm::kSileroUpper[i]) return bwm::kBandReaction[i];
  return bwm::kBandReaction[4];
}

bwm::Reaction randomReaction() {
  uint16_t total = 0;
  for (uint8_t weight : bwm::kDefaultWeights) total += weight;
  if (!total) return bwm::Reaction::kCascade;
  uint16_t value = esp_random() % total;
  for (uint8_t i = 0; i < 5; ++i) {
    if (value < bwm::kDefaultWeights[i]) return static_cast<bwm::Reaction>(i);
    value -= bwm::kDefaultWeights[i];
  }
  return bwm::Reaction::kCascade;
}

void triggerReaction(bwm::Reaction reaction) {
  const uint32_t now = millis();
  if (!session.active()) return;
  if (reactionBusy(now)) { ++dropped_busy; return; }
  current_reaction = reaction;
  uint32_t start = now + bwm::kQuietGapMs;
  if (safety.hasAccepted()) {
    const uint32_t quiet_deadline = safety.lastAcceptedMs() + bwm::kQuietGapMs;
    if (bwm::reached(now, quiet_deadline)) start = now;
    else start = quiet_deadline;
  }
  reaction_window_active = true;
  switch (reaction) {
    case bwm::Reaction::kSimultaneousThenSequence: {
      for (uint8_t channel = 0; channel < 6; ++channel) schedulePulse(channel, bwm::kReactionPulseMs, start, true);
      uint32_t sequence = start + bwm::kSimultaneousWaitMs;
      for (uint8_t channel = 0; channel < 6; ++channel)
        schedulePulse(channel, bwm::kReactionPulseMs, sequence + channel * bwm::kSimultaneousSpacingMs, true);
      reaction_busy_until = sequence + 5 * bwm::kSimultaneousSpacingMs + bwm::kSimultaneousTailMs;
      break;
    }
    case bwm::Reaction::kCascade:
      for (uint8_t channel = 0; channel < 6; ++channel)
        schedulePulse(channel, bwm::kReactionPulseMs, start + channel * bwm::kCascadeSpacingMs, true);
      reaction_busy_until = start + 5 * bwm::kCascadeSpacingMs + bwm::kCascadeTailMs;
      break;
    case bwm::Reaction::kSplitGroups:
      for (uint8_t channel = 0; channel < 3; ++channel) schedulePulse(channel, bwm::kReactionPulseMs, start, true);
      for (uint8_t channel = 3; channel < 6; ++channel)
        schedulePulse(channel, bwm::kReactionPulseMs, start + bwm::kSplitWaitMs, true);
      reaction_busy_until = start + bwm::kSplitWaitMs + bwm::kSplitTailMs;
      break;
    case bwm::Reaction::kTripleTap:
      reaction_busy_until = now + bwm::kTripleWindowMs;
      break;
    case bwm::Reaction::kDoubleTap:
      reaction_busy_until = now + bwm::kDoubleWindowMs;
      break;
  }
  Serial.printf("[Reaction] started type=%u busy_until=%lu\n", static_cast<unsigned>(reaction),
                static_cast<unsigned long>(reaction_busy_until));
}

bool validTimestamp(const char* value) {
  return value && strlen(value) >= 20 && value[4] == '-' && value[7] == '-' && value[10] == 'T';
}

bool stateAllowed(const char* state) {
  static const char* values[] = {"idle", "initializing", "listening", "whisper_detected",
                                 "capture_processing", "response_displayed"};
  for (const char* value : values) if (state && strcmp(state, value) == 0) return true;
  return false;
}

void processSemanticEvent(const char* raw, size_t length, bool inbound_uart, const char* transport) {
  if (!raw || !length || length > kMaxSemanticFrame) { ++invalid_messages; return; }
  JsonDocument doc;
  const DeserializationError error = deserializeJson(doc, raw, length);
  if (error || doc["version"].as<int>() != 1 || !doc["id"].is<const char*>() ||
      !doc["type"].is<const char*>() || !doc["origin"].is<const char*>() ||
      !doc["timestamp"].is<const char*>() || !doc["payload"].is<JsonObject>() ||
      !validTimestamp(doc["timestamp"].as<const char*>())) {
    ++invalid_messages;
    return;
  }
  const char* id = doc["id"];
  const char* type = doc["type"];
  if (!*id || !*type || !*doc["origin"].as<const char*>()) { ++invalid_messages; return; }
  if (recent_ids.seen(bwm::RecentIds::hash(id), millis())) { ++duplicate_messages; return; }
  JsonObject payload = doc["payload"];
  if (strcmp(type, "installation.activation") == 0) {
    const char* state = payload["state"] | "";
    if (strcmp(state, "active") == 0) activate(!inbound_uart);
    else if (strcmp(state, "inactive") == 0) teardown(!inbound_uart, transport);
    else ++invalid_messages;
    return;
  }
  if (strcmp(type, "whisper.interaction") == 0) {
    const char* source = payload["source"] | "";
    if (strcmp(source, "detector") == 0 && payload["silero_selection_value"].is<float>()) {
      if (kTriggerMode == TriggerMode::kWhisperInteraction)
        triggerReaction(reactionForSilero(payload["silero_selection_value"].as<float>()));
    } else if (strcmp(source, "button") == 0 && payload["silero_selection_value"].isNull()) {
      if (kTriggerMode == TriggerMode::kWhisperInteraction) triggerReaction(randomReaction());
    } else ++invalid_messages;
    return;
  }
  if (strcmp(type, "whisper.state") == 0) {
    const char* state = payload["state"] | "";
    if (!stateAllowed(state)) { ++invalid_messages; return; }
    const bool entering = strcmp(last_whisper_state, state) != 0;
    strlcpy(last_whisper_state, state, sizeof(last_whisper_state));
    if (kTriggerMode == TriggerMode::kWhisperState && entering && strcmp(state, "capture_processing") == 0)
      triggerReaction(randomReaction());
    return;
  }
  ++invalid_messages;
}

void dispatchScore(uint32_t now) {
  if (!session.active() || !session.admissionOpen(now)) return;
  const bwm::SessionSelection& selected = session.selection();
  while (session.next() < selected.end) {
    const bwm::ScoreEvent& event = bwm::kScoreEvents[session.next()];
    const uint32_t relative = event.time_ms - selected.source_start_ms;
    if (relative > session.scoreElapsed(now)) break;
    session.advance();
    if (reaction_window_active && !bwm::reached(now, reaction_busy_until)) {
      if (current_reaction == bwm::Reaction::kTripleTap) {
        for (uint8_t i = 0; i < bwm::kTripleCount; ++i)
          schedulePulse(event.channel, event.duration_ms, now + i * bwm::kTripleSpacingMs, true);
      } else if (current_reaction == bwm::Reaction::kDoubleTap) {
        for (uint8_t i = 0; i < bwm::kDoubleCount; ++i)
          schedulePulse(event.channel, event.duration_ms, now + i * bwm::kDoubleSpacingMs, true);
      }
      // Override reactions suppress; repeat reactions replace. Both discard base.
    } else {
      reaction_window_active = false;
      schedulePulse(event.channel, event.duration_ms, now, false);
    }
  }
}

bwm::UartLineFramer<kMaxSemanticFrame> uart_framer;

void serviceUart() {
  while (whisper_uart.available()) {
    const bwm::FrameResult result = uart_framer.feed(static_cast<uint8_t>(whisper_uart.read()));
    if (result == bwm::FrameResult::kComplete)
      processSemanticEvent(uart_framer.data(), uart_framer.size(), true, "uart");
    else if (result == bwm::FrameResult::kMalformed || result == bwm::FrameResult::kOversized)
      ++invalid_messages;
  }
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  if (strcmp(topic, kActivationTopic) && strcmp(topic, kWhisperStateTopic) &&
      strcmp(topic, kWhisperInteractionTopic)) return;
  processSemanticEvent(reinterpret_cast<const char*>(payload), length, false, "mqtt");
}

void serviceNetwork(uint32_t now) {
  if (!wifi_ssid.length()) return;
  if (WiFi.status() != WL_CONNECTED && bwm::reached(now, next_wifi_attempt)) {
    next_wifi_attempt = now + 10000;
    WiFi.begin(wifi_ssid.c_str(), wifi_password.c_str());
  }
  if (WiFi.status() != WL_CONNECTED) return;
  if (!mqtt_host.length()) return;
  if (!mqtt.connected() && bwm::reached(now, next_mqtt_attempt)) {
    next_mqtt_attempt = now + kReconnectMs;
    String client_id = "bwm-translation-" + String(static_cast<uint32_t>(ESP.getEfuseMac()), HEX);
    if (mqtt.connect(client_id.c_str())) {
      mqtt.subscribe(kActivationTopic, 1);
      mqtt.subscribe(kWhisperStateTopic, 1);
      mqtt.subscribe(kWhisperInteractionTopic, 1);
    }
  }
  if (mqtt.connected()) mqtt.loop();
}

bwm::BleFragmentFramer<4096> ble_reassembler;

void bleNotify(NimBLERemoteCharacteristic*, uint8_t* data, size_t length, bool) {
  const bwm::FrameResult result = ble_reassembler.feed(data, length);
  if (result == bwm::FrameResult::kComplete && ble_frames) {
    SemanticFrame frame{};
    memcpy(frame.bytes, ble_reassembler.data(), ble_reassembler.size());
    frame.bytes[ble_reassembler.size()] = 0;
    xQueueSend(ble_frames, &frame, 0);
  } else if (result == bwm::FrameResult::kMalformed || result == bwm::FrameResult::kOversized) {
    ++invalid_messages;
  }
}

void bleTask(void*) {
  NimBLEDevice::init("BWM Translation");
  NimBLEScan* scan = NimBLEDevice::getScan();
  scan->setActiveScan(true);
  for (;;) {
    NimBLEScanResults results = scan->start(8, false);
    for (int i = 0; i < results.getCount(); ++i) {
      NimBLEAdvertisedDevice device = results.getDevice(i);
      if (!device.isAdvertisingService(NimBLEUUID(kBleServiceUuid)) && device.getName() != "BWM Vision") continue;
      NimBLEClient* client = NimBLEDevice::createClient();
      if (client->connect(&device)) {
        NimBLERemoteService* service = client->getService(kBleServiceUuid);
        NimBLERemoteCharacteristic* characteristic = service ? service->getCharacteristic(kBleCharacteristicUuid) : nullptr;
        if (characteristic && characteristic->canNotify() && characteristic->subscribe(true, bleNotify)) {
          while (client->isConnected()) vTaskDelay(pdMS_TO_TICKS(500));
        }
      }
      if (client->isConnected()) client->disconnect();
      NimBLEDevice::deleteClient(client);
      break;
    }
    scan->clearResults();
    vTaskDelay(pdMS_TO_TICKS(1000));
  }
}

void loadDeploymentConfig() {
  preferences.begin("bwm", true);
  wifi_ssid = preferences.getString("wifi_ssid", BWM_WIFI_SSID);
  wifi_password = preferences.getString("wifi_password", BWM_WIFI_PASSWORD);
  mqtt_host = preferences.getString("mqtt_host", BWM_MQTT_HOST);
  mqtt_port = preferences.getUShort("mqtt_port", BWM_MQTT_PORT);
  preferences.end();
}

void serviceButton(uint32_t now) {
  const bool current = digitalRead(bwm::kBoard.button) != LOW;
  if (last_button && !current && bwm::reached(now, button_dead_until)) {
    button_dead_until = now + kButtonDeadtimeMs;
    toggleLocal();
  }
  last_button = current;
}

void logDiagnostics(uint32_t now) {
  if (!bwm::reached(now, next_diagnostic)) return;
  next_diagnostic = now + 30000;
  Serial.printf("[Status] session=%s reaction_busy=%s ble_queue=%u mqtt=%s uart=ready accepted=%lu rejected=%lu dup=%lu invalid=%lu fault=%s\n",
                session.active() ? "active" : "idle", reactionBusy(now) ? "yes" : "no",
                static_cast<unsigned>(uxQueueMessagesWaiting(ble_frames)), mqtt.connected() ? "up" : "down",
                static_cast<unsigned long>(accepted_pulses), static_cast<unsigned long>(rejected_pulses),
                static_cast<unsigned long>(duplicate_messages), static_cast<unsigned long>(invalid_messages),
                fault_latched ? "latched" : "none");
}

}  // namespace

void setup() {
  // Match the proven fallback sequence: preload LOW, claim OUTPUT, reaffirm LOW.
  // External MOSFET gate pull-downs remain mandatory during reset/boot.
  for (uint8_t pin : bwm::kBoard.outputs) {
    digitalWrite(pin, LOW);
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);
  }
  pinMode(bwm::kBoard.button, INPUT_PULLUP);
  Serial.begin(115200);
  whisper_uart.begin(115200, SERIAL_8N1, bwm::kBoard.uart_rx, bwm::kBoard.uart_tx);
  esp_task_wdt_init(8, true);
  esp_task_wdt_add(nullptr);
  loadDeploymentConfig();
  mqtt.setServer(mqtt_host.c_str(), mqtt_port);
  mqtt.setCallback(mqttCallback);
  mqtt.setBufferSize(kMaxSemanticFrame + 1);
  if (wifi_ssid.length()) {
    WiFi.mode(WIFI_STA);
    WiFi.begin(wifi_ssid.c_str(), wifi_password.c_str());
    configTime(0, 0, "pool.ntp.org", "time.cloudflare.com");
  }
  ble_frames = xQueueCreate(4, sizeof(SemanticFrame));
  xTaskCreatePinnedToCore(bleTask, "bwm-ble-central", 8192, nullptr, 1, nullptr, 0);
  Serial.printf("BWM autonomous Translation %s reset=%d board=%s score=%u sha=%s\n",
                kFirmwareVersion, static_cast<int>(esp_reset_reason()), bwm::kBoard.name,
                static_cast<unsigned>(bwm::kScoreEventCount), bwm::kScoreSourceSha256);
  if (bwm::kInitiallyActive) activate(false);
  // Startup synchronization is best effort and never gates local operation.
  publishAuthoritative(session.active() ? "active" : "inactive");
}

void loop() {
  const uint32_t now = millis();
  esp_task_wdt_reset();
  serviceUart();
  SemanticFrame frame{};
  while (xQueueReceive(ble_frames, &frame, 0) == pdTRUE)
    processSemanticEvent(frame.bytes, strlen(frame.bytes), false, "ble");
  serviceNetwork(now);
  serviceButton(now);
  if (session.timedOut(now)) teardown(true, "timeout");
  if (!fault_latched) dispatchScore(now);
  servicePulseQueue(now);
  if (reaction_window_active && bwm::reached(now, reaction_busy_until)) reaction_window_active = false;
  logDiagnostics(now);
  delay(1);
}
