#pragma once

// Copy to config.h (ignored by Git). Never commit real credentials.
static const char* WIFI_SSID = "CHANGE_ME";
static const char* WIFI_PASSWORD = "CHANGE_ME";
// DNS name must resolve on the ESP and match the server certificate SAN.
static const char* MQTT_SERVER = "SentinelPi-1.local";
static const uint16_t MQTT_PORT = 8883;
static const char* MQTT_USERNAME = "sentinel-esp";
static const char* MQTT_PASSWORD = "CHANGE_ME";
static const char* DEVICE_ID = "sentinel-01";

// Current digital presence sensor is connected to D3.
// -1 disables it and publishes presence=null. Never reuse a sensor/output pin.
#define PRESENCE_SENSOR_PIN D3
#define PRESENCE_SENSOR_ACTIVE_LEVEL HIGH
// 0: one compact sensor log per acquisition; 1: also print MQTT JSON payloads.
#define MQTT_VERBOSE_TELEMETRY 0

// Paste ONLY the public ca.crt from the Pi, never ca.key or server.key.
static const char MQTT_CA_CERT[] PROGMEM = R"PEM(
-----BEGIN CERTIFICATE-----
PASTE_PUBLIC_CA_CERTIFICATE_HERE
-----END CERTIFICATE-----
)PEM";
