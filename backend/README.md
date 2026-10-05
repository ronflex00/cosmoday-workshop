# Backend

FastAPI + client MQTT + PostgreSQL.

Responsabilités :
- recevoir / s'abonner à la télémétrie et aux événements IA ;
- stocker l'historique ;
- exposer REST + WebSocket ;
- publier les commandes LED/buzzer.

Le contrat d'API commun est dans `docs/contracts.md`.
