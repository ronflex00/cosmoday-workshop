# Anomaly detection

- `buffer.py` : référence bornée aux premières mesures valides, trois features.
- `detector.py` : apprentissage réel d'IsolationForest puis analyse des nouvelles mesures.
- `service.py` : traitement dans un worker, en dehors du thread réseau MQTT.
- Les premières `AI_TRAINING_SAMPLES` mesures (20 par défaut) publient `ready=false`.
- La référence reste fixe après apprentissage ; redémarrer pour réinitialiser.
- Voir `../../README.md` pour la démonstration et les formats MQTT.
