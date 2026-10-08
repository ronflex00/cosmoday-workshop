// Standalone HW-416 test: no Wi-Fi, MQTT or other sensor reads.
// Match this pin to the actual OUT wire: D3 currently, or D1 if moved.
const int PIR_PIN = D3;
unsigned long lastReport = 0;

void setup() {
  Serial.begin(115200);
  pinMode(PIR_PIN, INPUT);
  Serial.println();
  Serial.println("TEST PIR HW-416 : attendre la stabilisation du capteur.");
}

void loop() {
  if (millis() - lastReport >= 1000) {
    lastReport = millis();
    const bool active = digitalRead(PIR_PIN) == HIGH;
    Serial.print("PIR : ");
    Serial.print(active ? "OUI" : "NON");
    Serial.println(active ? " (signal=HIGH)" : " (signal=LOW)");
  }
  delay(5);
}
