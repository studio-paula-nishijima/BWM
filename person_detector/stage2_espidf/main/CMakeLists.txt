idf_component_register(
    SRCS
        "app_main.cpp"
        "camera_source.cpp"
        "activation_event.cpp"
        "activation_transport.cpp"
        "activation_transport_policy.cpp"
        "ble_activation_publisher.cpp"
        "motion_detector.cpp"
        "person_detector.cpp"
        "preview_server.cpp"
        "trigger_zone_config.cpp"
        "mqtt_activation_publisher.cpp"
        "wifi_provisioning.cpp"
    INCLUDE_DIRS "."
    # `esp_camera.h` is the public header, but the registry component itself
    # is named `esp32-camera`.
    REQUIRES esp32-camera esp-dl pedestrian_detect esp_psram esp_wifi esp_netif esp_event esp_http_server esp_hw_support esp_system esp_timer nvs_flash mqtt json bt
)
