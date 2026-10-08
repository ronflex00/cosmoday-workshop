#include <ESP8266WiFi.h>
#include <WiFiClientSecureBearSSL.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <coredecls.h>
#include "config.h"
#include <DHT.h>
#include <time.h>

// Digital presence sensor wired to D3. The private config.h may override it.
// Set the pin to -1 to publish presence=null when no sensor is connected.
#ifndef PRESENCE_SENSOR_PIN
#define PRESENCE_SENSOR_PIN D3
#endif
#ifndef PRESENCE_SENSOR_ACTIVE_LEVEL
#define PRESENCE_SENSOR_ACTIVE_LEVEL HIGH
#endif
#ifndef MQTT_VERBOSE_TELEMETRY
#define MQTT_VERBOSE_TELEMETRY 0
#endif

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
// ULTRASONIC PROXIMITY (legacy motion field)
// ========================================================

const float PROXIMITY_DISTANCE_CM = 80.0;

bool proximityDetected = false;
bool presenceSensorDetected = false;

float distanceCm = -1.0;


// ========================================================
// BUZZER
// ========================================================

const int BUZZER_FREQUENCY = 2000;

bool remoteBuzzerActive = false;

bool buzzerOutputActive = false;


// ========================================================
// LED
// ========================================================

bool remoteLedActive = false;


// ========================================================
// MQ-2
// ========================================================

const int MQ2_AVERAGE_SAMPLES = 10;
int gasValue = 0;


// ========================================================
// DHT11 / ENVIRONNEMENT
// ========================================================

float temperature = 0.0;
float humidity = 0.0;
bool dhtValid = false;


// ========================================================
// MQTT TELEMETRY
// ========================================================

unsigned long lastSensorRead = 0;
const unsigned long SENSOR_INTERVAL = 2000;

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
    remoteLedActive;

  digitalWrite(
    LED_PIN,
    ledShouldBeOn ? HIGH : LOW
  );


  // ------------------------------------------------------
  // BUZZER
  // ------------------------------------------------------

  bool buzzerShouldBeOn =
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


// Outputs are controlled only by commands from the API/controller.
void updateOutputs() {
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

  // No echo is a normal absence of distance measurement, encoded as null.
  char distanceJson[24];
  if (distanceCm >= 0.0) {
    snprintf(distanceJson, sizeof(distanceJson), "%.1f", distanceCm);
  } else {
    snprintf(distanceJson, sizeof(distanceJson), "null");
  }


  int payloadLength = snprintf(
    payload,
    sizeof(payload),

    "{\"device_id\":\"%s\","
    "\"ts\":\"%s\","
    "\"temperature\":%.1f,"
    "\"humidity\":%.1f,"
    "\"gas\":%.1f,"
    "\"motion\":%s,"
    "\"distance_sensor\":true,"
    "\"distance_cm\":%s,"
    "\"presence\":%s,"
    "\"buzzer\":%s}",

    DEVICE_ID,

    timestamp.c_str(),

    temperature,

    humidity,

    (float)gasValue,

    proximityDetected
      ? "true"
      : "false",
    distanceJson,
    PRESENCE_SENSOR_PIN < 0 ? "null" : presenceSensorDetected ? "true" : "false",
    buzzerOutputActive ? "true" : "false"
  );

  if (payloadLength < 0 || static_cast<size_t>(payloadLength) >= sizeof(payload)) {
    Serial.println("MQTT: telemetry trop longue, publication refusee");
    return;
  }


  bool success =
    mqttClient.publish(
      TOPIC_TELEMETRY,
      payload
    );


#if MQTT_VERBOSE_TELEMETRY
  Serial.print("MQTT -> ");
  Serial.println(TOPIC_TELEMETRY);
  Serial.println(payload);
#endif


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

  if (PRESENCE_SENSOR_PIN >= 0) pinMode(PRESENCE_SENSOR_PIN, INPUT);


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


  // Raw MQ-2 values are interpreted by the environmental AI on the Pi.


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


  // Measurements only: environmental AI decides alerts on the Pi.
  // A single acquisition/report/publication cycle for every sensor.
  // MQTT and output timers continue to run between measurements.
  if (millis() - lastSensorRead < SENSOR_INTERVAL) {
    delay(5);
    return;
  }
  lastSensorRead = millis();

  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  unsigned long duration = pulseIn(ECHO_PIN, HIGH, 30000);
  distanceCm = duration == 0 ? -1.0 : duration * 0.0343 / 2.0;
  proximityDetected = distanceCm >= 0 && distanceCm < PROXIMITY_DISTANCE_CM;

  int presenceRaw = -1;
  if (PRESENCE_SENSOR_PIN >= 0) {
    presenceRaw = digitalRead(PRESENCE_SENSOR_PIN);
    presenceSensorDetected = presenceRaw == PRESENCE_SENSOR_ACTIVE_LEVEL;
  }

  gasValue = readMQ2();
  float newHumidity = dht.readHumidity();
  float newTemperature = dht.readTemperature();
  dhtValid = !isnan(newHumidity) && !isnan(newTemperature);
  if (dhtValid) {
    humidity = newHumidity;
    temperature = newTemperature;

  }

  updateOutputs();
  Serial.print("DISTANCE : ");
  if (distanceCm < 0) Serial.print("AUCUN ECHO");
  else { Serial.print(distanceCm, 1); Serial.print(" cm"); }
  Serial.print(" | PRESENCE : ");
  if (presenceRaw < 0) Serial.print("NON CONFIGUREE");
  else {
    Serial.print(presenceSensorDetected ? "OUI" : "NON");
    Serial.print(" (signal=");
    Serial.print(presenceRaw == HIGH ? "HIGH" : "LOW");
    Serial.print(")");
  }
  Serial.print(" | GAZ : ");
  Serial.print(gasValue);
  Serial.print("/1023");
  if (dhtValid) {
    Serial.print(" | TEMP : "); Serial.print(temperature, 1); Serial.print(" C");
    Serial.print(" | HUM : "); Serial.print(humidity, 1); Serial.print(" %");
  } else Serial.print(" | DHT11 : ERREUR");
  Serial.print(" | LED : "); Serial.print(remoteLedActive ? "ON" : "OFF");
  Serial.print(" | BUZZER : "); Serial.println(remoteBuzzerActive ? "ON" : "OFF");

  publishTelemetry();
}
