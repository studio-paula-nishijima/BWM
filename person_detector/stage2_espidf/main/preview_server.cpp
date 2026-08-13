#include "preview_server.h"

#include <cstdio>
#include <cstring>
#include <new>

#include "esp_event.h"
#include "esp_heap_caps.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/semphr.h"
#include "nvs_flash.h"

// Reuse the deliberately ignored local development credentials from Stage 1.
#if __has_include("../../wifi_credentials.h")
#include "../../wifi_credentials.h"
#else
#define BWM_WIFI_SSID ""
#define BWM_WIFI_PASSWORD ""
#endif

class PreviewServer::Impl {
public:
    EventGroupHandle_t wifi_events = nullptr;
    SemaphoreHandle_t mutex = nullptr;
    uint8_t *frame = nullptr;
    size_t frame_length = 0;
    PersonDetection detection;
    httpd_handle_t server = nullptr;
};

namespace {
constexpr char kTag[] = "bwm.preview";
constexpr EventBits_t kWifiConnectedBit = BIT0;
constexpr TickType_t kWifiTimeout = pdMS_TO_TICKS(20000);
constexpr size_t kPreviewCapacity = 128 * 1024;
PreviewServer::Impl *gPreview = nullptr;

const char kIndexHtml[] = R"HTML(<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BWM vision node — Stage 2</title>
<style>body{font:16px system-ui;margin:1.5rem;background:#111;color:#eee;max-width:48rem}#view{position:relative;line-height:0}img{width:100%;height:auto;border:1px solid #555}.box{position:absolute;border:3px solid #58e06f;display:none;box-sizing:border-box}code{color:#9dd}</style>
</head><body><h1>BWM vision node — Stage 2</h1><p>Low-rate camera preview and latest pedestrian-model result.</p>
<div id="view"><img id="camera" src="/capture" alt="Live camera preview"><div id="box" class="box"></div></div>
<p id="status">Waiting for a frame…</p><p><a href="/capture">Open one snapshot</a> · <a href="/status">Detection JSON</a></p>
<script>
const camera=document.getElementById('camera'),box=document.getElementById('box'),status=document.getElementById('status');
function refresh(){camera.src='/capture?t='+Date.now();fetch('/status?t='+Date.now()).then(r=>r.json()).then(d=>{status.textContent=`${d.person?'PERSON':'no person'} · confidence ${d.confidence.toFixed(3)} · inference ${d.inference_ms} ms`;box.style.display=d.person?'block':'none';if(d.person){box.style.left=(d.x*100)+'%';box.style.top=(d.y*100)+'%';box.style.width=(d.w*100)+'%';box.style.height=(d.h*100)+'%';}}).catch(()=>status.textContent='Waiting for detector…');}
refresh();setInterval(refresh,700);
</script></body></html>)HTML";

void wifiEventHandler(void *, esp_event_base_t event_base, int32_t event_id, void *event_data)
{
    if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP && gPreview != nullptr) {
        xEventGroupSetBits(gPreview->wifi_events, kWifiConnectedBit);
    }
}

esp_err_t indexHandler(httpd_req_t *request)
{
    httpd_resp_set_type(request, "text/html");
    return httpd_resp_send(request, kIndexHtml, HTTPD_RESP_USE_STRLEN);
}

esp_err_t unavailable(httpd_req_t *request, const char *message)
{
    httpd_resp_set_status(request, "503 Service Unavailable");
    httpd_resp_set_type(request, "text/plain");
    return httpd_resp_sendstr(request, message);
}

esp_err_t captureHandler(httpd_req_t *request)
{
    if (gPreview == nullptr) return httpd_resp_send_404(request);
    auto *impl = gPreview;
    if (xSemaphoreTake(impl->mutex, pdMS_TO_TICKS(1000)) != pdTRUE) {
        return unavailable(request, "Preview busy");
    }
    if (impl->frame_length == 0) {
        xSemaphoreGive(impl->mutex);
        return unavailable(request, "Waiting for first camera frame");
    }
    httpd_resp_set_type(request, "image/jpeg");
    httpd_resp_set_hdr(request, "Cache-Control", "no-store, no-cache, must-revalidate, max-age=0");
    const esp_err_t result = httpd_resp_send(request, reinterpret_cast<const char *>(impl->frame), impl->frame_length);
    xSemaphoreGive(impl->mutex);
    return result;
}

esp_err_t statusHandler(httpd_req_t *request)
{
    if (gPreview == nullptr) return httpd_resp_send_404(request);
    auto *impl = gPreview;
    if (xSemaphoreTake(impl->mutex, pdMS_TO_TICKS(100)) != pdTRUE) {
        return unavailable(request, "Preview busy");
    }
    const PersonDetection detection = impl->detection;
    char json[220];
    std::snprintf(json, sizeof(json),
                  "{\"person\":%s,\"confidence\":%.4f,\"x\":%.4f,\"y\":%.4f,\"w\":%.4f,\"h\":%.4f,\"inference_ms\":%u}",
                  detection.person ? "true" : "false", detection.confidence, detection.x, detection.y,
                  detection.width, detection.height, static_cast<unsigned>(detection.inference_ms));
    xSemaphoreGive(impl->mutex);
    httpd_resp_set_type(request, "application/json");
    httpd_resp_set_hdr(request, "Cache-Control", "no-store");
    return httpd_resp_sendstr(request, json);
}
}  // namespace

bool PreviewServer::begin()
{
    if (std::strlen(BWM_WIFI_SSID) == 0) {
        ESP_LOGW(kTag, "Wi-Fi is not configured; preview server disabled");
        return false;
    }
    impl_ = new (std::nothrow) Impl();
    if (impl_ == nullptr) return false;
    impl_->frame = static_cast<uint8_t *>(heap_caps_malloc(kPreviewCapacity, MALLOC_CAP_SPIRAM));
    impl_->mutex = xSemaphoreCreateMutex();
    impl_->wifi_events = xEventGroupCreate();
    if (impl_->frame == nullptr || impl_->mutex == nullptr || impl_->wifi_events == nullptr) {
        ESP_LOGE(kTag, "could not allocate preview resources");
        return false;
    }

    gPreview = impl_;
    ESP_ERROR_CHECK(nvs_flash_init());
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifiEventHandler, nullptr, nullptr));

    wifi_config_t config = {};
    std::strncpy(reinterpret_cast<char *>(config.sta.ssid), BWM_WIFI_SSID, sizeof(config.sta.ssid) - 1);
    std::strncpy(reinterpret_cast<char *>(config.sta.password), BWM_WIFI_PASSWORD, sizeof(config.sta.password) - 1);
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &config));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    ESP_ERROR_CHECK(esp_wifi_connect());
    if ((xEventGroupWaitBits(impl_->wifi_events, kWifiConnectedBit, pdFALSE, pdTRUE, kWifiTimeout) & kWifiConnectedBit) == 0) {
        ESP_LOGW(kTag, "Wi-Fi did not connect within 20 seconds; preview server disabled");
        return false;
    }

    httpd_config_t server_config = HTTPD_DEFAULT_CONFIG();
    server_config.stack_size = 6144;
    if (httpd_start(&impl_->server, &server_config) != ESP_OK) return false;
    const httpd_uri_t index = {.uri = "/", .method = HTTP_GET, .handler = indexHandler, .user_ctx = nullptr};
    const httpd_uri_t capture = {.uri = "/capture", .method = HTTP_GET, .handler = captureHandler, .user_ctx = nullptr};
    const httpd_uri_t status = {.uri = "/status", .method = HTTP_GET, .handler = statusHandler, .user_ctx = nullptr};
    ESP_ERROR_CHECK(httpd_register_uri_handler(impl_->server, &index));
    ESP_ERROR_CHECK(httpd_register_uri_handler(impl_->server, &capture));
    ESP_ERROR_CHECK(httpd_register_uri_handler(impl_->server, &status));

    esp_netif_ip_info_t ip = {};
    esp_netif_get_ip_info(esp_netif_get_handle_from_ifkey("WIFI_STA_DEF"), &ip);
    ESP_LOGI(kTag, "preview ready: open http://" IPSTR "/", IP2STR(&ip.ip));
    return true;
}

void PreviewServer::publishFrame(const camera_fb_t &camera_frame)
{
    if (impl_ == nullptr || camera_frame.format != PIXFORMAT_JPEG || camera_frame.len > kPreviewCapacity) return;
    if (xSemaphoreTake(impl_->mutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        std::memcpy(impl_->frame, camera_frame.buf, camera_frame.len);
        impl_->frame_length = camera_frame.len;
        xSemaphoreGive(impl_->mutex);
    }
}

void PreviewServer::publishDetection(const PersonDetection &detection)
{
    if (impl_ == nullptr) return;
    if (xSemaphoreTake(impl_->mutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        impl_->detection = detection;
        xSemaphoreGive(impl_->mutex);
    }
}
