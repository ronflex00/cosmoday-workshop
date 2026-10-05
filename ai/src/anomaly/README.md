# Anomaly detection

- Buffer circulaire des dernières mesures.
- `IsolationForest` sur température, humidité et gaz.
- Ne déclencher qu'après un minimum de points pour éviter des faux positifs au démarrage.
