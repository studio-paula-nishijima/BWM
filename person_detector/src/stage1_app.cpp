#include "stage1_app.h"

#include <Arduino.h>
#include <cstring>
#include <WebServer.h>
#include <WiFi.h>
#include "esp_camera.h"

// This optional file is ignored by Git.  Empty defaults allow a hardware-only
// camera test to compile before temporary development Wi-Fi is configured.
#if __has_include("../wifi_credentials.h")
#include "../wifi_credentials.h"
#else
#define BWM_WIFI_SSID ""
#define BWM_WIFI_PASSWORD ""
#endif

namespace {

constexpr uint32_t kSerialBaud = 115200;
constexpr uint32_t kWifiTimeoutMs = 20000;
constexpr uint32_t kCameraDiagnosticIntervalMs = 10000;

// Seeed Studio XIAO ESP32S3 Sense camera expansion-board wiring (OV2640/OV5640).
constexpr int kCameraPinPwdn = -1;
constexpr int kCameraPinReset = -1;
constexpr int kCameraPinXclk = 10;
constexpr int kCameraPinSiod = 40;
constexpr int kCameraPinSioc = 39;
constexpr int kCameraPinD7 = 48;
constexpr int kCameraPinD6 = 11;
constexpr int kCameraPinD5 = 12;
constexpr int kCameraPinD4 = 14;
constexpr int kCameraPinD3 = 16;
constexpr int kCameraPinD2 = 18;
constexpr int kCameraPinD1 = 17;
constexpr int kCameraPinD0 = 15;
constexpr int kCameraPinVsync = 38;
constexpr int kCameraPinHref = 47;
constexpr int kCameraPinPclk = 13;

WebServer server(80);
bool cameraReady = false;
uint32_t lastCameraDiagnosticMs = 0;

const char kIndexHtml[] PROGMEM = R"HTML(
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BWM vision node — Stage 1</title>
<style>body{font:16px system-ui;margin:2rem;background:#111;color:#eee}img{display:block;max-width:100%;height:auto;border:1px solid #555}code{color:#9dd}</style>
</head><body>
<h1>BWM vision node — Stage 1</h1>
<p>Camera preview. This is a JPEG snapshot refreshed four times per second; it is intentionally simple while camera reliability is established.</p>
<img id="camera" src="/capture" alt="Live camera preview">
<p><a href="/capture">Open one snapshot</a> · <a href="/health">Health diagnostics</a></p>
<script>const camera=document.getElementById('camera');setInterval(()=>camera.src='/capture?t='+Date.now(),250);</script>
</body></html>
)HTML";

bool initialiseCamera() {
  camera_config_t config{};
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = kCameraPinD0;
  config.pin_d1 = kCameraPinD1;
  config.pin_d2 = kCameraPinD2;
  config.pin_d3 = kCameraPinD3;
  config.pin_d4 = kCameraPinD4;
  config.pin_d5 = kCameraPinD5;
  config.pin_d6 = kCameraPinD6;
  config.pin_d7 = kCameraPinD7;
  config.pin_xclk = kCameraPinXclk;
  config.pin_pclk = kCameraPinPclk;
  config.pin_vsync = kCameraPinVsync;
  config.pin_href = kCameraPinHref;
  config.pin_sccb_sda = kCameraPinSiod;
  config.pin_sccb_scl = kCameraPinSioc;
  config.pin_pwdn = kCameraPinPwdn;
  config.pin_reset = kCameraPinReset;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size = FRAMESIZE_VGA;
  config.jpeg_quality = 12;
  config.fb_count = 2;
  config.grab_mode = CAMERA_GRAB_LATEST;
  config.fb_location = CAMERA_FB_IN_PSRAM;

  if (!psramFound()) {
    Serial.println("FATAL: PSRAM not found. Check board selection and PSRAM settings.");
    return false;
  }

  const esp_err_t error = esp_camera_init(&config);
  if (error != ESP_OK) {
    Serial.printf("FATAL: camera init failed: 0x%x\n", error);
    return false;
  }

  // One startup capture verifies that the configured sensor is returning JPEG.
  camera_fb_t *frame = esp_camera_fb_get();
  if (frame == nullptr) {
    Serial.println("FATAL: camera initialised but first frame capture failed.");
    esp_camera_deinit();
    return false;
  }
  Serial.printf("Camera ready: %ux%u, JPEG, first frame %u bytes\n", frame->width,
                frame->height, frame->len);
  esp_camera_fb_return(frame);
  return true;
}

void handleCapture() {
  if (!cameraReady) {
    server.send(503, "text/plain", "Camera is not ready");
    return;
  }
  camera_fb_t *frame = esp_camera_fb_get();
  if (frame == nullptr) {
    Serial.println("ERROR: camera frame capture failed for HTTP request.");
    server.send(503, "text/plain", "Camera capture failed");
    return;
  }
  server.sendHeader("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0");
  server.setContentLength(frame->len);
  server.send(200, "image/jpeg", "");
  WiFiClient client = server.client();
  client.write(frame->buf, frame->len);
  esp_camera_fb_return(frame);
}

void handleHealth() {
  const String body = String("{\"camera_ready\":") + (cameraReady ? "true" : "false") +
                      ",\"psram_found\":" + (psramFound() ? "true" : "false") +
                      ",\"wifi_connected\":" + (WiFi.status() == WL_CONNECTED ? "true" : "false") +
                      ",\"ip\":\"" + WiFi.localIP().toString() + "\"}";
  server.send(200, "application/json", body);
}

void startWebServer() {
  server.on("/", HTTP_GET, []() { server.send_P(200, "text/html", kIndexHtml); });
  server.on("/capture", HTTP_GET, handleCapture);
  server.on("/health", HTTP_GET, handleHealth);
  server.onNotFound([]() { server.send(404, "text/plain", "Not found"); });
  server.begin();
  Serial.println("HTTP server started: / (preview), /capture (JPEG), /health (JSON)");
}

bool connectWifi() {
  if (strlen(BWM_WIFI_SSID) == 0) {
    Serial.println("WiFi not configured. Copy include/wifi_credentials.h.example to wifi_credentials.h.");
    return false;
  }

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(BWM_WIFI_SSID, BWM_WIFI_PASSWORD);
  Serial.printf("WiFi connecting to '%s'", BWM_WIFI_SSID);
  const uint32_t startedAt = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - startedAt < kWifiTimeoutMs) {
    delay(250);
    Serial.print('.');
  }
  Serial.println();
  if (WiFi.status() != WL_CONNECTED) {
    Serial.printf("WiFi connection failed (status %d). Camera test remains available over serial.\n", WiFi.status());
    return false;
  }
  Serial.printf("WiFi connected. Open http://%s/\n", WiFi.localIP().toString().c_str());
  return true;
}

void logPeriodicCameraDiagnostic() {
  if (!cameraReady || millis() - lastCameraDiagnosticMs < kCameraDiagnosticIntervalMs) {
    return;
  }
  lastCameraDiagnosticMs = millis();
  camera_fb_t *frame = esp_camera_fb_get();
  if (frame == nullptr) {
    Serial.println("ERROR: periodic camera capture failed.");
    return;
  }
  Serial.printf(
      "Camera capture OK: %ux%u, %u bytes, WiFi status %d, IP %s, free heap %u, free PSRAM %u\n",
      frame->width, frame->height, frame->len, WiFi.status(), WiFi.localIP().toString().c_str(),
      ESP.getFreeHeap(), ESP.getFreePsram());
  esp_camera_fb_return(frame);
}

}  // namespace

void stage1Setup() {
  Serial.begin(kSerialBaud);
  delay(1000);
  Serial.println("\nBWM Vision Node — Stage 1 baseline");
  Serial.printf("Chip: %s, PSRAM: %u bytes\n", ESP.getChipModel(), ESP.getPsramSize());

  cameraReady = initialiseCamera();
  if (!cameraReady) {
    Serial.println("Camera baseline stopped. Fix the reported problem and reset the board.");
    return;
  }

  if (connectWifi()) {
    startWebServer();
  }
}

void stage1Loop() {
  if (cameraReady) {
    logPeriodicCameraDiagnostic();
  }
  server.handleClient();
  delay(2);
}
