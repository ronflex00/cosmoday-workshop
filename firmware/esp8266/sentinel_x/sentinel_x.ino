#include <ESP8266WiFi.h>
#include <WiFiClientSecureBearSSL.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <coredecls.h>
#include "config.h"
#include <DHT.h>
#include <time.h>

// ========================================================
// SENTINEL-X
// ESP8266 + HC-SR04 + MQ-2 + DHT11
// + LED + BUZZER + WIFI + MQTTS
// ========================================================


// ========================================================
// WIFI
// ========================================================

// Network settings and public CA are in the private config.h.

// Topics du contrat SENTINEL-X
const char* TOPIC_TELEMETRY = "sentinel/telemetry";
const char* TOPIC_COMMANDS = "sentinel/commands";
const char* TOPIC_STATUS = "sentinel/status/device";
const char* TOPIC_ALERTS = "sentinel/alerts";


// ========================================================
// PINS
// ========================================================

// HC-SR04
#define TRIG_PIN D5
#define ECHO_PIN D6

// MQ-2
#define MQ2_PIN A0

// DHT11
#define DHT_PIN D4
#define DHT_TYPE DHT11

// LED
#define LED_PIN D2

// Buzzer
#define BUZZER_PIN D8


// ========================================================
// DHT11
// ========================================================

DHT dht(DHT_PIN, DHT_TYPE);


// ========================================================
// WIFI / MQTT CLIENTS
// ========================================================

BearSSL::X509List mqttTrustAnchor(MQTT_CA_CERT);
BearSSL::WiFiClientSecure wifiClient;
bool clockSynchronized = false;
bool ntpStarted = false;

PubSubClient mqttClient(wifiClient);


// ========================================================
// PRESENCE
// ========================================================

const float PRESENCE_DISTANCE_CM = 80.0;

bool presenceDetected = false;
bool wasPresent = false;

float distanceCm = -1.0;


// ========================================================
// BUZZER
// ========================================================

const int BUZZER_FREQUENCY = 2000;

// Alerte locale = 1 seconde
const unsigned long BUZZER_DURATION = 1000;

bool localBuzzerActive = false;
bool remoteBuzzerActive = false;

unsigned long buzzerStartTime = 0;

bool buzzerOutputActive = false;


// ========================================================
// LED
// ========================================================

// Alerte locale = 5 secondes
const unsigned long LED_DURATION = 5000;

bool localLedActive = false;
bool remoteLedActive = false;

unsigned long ledStartTime = 0;


// ========================================================
// MQ-2
// ========================================================

const int MQ2_CALIBRATION_SAMPLES = 50;
const int MQ2_AVERAGE_SAMPLES = 10;

const int MQ2_WARNING_MARGIN = 40;
const int MQ2_DANGER_MARGIN = 100;

// 0 = NORMAL
// 1 = ATTENTION
// 2 = ANOMALIE
int currentGasState = 0;
int previousGasState = 0;

int gasValue = 0;

int gasBaseline = 0;
int gasWarningThreshold = 0;
int gasDangerThreshold = 0;


// ========================================================
// DHT11 / ENVIRONNEMENT
// ========================================================

const float TEMP_MIN = 15.0;
const float TEMP_MAX = 30.0;

const float HUMIDITY_MIN = 30.0;
const float HUMIDITY_MAX = 70.0;

float temperature = 0.0;
float humidity = 0.0;

bool dhtValid = false;

bool environmentAnomaly = false;
bool previousEnvironmentAnomaly = false;

unsigned long lastDHTRead = 0;

const unsigned long DHT_INTERVAL = 2000;


// ========================================================
// MQTT TELEMETRY
// ========================================================

unsigned long lastTelemetryPublish = 0;

const unsigned long TELEMETRY_INTERVAL = 2000;

unsigned long lastMqttReconnect = 0;
unsigned long lastWiFiReconnect = 0;


// ========================================================
// GESTION DES SORTIES
// ========================================================

void applyOutputs() {

  // ------------------------------------------------------
  // LED
  // ------------------------------------------------------

  bool ledShouldBeOn =
    localLedActive ||
    remoteLedActive;

  digitalWrite(
    LED_PIN,
    ledShouldBeOn ? HIGH : LOW
  );


  // ------------------------------------------------------
  // BUZZER
  // ------------------------------------------------------

  bool buzzerShouldBeOn =
    localBuzzerActive ||
    remoteBuzzerActive;


  if (
    buzzerShouldBeOn &&
    !buzzerOutputActive
  ) {

    tone(
      BUZZER_PIN,
      BUZZER_FREQUENCY
    );

    buzzerOutputActive = true;
  }


  if (
    !buzzerShouldBeOn &&
    buzzerOutputActive
  ) {

    noTone(BUZZER_PIN);

    buzzerOutputActive = false;
  }
}


// ========================================================
// ALERTE LOCALE
// LED = 5 secondes
// BUZZER = 1 seconde
// ========================================================

void publishLocalAlert(const char* type, const char* message) {
  if (!mqttClient.connected() || !clockSynchronized) return;
  JsonDocument doc;
  doc["ts"] = getTimestamp();
  doc["type"] = type;
  doc["severity"] = "warning";
  doc["message"] = message;
  char buffer[384];
  if (measureJson(doc) >= sizeof(buffer)) return;
  size_t size = serializeJson(doc, buffer, sizeof(buffer));
  if (!mqttClient.publish(TOPIC_ALERTS, reinterpret_cast<const uint8_t*>(buffer), size, false)) {
    Serial.println("Publication alerte locale impossible");
  }
}

void triggerLocalAlert(const char* type, const char* message) {
  // Local protections keep working even when Wi-Fi/MQTT is unavailable.
  publishLocalAlert(type, message);

  localLedActive = true;

  ledStartTime = millis();


  localBuzzerActive = true;

  buzzerStartTime = millis();


  applyOutputs();
}


// ========================================================
// LED UNIQUEMENT
// ========================================================

void triggerLedOnly() {

  localLedActive = true;

  ledStartTime = millis();

  applyOutputs();
}


// ========================================================
// MISE A JOUR DES TIMERS
// ========================================================

void updateOutputs() {

  // Buzzer après 1 seconde
  if (
    localBuzzerActive &&
    millis() - buzzerStartTime >= BUZZER_DURATION
  ) {

    localBuzzerActive = false;
  }


  // LED après 5 secondes
  if (
    localLedActive &&
    millis() - ledStartTime >= LED_DURATION
  ) {

    localLedActive = false;
  }


  applyOutputs();
}


// ========================================================
// MQ-2
// ========================================================

int readMQ2() {

  long total = 0;


  for (
    int i = 0;
    i < MQ2_AVERAGE_SAMPLES;
    i++
  ) {

    total += analogRead(MQ2_PIN);

    delay(5);
  }


  return
    total / MQ2_AVERAGE_SAMPLES;
}


// ========================================================
// CALIBRATION MQ-2
// ========================================================

void calibrateMQ2() {

  Serial.println();
  Serial.println(
    "========================================"
  );

  Serial.println(
    "CALIBRATION MQ-2"
  );

  Serial.println(
    "Laissez le capteur dans un air normal"
  );

  Serial.println(
    "========================================"
  );


  long total = 0;


  for (
    int i = 0;
    i < MQ2_CALIBRATION_SAMPLES;
    i++
  ) {

    int value =
      analogRead(MQ2_PIN);


    total += value;


    Serial.print("Calibration ");

    Serial.print(i + 1);

    Serial.print("/");

    Serial.print(
      MQ2_CALIBRATION_SAMPLES
    );

    Serial.print(" : ");

    Serial.println(value);


    delay(100);
  }


  gasBaseline =
    total /
    MQ2_CALIBRATION_SAMPLES;


  gasWarningThreshold =
    gasBaseline +
    MQ2_WARNING_MARGIN;


  gasDangerThreshold =
    gasBaseline +
    MQ2_DANGER_MARGIN;


  Serial.println();
  Serial.println(
    "========================================"
  );

  Serial.println(
    "MQ-2 CALIBRE"
  );


  Serial.print(
    "Baseline : "
  );

  Serial.println(
    gasBaseline
  );


  Serial.print(
    "Seuil ATTENTION : "
  );

  Serial.println(
    gasWarningThreshold
  );


  Serial.print(
    "Seuil ANOMALIE : "
  );

  Serial.println(
    gasDangerThreshold
  );

  Serial.println(
    "========================================"
  );
}


// ========================================================
// WIFI
// ========================================================

void connectWiFi() {

  Serial.println();
  Serial.print(
    "Connexion WiFi : "
  );

  Serial.println(
    WIFI_SSID
  );


  WiFi.mode(WIFI_STA);

  WiFi.begin(
    WIFI_SSID,
    WIFI_PASSWORD
  );


  unsigned long start =
    millis();


  while (
    WiFi.status() != WL_CONNECTED &&
    millis() - start < 20000
  ) {

    delay(500);

    Serial.print(".");
  }


  Serial.println();


  if (
    WiFi.status() ==
    WL_CONNECTED
  ) {

    Serial.println(
      "WiFi CONNECTE"
    );


    Serial.print(
      "IP ESP8266 : "
    );

    Serial.println(
      WiFi.localIP()
    );


    Serial.print(
      "RSSI : "
    );

    Serial.print(
      WiFi.RSSI()
    );

    Serial.println(
      " dBm"
    );

  } else {

    Serial.println(
      "ECHEC WIFI"
    );

    Serial.println(
      "Le système continue en mode local."
    );
  }
}


// ========================================================
// TIMESTAMP UTC
// ========================================================

String getTimestamp() {

  time_t now =
    time(nullptr);


  // Pas encore synchronisé
  if (now < 1700000000) {

    return
      "1970-01-01T00:00:00Z";
  }


  struct tm timeinfo;


  gmtime_r(
    &now,
    &timeinfo
  );


  char buffer[25];


  strftime(
    buffer,
    sizeof(buffer),
    "%Y-%m-%dT%H:%M:%SZ",
    &timeinfo
  );


  return String(buffer);
}


// ========================================================
// STATUS DEVICE MQTT
// ========================================================

void publishDeviceStatus() {

  if (
    !mqttClient.connected()
  ) {

    return;
  }


  String ip =
    WiFi.localIP().toString();


  char payload[220];


  snprintf(
    payload,
    sizeof(payload),

    "{\"device_id\":\"%s\","
    "\"online\":true,"
    "\"ip\":\"%s\","
    "\"rssi\":%d}",

    DEVICE_ID,
    ip.c_str(),
    WiFi.RSSI()
  );


  mqttClient.publish(
    TOPIC_STATUS,
    payload,
    true
  );


  Serial.print(
    "MQTT STATUS -> "
  );

  Serial.println(payload);
}


// ========================================================
// COMMANDES RECUES DE L'API / CONTROLEUR DU PI
// ========================================================

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  if (length == 0 || length > 384) {
    Serial.println("MQTT: taille JSON refusee");
    return;
  }
  JsonDocument doc;
  DeserializationError error = deserializeJson(
    doc, static_cast<const byte*>(payload), length,
    DeserializationOption::NestingLimit(4));
  if (error || !doc.is<JsonObject>()) {
    Serial.println("MQTT: JSON invalide refuse");
    return;
  }
  if (strcmp(topic, TOPIC_ALERTS) == 0) {
    if (!doc["ts"].is<const char*>() || !doc["type"].is<const char*>() ||
        !doc["severity"].is<const char*>() || !doc["message"].is<const char*>()) {
      Serial.println("MQTT: alerte invalide refusee");
      return;
    }
    // Events are informative: only commands change remote outputs.
    // Never republish received alerts (the ESP receives its own local alerts).
    Serial.println("MQTT: evenement alerte recu");
    return;
  }
  if (strcmp(topic, TOPIC_COMMANDS) != 0) return;
  if (doc.size() != 2 || !doc["buzzer"].is<bool>() ||
      !doc["led"].is<const char*>()) {
    Serial.println("MQTT: commande invalide refusee");
    return;
  }
  const char* led = doc["led"].as<const char*>();
  if (strcmp(led, "red") != 0 && strcmp(led, "green") != 0) {
    Serial.println("MQTT: valeur LED refusee");
    return;
  }
  remoteBuzzerActive = doc["buzzer"].as<bool>();
  // Existing single LED: red = ON, green = OFF, not a two-colour LED.
  remoteLedActive = strcmp(led, "red") == 0;
  applyOutputs();
  Serial.println("MQTT: commande valide appliquee");
}


// ========================================================
// CONNEXION MQTT
// ========================================================

void connectMQTT() {

  if (
    WiFi.status() != WL_CONNECTED
  ) {

    return;
  }


  if (
    mqttClient.connected()
  ) {

    return;
  }


  Serial.print(
    "Connexion MQTT "
  );

  Serial.print(
    MQTT_SERVER
  );

  Serial.print(":");

  Serial.println(
    MQTT_PORT
  );


  if (!clockSynchronized) {
    Serial.println("MQTTS: attente synchronisation NTP");
    return;
  }

  String clientId =
    "sentinel-esp8266-";

  clientId +=
    String(
      ESP.getChipId(),
      HEX
    );


  JsonDocument willDoc;
  willDoc["device_id"] = DEVICE_ID;
  willDoc["online"] = false;
  char willPayload[128];
  if (measureJson(willDoc) >= sizeof(willPayload)) return;
  serializeJson(willDoc, willPayload, sizeof(willPayload));
  if (
    mqttClient.connect(
      clientId.c_str(), MQTT_USERNAME, MQTT_PASSWORD,
      TOPIC_STATUS, 1, true,
      willPayload
    )
  ) {

    Serial.println(
      "MQTT CONNECTE"
    );


    if (!mqttClient.subscribe(TOPIC_COMMANDS) || !mqttClient.subscribe(TOPIC_ALERTS)) {
      Serial.println("MQTT: echec demande abonnement");
      mqttClient.disconnect();
      return;
    }


    Serial.print(
      "Abonne a : "
    );

    Serial.println(
      TOPIC_COMMANDS
    );


    publishDeviceStatus();

  } else {

    Serial.print(
      "MQTT ECHEC, code = "
    );

    Serial.println(mqttClient.state());
    char tlsError[160];
    if (wifiClient.getLastSSLError(tlsError, sizeof(tlsError)) != 0) {
      Serial.print("TLS: ");
      Serial.println(tlsError);
    }
  }
}


// ========================================================
// TELEMETRIE MQTT
// ========================================================

void publishTelemetry() {

  if (
    !mqttClient.connected()
  ) {

    return;
  }


  // Le backend exige température
  // et humidité valides
  if (!dhtValid || !clockSynchronized) {

    Serial.println(
      "MQTT : telemetry non envoyee, DHT11 invalide ou heure non synchronisee"
    );

    return;
  }


  String timestamp =
    getTimestamp();


  char payload[320];


  snprintf(
    payload,
    sizeof(payload),

    "{\"device_id\":\"%s\","
    "\"ts\":\"%s\","
    "\"temperature\":%.1f,"
    "\"humidity\":%.1f,"
    "\"gas\":%.1f,"
    "\"motion\":%s}",

    DEVICE_ID,

    timestamp.c_str(),

    temperature,

    humidity,

    (float)gasValue,

    presenceDetected
      ? "true"
      : "false"
  );


  bool success =
    mqttClient.publish(
      TOPIC_TELEMETRY,
      payload
    );


  Serial.println();

  Serial.print(
    "MQTT -> "
  );

  Serial.println(
    TOPIC_TELEMETRY
  );


  Serial.println(
    payload
  );


  if (!success) {

    Serial.println(
      "ERREUR PUBLICATION MQTT"
    );
  }
}


// ========================================================
// SETUP
// ========================================================

void setup() {

  Serial.begin(115200);

  delay(1000);


  // ------------------------------------------------------
  // HC-SR04
  // ------------------------------------------------------

  pinMode(
    TRIG_PIN,
    OUTPUT
  );

  pinMode(
    ECHO_PIN,
    INPUT
  );

  digitalWrite(
    TRIG_PIN,
    LOW
  );


  // ------------------------------------------------------
  // LED
  // ------------------------------------------------------

  pinMode(
    LED_PIN,
    OUTPUT
  );

  digitalWrite(
    LED_PIN,
    LOW
  );


  // ------------------------------------------------------
  // BUZZER
  // ------------------------------------------------------

  pinMode(
    BUZZER_PIN,
    OUTPUT
  );

  noTone(
    BUZZER_PIN
  );


  // ------------------------------------------------------
  // DHT11
  // ------------------------------------------------------

  dht.begin();


  Serial.println();
  Serial.println(
    "========================================"
  );

  Serial.println(
    "              SENTINEL-X"
  );

  Serial.println(
    "========================================"
  );

  Serial.println(
    "HC-SR04 : D5 / D6"
  );

  Serial.println(
    "MQ-2    : A0"
  );

  Serial.println(
    "DHT11   : D4"
  );

  Serial.println(
    "LED     : D2"
  );

  Serial.println(
    "BUZZER  : D8"
  );

  Serial.println(
    "========================================"
  );


  // MQ-2
  calibrateMQ2();


  // Première lecture DHT
  temperature =
    dht.readTemperature();

  humidity =
    dht.readHumidity();


  dhtValid =
    !isnan(temperature) &&
    !isnan(humidity);


  // ------------------------------------------------------
  // WIFI
  // ------------------------------------------------------

  // Lifetime of the global trust anchor matches the TLS client.
  wifiClient.setTrustAnchors(&mqttTrustAnchor);
  mqttClient.setSocketTimeout(3);
  settimeofday_cb([]() { clockSynchronized = true; });
  connectWiFi();


  // ------------------------------------------------------
  // HEURE UTC / NTP
  // ------------------------------------------------------

  if (
    WiFi.status() ==
    WL_CONNECTED
  ) {

    ntpStarted = true;
    configTime(
      0,
      0,
      "pool.ntp.org",
      "time.nist.gov"
    );
  }


  // ------------------------------------------------------
  // MQTT
  // ------------------------------------------------------

  mqttClient.setServer(
    MQTT_SERVER,
    MQTT_PORT
  );


  mqttClient.setCallback(
    mqttCallback
  );


  mqttClient.setBufferSize(
    512
  );


  connectMQTT();
}


// ========================================================
// LOOP
// ========================================================

void loop() {

  updateOutputs();


  // ======================================================
  // WIFI RECONNECT
  // ======================================================

  if (
    WiFi.status() != WL_CONNECTED
  ) {

    if (
      millis() -
      lastWiFiReconnect >= 10000
    ) {

      lastWiFiReconnect =
        millis();


      Serial.println(
        "WiFi perdu -> reconnexion"
      );


      WiFi.begin(
        WIFI_SSID,
        WIFI_PASSWORD
      );
    }

  } else {
    if (!ntpStarted) {
      configTime(0, 0, "pool.ntp.org", "time.nist.gov");
      ntpStarted = true;
    }

    // ====================================================
    // MQTT RECONNECT
    // ====================================================

    if (
      !mqttClient.connected() &&
      millis() - lastMqttReconnect >= 5000
    ) {

      lastMqttReconnect =
        millis();

      connectMQTT();
    }
  }


  // Important pour recevoir les commandes
  if (
    mqttClient.connected()
  ) {

    mqttClient.loop();
  }


  // ======================================================
  // 1. HC-SR04
  // ======================================================

  digitalWrite(
    TRIG_PIN,
    LOW
  );

  delayMicroseconds(2);


  digitalWrite(
    TRIG_PIN,
    HIGH
  );

  delayMicroseconds(10);


  digitalWrite(
    TRIG_PIN,
    LOW
  );


  long duration =
    pulseIn(
      ECHO_PIN,
      HIGH,
      30000
    );


  if (duration == 0) {

    distanceCm = -1;

    presenceDetected =
      false;

    wasPresent =
      false;


    Serial.print(
      "Distance : aucun echo"
    );

  } else {

    distanceCm =
      duration *
      0.0343 /
      2.0;


    presenceDetected =
      distanceCm <
      PRESENCE_DISTANCE_CM;


    Serial.print(
      "Distance : "
    );

    Serial.print(
      distanceCm,
      1
    );

    Serial.print(
      " cm | "
    );


    if (
      presenceDetected
    ) {

      Serial.print(
        "PRESENCE"
      );


      if (!wasPresent) {

        Serial.print(
          " -> ALERTE"
        );


        // LED 5 s + buzzer 1 s
        triggerLocalAlert("intrusion", "ESP: presence de proximite HC-SR04");
      }


      wasPresent =
        true;

    } else {

      Serial.print(
        "CLEAR"
      );


      wasPresent =
        false;
    }
  }


  // ======================================================
  // 2. MQ-2
  // ======================================================

  gasValue =
    readMQ2();


  Serial.print(
    " || GAZ : "
  );

  Serial.print(
    gasValue
  );

  Serial.print(
    "/1023 | "
  );


  if (
    gasValue <
    gasWarningThreshold
  ) {

    currentGasState = 0;

    Serial.print(
      "NORMAL"
    );

  } else if (
    gasValue <
    gasDangerThreshold
  ) {

    currentGasState = 1;

    Serial.print(
      "ATTENTION"
    );

  } else {

    currentGasState = 2;

    Serial.print(
      "ANOMALIE"
    );
  }


  // Attention gaz -> LED 5 secondes
  if (
    currentGasState == 1 &&
    previousGasState == 0
  ) {

    triggerLedOnly();
  }


  // Anomalie gaz -> LED 5 s + buzzer 1 s
  if (
    currentGasState == 2 &&
    previousGasState != 2
  ) {

    Serial.print(
      " -> ALERTE GAZ"
    );

    triggerLocalAlert("system", "ESP: seuil gaz critique MQ-2");
  }


  previousGasState =
    currentGasState;


  // ======================================================
  // 3. DHT11
  // ======================================================

  if (
    millis() -
    lastDHTRead >=
    DHT_INTERVAL
  ) {

    lastDHTRead =
      millis();


    float newHumidity =
      dht.readHumidity();


    float newTemperature =
      dht.readTemperature();


    if (
      isnan(newHumidity) ||
      isnan(newTemperature)
    ) {

      dhtValid =
        false;


      Serial.print(
        " || DHT11 : ERREUR"
      );

    } else {

      dhtValid =
        true;


      humidity =
        newHumidity;


      temperature =
        newTemperature;


      Serial.print(
        " || TEMP : "
      );

      Serial.print(
        temperature,
        1
      );

      Serial.print(
        " C"
      );


      Serial.print(
        " | HUM : "
      );

      Serial.print(
        humidity,
        1
      );

      Serial.print(
        " %"
      );


      environmentAnomaly =

        temperature < TEMP_MIN ||

        temperature > TEMP_MAX ||

        humidity < HUMIDITY_MIN ||

        humidity > HUMIDITY_MAX;


      if (
        environmentAnomaly &&
        !previousEnvironmentAnomaly
      ) {

        Serial.print(
          " -> ALERTE ENVIRONNEMENT"
        );


        // LED 5 s + buzzer 1 s
        triggerLocalAlert("system", "ESP: seuil environnemental depasse");
      }


      previousEnvironmentAnomaly =
        environmentAnomaly;
    }
  }


  // ======================================================
  // MQTT TELEMETRY TOUTES LES 2 SECONDES
  // ======================================================

  if (
    millis() -
    lastTelemetryPublish >=
    TELEMETRY_INTERVAL
  ) {

    lastTelemetryPublish =
      millis();


    publishTelemetry();
  }


  // ======================================================
  // SORTIES
  // ======================================================

  updateOutputs();


  Serial.print(
    " || LED : "
  );

  Serial.print(
    (localLedActive || remoteLedActive)
      ? "ON"
      : "OFF"
  );


  Serial.print(
    " | BUZZER : "
  );

  Serial.print(
    (localBuzzerActive || remoteBuzzerActive)
      ? "ON"
      : "OFF"
  );


  Serial.println();


  // Keep MQTT/output timers serviced during the existing sensor cadence.
  const unsigned long idleStart = millis();
  while (millis() - idleStart < 200) {
    if (mqttClient.connected()) mqttClient.loop();
    updateOutputs();
    delay(5);
  }
}
