# Contrats d'intégration SENTINEL-X

Ce fichier doit être modifié uniquement après accord de l'équipe. Il évite que chaque brique utilise des noms de topics ou des formats JSON différents.

## MQTT

### 1. Télémétrie ESP -> serveur

Topic : `sentinel/telemetry`

```json
{
  "device_id": "sentinel-01",
  "ts": "2026-10-05T14:30:00Z",
  "temperature": 24.3,
  "humidity": 46.0,
  "gas": 173,
  "motion": false
}
```

### 2. État du device ESP

Topic : `sentinel/status/device`

```json
{
  "device_id": "sentinel-01",
  "online": true,
  "ip": "192.168.10.10",
  "rssi": -52
}
```

### 3. Résultat IA vision

Topic : `sentinel/ai/vision`

```json
{
  "ts": "2026-10-05T14:30:05Z",
  "person_detected": true,
  "confidence": 0.91,
  "source": "camera-0"
}
```

### 4. Résultat IA anomalie capteurs

Topic : `sentinel/ai/anomaly`

```json
{
  "ts": "2026-10-05T14:30:06Z",
  "anomaly": true,
  "score": -0.18,
  "model": "isolation_forest",
  "features": {
    "temperature": 29.1,
    "humidity": 44.0,
    "gas": 260
  }
}
```

### 5. Alertes consolidées

Topic : `sentinel/alerts`

```json
{
  "ts": "2026-10-05T14:30:07Z",
  "type": "intrusion",
  "severity": "critical",
  "message": "Présence humaine détectée"
}
```

### 6. Commandes API -> ESP

Topic : `sentinel/commands`

```json
{
  "buzzer": true,
  "led": "red"
}
```

## API minimale

- `GET /health` -> statut API.
- `GET /api/v1/status` -> état global Sentinel-X.
- `GET /api/v1/sensors/latest` -> dernière télémétrie.
- `GET /api/v1/alerts` -> alertes récentes.
- `POST /api/v1/alerts` -> réception / création d'alerte.
- `POST /api/v1/commands` -> publier une commande LED/buzzer vers MQTT.
- `GET /api/v1/ai/status` -> dernier état vision + anomalie.
- `WS /ws` -> pousser les mises à jour au dashboard.

## Règles d'intégration

- Les timestamps sont en ISO-8601 UTC.
- Ne jamais renommer un topic sans modifier ce fichier et prévenir les autres.
- Les messages JSON doivent rester petits et lisibles.
- L'IA publie ses résultats sur MQTT ; elle ne parle pas directement au frontend.
- Le navigateur communique uniquement avec l'API (REST/WebSocket), jamais directement avec MQTT.
