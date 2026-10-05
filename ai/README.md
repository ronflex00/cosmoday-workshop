# AI service

Responsabilités :

1. Ouvrir la webcam USB directement sur le Raspberry Pi.
2. Détecter la classe `person` (YOLOv8n recommandé ; fallback OpenCV possible).
3. Publier le dernier état dans `sentinel/ai/vision`.
4. S'abonner à `sentinel/telemetry`.
5. Calculer une anomalie avec `IsolationForest`.
6. Publier le résultat dans `sentinel/ai/anomaly`.

Pour le sprint, lancer cette brique directement sur l'hôte Raspberry Pi dans un virtualenv plutôt qu'en conteneur afin d'éviter les problèmes d'accès à `/dev/video0`.
