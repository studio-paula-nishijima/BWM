#include "preview_server.h"

#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <memory>
#include <new>

#include "cJSON.h"
#include "esp_event.h"
#include "esp_heap_caps.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/semphr.h"
#include "stage2b_config.h"

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
    PersonDetection person_detection;
    MotionDetection motion_detection;
    TriggerZoneConfig *trigger_zone = nullptr;
    MqttActivationPublisher *activation_publisher = nullptr;
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
<title>BWM vision node — rectangle calibration</title>
<style>
body{font:16px system-ui;margin:1.5rem;background:#111;color:#eee;max-width:56rem}#view{position:relative;line-height:0}img{width:100%;height:auto;border:1px solid #555}.overlay{position:absolute;box-sizing:border-box;pointer-events:none}.person{border:3px solid #58e06f}.motion{border:3px solid #35c9ff}.shadow{border:3px dashed #d76cff}.zone{border:3px dashed #ffb020;background:#ffb02018;z-index:3}.zone.editing{border-style:solid;background:#ffb02030;pointer-events:auto;cursor:move;touch-action:none}.handle{display:none;position:absolute;width:16px;height:16px;background:#ffb020;border:2px solid #111;border-radius:50%}.editing .handle{display:block}.nw{left:-10px;top:-10px;cursor:nwse-resize}.ne{right:-10px;top:-10px;cursor:nesw-resize}.sw{left:-10px;bottom:-10px;cursor:nesw-resize}.se{right:-10px;bottom:-10px;cursor:nwse-resize}.centre{width:9px;height:9px;margin:-4px 0 0 -4px;border-radius:50%;background:#ff496c}.controls{display:flex;flex-wrap:wrap;gap:.5rem;margin:1rem 0}.controls button{font:inherit;padding:.5rem .8rem}.controls button:disabled{opacity:.45}code{color:#9dd}
</style></head><body><h1>BWM vision node — rectangle calibration</h1>
<p>Orange: trigger zone. Cyan: accepted motion. Purple dashed: rejected likely shadow.</p>
<div id="view"><img id="camera" src="/capture" alt="Live camera preview"><div id="zone" class="overlay zone"><i class="handle nw" data-handle="nw"></i><i class="handle ne" data-handle="ne"></i><i class="handle sw" data-handle="sw"></i><i class="handle se" data-handle="se"></i></div><div id="overlays"></div></div>
<div class="controls"><button id="edit">Edit Trigger Zone</button><button id="apply" disabled>Apply</button><button id="save" disabled>Save</button><button id="cancel" disabled>Cancel</button><button id="reset">Reset to Default</button></div>
<div class="controls"><button id="testActivation">Send Test Activation</button></div><p id="mqttStatus">MQTT test trigger ready.</p>
<p><code id="zoneValues">Loading trigger zone…</code></p><p id="status">Waiting for a frame…</p><p><a href="/capture">Open one snapshot</a> · <a href="/status">Detection JSON</a></p>
<script>
const camera=document.getElementById('camera'),overlays=document.getElementById('overlays'),status=document.getElementById('status'),zoneBox=document.getElementById('zone'),zoneValues=document.getElementById('zoneValues');
const editButton=document.getElementById('edit'),applyButton=document.getElementById('apply'),saveButton=document.getElementById('save'),cancelButton=document.getElementById('cancel'),resetButton=document.getElementById('reset'),testActivationButton=document.getElementById('testActivation'),mqttStatus=document.getElementById('mqttStatus'),MIN_SIZE=.05;
let serverZone={x:.2,y:.2,w:.6,h:.6},editZone={...serverZone},preEditZone={...serverZone},editing=false,drag=null,framePending=false,statusPending=false;
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
function renderZone(z){zoneBox.style.left=(z.x*100)+'%';zoneBox.style.top=(z.y*100)+'%';zoneBox.style.width=(z.w*100)+'%';zoneBox.style.height=(z.h*100)+'%';zoneValues.textContent='x='+z.x.toFixed(3)+' y='+z.y.toFixed(3)+' w='+z.w.toFixed(3)+' h='+z.h.toFixed(3)}
function rect(cls,x,y,w,h){const e=document.createElement('div');e.className='overlay '+cls;e.style.left=(x*100)+'%';e.style.top=(y*100)+'%';e.style.width=(w*100)+'%';e.style.height=(h*100)+'%';overlays.appendChild(e)}
function point(x,y){const e=document.createElement('div');e.className='overlay centre';e.style.left=(x*100)+'%';e.style.top=(y*100)+'%';overlays.appendChild(e)}
function setEditing(value){editing=value;zoneBox.classList.toggle('editing',value);editButton.disabled=value;applyButton.disabled=!value;saveButton.disabled=!value;cancelButton.disabled=!value}
async function api(path,body){const options={method:'POST'};if(body){options.headers={'Content-Type':'application/json'};options.body=JSON.stringify({trigger_zone:body})}const response=await fetch(path,options);if(!response.ok)throw new Error(await response.text());return response.json()}
async function loadZone(){const response=await fetch('/api/config/trigger-zone?t='+Date.now());if(!response.ok)throw new Error(await response.text());const data=await response.json();serverZone={...data.trigger_zone};editZone={...serverZone};renderZone(serverZone)}
editButton.onclick=()=>{preEditZone={...serverZone};editZone={...serverZone};setEditing(true);renderZone(editZone)};
applyButton.onclick=async()=>{try{const data=await api('/api/config/trigger-zone',editZone);serverZone={...data.trigger_zone};editZone={...serverZone};renderZone(editZone)}catch(error){status.textContent='Apply failed: '+error.message}};
saveButton.onclick=async()=>{try{let data=await api('/api/config/trigger-zone',editZone);serverZone={...data.trigger_zone};data=await api('/api/config/trigger-zone/save');serverZone={...data.trigger_zone};editZone={...serverZone};setEditing(false);renderZone(serverZone)}catch(error){status.textContent='Save failed: '+error.message}};
cancelButton.onclick=async()=>{try{const data=await api('/api/config/trigger-zone',preEditZone);serverZone={...data.trigger_zone};editZone={...serverZone};setEditing(false);renderZone(serverZone)}catch(error){status.textContent='Cancel failed: '+error.message}};
resetButton.onclick=async()=>{try{const data=await api('/api/config/trigger-zone/reset');serverZone={...data.trigger_zone};editZone={...serverZone};renderZone(editing?editZone:serverZone)}catch(error){status.textContent='Reset failed: '+error.message}};
testActivationButton.onclick=async()=>{testActivationButton.disabled=true;mqttStatus.textContent='Sending test activation…';try{const data=await api('/api/test/activation');mqttStatus.textContent='Test activation queued · event '+data.event_id}catch(error){mqttStatus.textContent='Test activation failed: '+error.message}finally{testActivationButton.disabled=false}};
zoneBox.addEventListener('pointerdown',event=>{if(!editing)return;event.preventDefault();zoneBox.setPointerCapture(event.pointerId);drag={handle:event.target.dataset.handle||'move',x:event.clientX,y:event.clientY,zone:{...editZone}}});
zoneBox.addEventListener('pointermove',event=>{if(!drag)return;const image=camera.getBoundingClientRect();if(!image.width||!image.height)return;const dx=(event.clientX-drag.x)/image.width,dy=(event.clientY-drag.y)/image.height,s=drag.zone;let left=s.x,top=s.y,right=s.x+s.w,bottom=s.y+s.h;if(drag.handle==='move'){left=clamp(s.x+dx,0,1-s.w);top=clamp(s.y+dy,0,1-s.h);right=left+s.w;bottom=top+s.h}else{if(drag.handle.includes('w'))left=clamp(s.x+dx,0,right-MIN_SIZE);if(drag.handle.includes('e'))right=clamp(s.x+s.w+dx,left+MIN_SIZE,1);if(drag.handle.includes('n'))top=clamp(s.y+dy,0,bottom-MIN_SIZE);if(drag.handle.includes('s'))bottom=clamp(s.y+s.h+dy,top+MIN_SIZE,1)}editZone={x:left,y:top,w:right-left,h:bottom-top};renderZone(editZone)});
zoneBox.addEventListener('pointerup',()=>drag=null);zoneBox.addEventListener('pointercancel',()=>drag=null);
function refreshFrame(){if(framePending)return;framePending=true;camera.onload=()=>framePending=false;camera.onerror=()=>framePending=false;camera.src='/capture?t='+Date.now()}
async function refreshStatus(){if(statusPending)return;statusPending=true;try{const response=await fetch('/status?t='+Date.now());if(!response.ok)throw new Error();const d=await response.json();overlays.replaceChildren();if(d.mode==='motion'){if(!editing&&d.zone){serverZone={...d.zone};editZone={...serverZone};renderZone(serverZone)}for(const b of d.boxes){rect('motion',b.x,b.y,b.w,b.h);point(b.cx,b.cy)}for(const b of(d.rejected_boxes||[]))rect('shadow',b.x,b.y,b.w,b.h);status.textContent='MOTION '+(d.motion?'yes':'no')+' · changed '+(d.changed_fraction*100).toFixed(2)+'% · in-zone '+(d.in_zone_hit?'yes':'no')+' · confirmed '+(d.confirmed?'YES':'no')+' · '+d.reason}else{if(d.person)rect('person',d.x,d.y,d.w,d.h);status.textContent=(d.person?'PERSON':'no person')+' · confidence '+d.confidence.toFixed(3)+' · inference '+d.inference_ms+' ms'}}catch(error){status.textContent='Waiting for detector…'}finally{statusPending=false}}
function refresh(){refreshFrame();refreshStatus()}
loadZone().catch(error=>status.textContent='Config load failed: '+error.message);refresh();setInterval(refresh,1000);
</script></body></html>)HTML";

void wifiEventHandler(void *, esp_event_base_t event_base, int32_t event_id, void *)
{
    if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP && gPreview != nullptr) {
        xEventGroupSetBits(gPreview->wifi_events, kWifiConnectedBit);
    }
}

esp_err_t indexHandler(httpd_req_t *request)
{
    httpd_resp_set_type(request, "text/html");
    httpd_resp_set_hdr(request, "Cache-Control", "no-store, no-cache, must-revalidate");
    return httpd_resp_send(request, kIndexHtml, HTTPD_RESP_USE_STRLEN);
}

esp_err_t unavailable(httpd_req_t *request, const char *message)
{
    httpd_resp_set_status(request, "503 Service Unavailable");
    httpd_resp_set_type(request, "text/plain");
    return httpd_resp_sendstr(request, message);
}

esp_err_t sendApiError(httpd_req_t *request, const char *status, const char *message)
{
    httpd_resp_set_status(request, status);
    httpd_resp_set_type(request, "application/json");
    char json[160];
    std::snprintf(json, sizeof(json), "{\"error\":\"%s\"}", message);
    return httpd_resp_sendstr(request, json);
}

esp_err_t sendZoneJson(httpd_req_t *request, const NormalisedZone &zone)
{
    char json[180];
    std::snprintf(json, sizeof(json),
                  "{\"trigger_zone\":{\"x\":%.6f,\"y\":%.6f,\"w\":%.6f,\"h\":%.6f}}",
                  zone.x, zone.y, zone.width, zone.height);
    httpd_resp_set_type(request, "application/json");
    httpd_resp_set_hdr(request, "Cache-Control", "no-store");
    return httpd_resp_sendstr(request, json);
}

bool readZoneJson(httpd_req_t *request, NormalisedZone &zone)
{
    if (request->content_len <= 0 || request->content_len > 256) return false;
    char body[257];
    size_t received = 0;
    while (received < static_cast<size_t>(request->content_len)) {
        const int count = httpd_req_recv(request, body + received, request->content_len - received);
        if (count <= 0) return false;
        received += count;
    }
    body[received] = '\0';
    cJSON *root = cJSON_ParseWithLength(body, received);
    if (root == nullptr) return false;
    const cJSON *candidate = cJSON_GetObjectItemCaseSensitive(root, "trigger_zone");
    if (!cJSON_IsObject(candidate)) candidate = root;
    const cJSON *x = cJSON_GetObjectItemCaseSensitive(candidate, "x");
    const cJSON *y = cJSON_GetObjectItemCaseSensitive(candidate, "y");
    const cJSON *w = cJSON_GetObjectItemCaseSensitive(candidate, "w");
    const cJSON *h = cJSON_GetObjectItemCaseSensitive(candidate, "h");
    const bool valid_numbers = cJSON_IsNumber(x) && cJSON_IsNumber(y) &&
        cJSON_IsNumber(w) && cJSON_IsNumber(h);
    if (valid_numbers) {
        zone = {static_cast<float>(x->valuedouble), static_cast<float>(y->valuedouble),
                static_cast<float>(w->valuedouble), static_cast<float>(h->valuedouble)};
    }
    cJSON_Delete(root);
    return valid_numbers && TriggerZoneConfig::valid(zone);
}

esp_err_t getZoneHandler(httpd_req_t *request)
{
    if (gPreview == nullptr || gPreview->trigger_zone == nullptr) return httpd_resp_send_404(request);
    return sendZoneJson(request, gPreview->trigger_zone->current());
}

esp_err_t applyZoneHandler(httpd_req_t *request)
{
    if (gPreview == nullptr || gPreview->trigger_zone == nullptr) return httpd_resp_send_404(request);
    NormalisedZone zone = {};
    if (!readZoneJson(request, zone)) {
        ESP_LOGW(kTag, "rejected malformed or invalid trigger-zone request");
        return sendApiError(request, "400 Bad Request", "invalid trigger zone");
    }
    if (!gPreview->trigger_zone->apply(zone)) {
        return sendApiError(request, "503 Service Unavailable", "could not apply trigger zone");
    }
    return sendZoneJson(request, zone);
}

esp_err_t saveZoneHandler(httpd_req_t *request)
{
    if (gPreview == nullptr || gPreview->trigger_zone == nullptr) return httpd_resp_send_404(request);
    if (!gPreview->trigger_zone->save()) {
        return sendApiError(request, "500 Internal Server Error", "persistent save failed");
    }
    return sendZoneJson(request, gPreview->trigger_zone->current());
}

esp_err_t resetZoneHandler(httpd_req_t *request)
{
    if (gPreview == nullptr || gPreview->trigger_zone == nullptr) return httpd_resp_send_404(request);
    gPreview->trigger_zone->resetToDefault();
    return sendZoneJson(request, gPreview->trigger_zone->current());
}

esp_err_t testActivationHandler(httpd_req_t *request)
{
    if (gPreview == nullptr || gPreview->activation_publisher == nullptr) {
        return sendApiError(request, "503 Service Unavailable", "activation publisher unavailable");
    }
    char event_id[37] = {};
    if (!gPreview->activation_publisher->publishManualActivation(event_id, sizeof(event_id))) {
        return sendApiError(request, "503 Service Unavailable",
                            "MQTT activation was not queued; check serial log");
    }
    char json[128];
    std::snprintf(json, sizeof(json),
                  "{\"published\":true,\"event_id\":\"%s\",\"source\":\"manual_test\"}",
                  event_id);
    httpd_resp_set_type(request, "application/json");
    httpd_resp_set_hdr(request, "Cache-Control", "no-store");
    return httpd_resp_sendstr(request, json);
}

esp_err_t captureHandler(httpd_req_t *request)
{
    if (gPreview == nullptr) return httpd_resp_send_404(request);
    auto *impl = gPreview;
    if (xSemaphoreTake(impl->mutex, pdMS_TO_TICKS(1000)) != pdTRUE) return unavailable(request, "Preview busy");
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

bool appendJson(char *buffer, size_t capacity, size_t &used, const char *format, ...)
{
    if (used >= capacity) return false;
    va_list arguments;
    va_start(arguments, format);
    const int written = std::vsnprintf(buffer + used, capacity - used, format, arguments);
    va_end(arguments);
    if (written < 0 || static_cast<size_t>(written) >= capacity - used) {
        used = capacity;
        return false;
    }
    used += static_cast<size_t>(written);
    return true;
}

esp_err_t statusHandler(httpd_req_t *request)
{
    if (gPreview == nullptr) return httpd_resp_send_404(request);
    auto *impl = gPreview;
    if (xSemaphoreTake(impl->mutex, pdMS_TO_TICKS(100)) != pdTRUE) return unavailable(request, "Preview busy");
    const PersonDetection person = impl->person_detection;
    const MotionDetection motion = impl->motion_detection;
    xSemaphoreGive(impl->mutex);
    const NormalisedZone zone = impl->trigger_zone == nullptr ?
        kDefaultMotionTriggerZone : impl->trigger_zone->current();

    char json[4096];
    size_t used = 0;
    bool complete = true;
    if (!motionModeEnabled()) {
        complete = appendJson(json, sizeof(json), used,
                              "{\"mode\":\"person\",\"person\":%s,\"confidence\":%.4f,"
                              "\"x\":%.4f,\"y\":%.4f,\"w\":%.4f,\"h\":%.4f,\"inference_ms\":%u}",
                              person.person ? "true" : "false", person.confidence, person.x, person.y,
                              person.width, person.height, static_cast<unsigned>(person.inference_ms));
    } else {
        complete = appendJson(json, sizeof(json), used,
                              "{\"mode\":\"motion\",\"motion\":%s,\"changed_fraction\":%.5f,"
                              "\"luminance_shift\":%.3f,\"illumination_change\":%s,"
                              "\"largest_blob_area\":%.5f,\"in_zone_hit\":%s,\"recent_hits\":%u,"
                              "\"recent_count\":%u,\"confirmed\":%s,\"strong_in_zone\":%s,\"reason\":\"%s\","
                              "\"zone\":{\"x\":%.5f,\"y\":%.5f,\"w\":%.5f,\"h\":%.5f},\"boxes\":[",
                              motion.motion ? "true" : "false", motion.changed_fraction,
                              motion.global_luminance_shift, motion.illumination_change ? "true" : "false",
                              motion.largest_blob_area, motion.in_zone_hit ? "true" : "false",
                              static_cast<unsigned>(motion.recent_hits), static_cast<unsigned>(motion.recent_count),
                              motion.confirmed ? "true" : "false", motion.strong_in_zone_motion ? "true" : "false",
                              motionConfirmationReasonName(motion.confirmation_reason),
                              zone.x, zone.y, zone.width, zone.height);
        for (size_t index = 0; complete && index < motion.box_count; ++index) {
            const MotionBox &box = motion.boxes[index];
            complete = appendJson(json, sizeof(json), used,
                                  "%s{\"x\":%.4f,\"y\":%.4f,\"w\":%.4f,\"h\":%.4f,"
                                  "\"cx\":%.4f,\"cy\":%.4f,\"area\":%.5f,\"luma\":%.2f,\"structure\":%.2f,"
                                  "\"strong\":%s,\"inside_zone\":%s}",
                                  index == 0 ? "" : ",", box.x, box.y, box.width, box.height,
                                  box.centre_x, box.centre_y, box.area_fraction, box.mean_luminance_change,
                                  box.mean_structure_change, box.strong_motion ? "true" : "false",
                                  box.inside_trigger_zone ? "true" : "false");
        }
        complete = complete && appendJson(json, sizeof(json), used, "],\"rejected_boxes\":[");
        for (size_t index = 0; complete && index < motion.rejected_box_count; ++index) {
            const MotionBox &box = motion.rejected_boxes[index];
            complete = appendJson(json, sizeof(json), used,
                                  "%s{\"x\":%.4f,\"y\":%.4f,\"w\":%.4f,\"h\":%.4f,"
                                  "\"cx\":%.4f,\"cy\":%.4f,\"area\":%.5f,\"luma\":%.2f,"
                                  "\"structure\":%.2f,\"inside_zone\":%s}",
                                  index == 0 ? "" : ",", box.x, box.y, box.width, box.height,
                                  box.centre_x, box.centre_y, box.area_fraction, box.mean_luminance_change,
                                  box.mean_structure_change, box.inside_trigger_zone ? "true" : "false");
        }
        complete = complete && appendJson(json, sizeof(json), used, "]}");
    }
    if (!complete) return sendApiError(request, "500 Internal Server Error", "status JSON overflow");
    httpd_resp_set_type(request, "application/json");
    httpd_resp_set_hdr(request, "Cache-Control", "no-store");
    return httpd_resp_sendstr(request, json);
}
}  // namespace

bool PreviewServer::begin(TriggerZoneConfig &trigger_zone,
                          MqttActivationPublisher &activation_publisher)
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
    impl_->trigger_zone = &trigger_zone;
    impl_->activation_publisher = &activation_publisher;
    if (impl_->frame == nullptr || impl_->mutex == nullptr || impl_->wifi_events == nullptr) {
        ESP_LOGE(kTag, "could not allocate preview resources");
        return false;
    }

    gPreview = impl_;
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
    server_config.stack_size = 8192;
    server_config.max_uri_handlers = 9;
    server_config.max_open_sockets = 4;
    server_config.lru_purge_enable = true;
    if (httpd_start(&impl_->server, &server_config) != ESP_OK) return false;
    const httpd_uri_t index = {.uri = "/", .method = HTTP_GET, .handler = indexHandler, .user_ctx = nullptr};
    const httpd_uri_t capture = {.uri = "/capture", .method = HTTP_GET, .handler = captureHandler, .user_ctx = nullptr};
    const httpd_uri_t status = {.uri = "/status", .method = HTTP_GET, .handler = statusHandler, .user_ctx = nullptr};
    const httpd_uri_t get_zone = {.uri = "/api/config/trigger-zone", .method = HTTP_GET, .handler = getZoneHandler, .user_ctx = nullptr};
    const httpd_uri_t apply_zone = {.uri = "/api/config/trigger-zone", .method = HTTP_POST, .handler = applyZoneHandler, .user_ctx = nullptr};
    const httpd_uri_t save_zone = {.uri = "/api/config/trigger-zone/save", .method = HTTP_POST, .handler = saveZoneHandler, .user_ctx = nullptr};
    const httpd_uri_t reset_zone = {.uri = "/api/config/trigger-zone/reset", .method = HTTP_POST, .handler = resetZoneHandler, .user_ctx = nullptr};
    const httpd_uri_t test_activation = {.uri = "/api/test/activation", .method = HTTP_POST, .handler = testActivationHandler, .user_ctx = nullptr};
    ESP_ERROR_CHECK(httpd_register_uri_handler(impl_->server, &index));
    ESP_ERROR_CHECK(httpd_register_uri_handler(impl_->server, &capture));
    ESP_ERROR_CHECK(httpd_register_uri_handler(impl_->server, &status));
    ESP_ERROR_CHECK(httpd_register_uri_handler(impl_->server, &get_zone));
    ESP_ERROR_CHECK(httpd_register_uri_handler(impl_->server, &apply_zone));
    ESP_ERROR_CHECK(httpd_register_uri_handler(impl_->server, &save_zone));
    ESP_ERROR_CHECK(httpd_register_uri_handler(impl_->server, &reset_zone));
    ESP_ERROR_CHECK(httpd_register_uri_handler(impl_->server, &test_activation));

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

void PreviewServer::publishPersonDetection(const PersonDetection &detection)
{
    if (impl_ == nullptr) return;
    if (xSemaphoreTake(impl_->mutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        impl_->person_detection = detection;
        xSemaphoreGive(impl_->mutex);
    }
}

void PreviewServer::publishMotionDetection(const MotionDetection &detection)
{
    if (impl_ == nullptr) return;
    if (xSemaphoreTake(impl_->mutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        impl_->motion_detection = detection;
        xSemaphoreGive(impl_->mutex);
    }
}
