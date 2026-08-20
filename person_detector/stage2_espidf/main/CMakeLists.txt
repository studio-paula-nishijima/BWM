idf_component_register(
    SRCS
        "app_main.cpp"
        "camera_source.cpp"
        "person_detector.cpp"
        "preview_server.cpp"
        "mqtt_activation_publisher.cpp"
    INCLUDE_DIRS "."
    # `esp_camera.h` is the public header, but the registry component itself
    # is named `esp32-camera`.
    REQUIRES esp32-camera esp-dl pedestrian_detect esp_psram esp_wifi esp_netif esp_event esp_http_server nvs_flash mqtt
)
