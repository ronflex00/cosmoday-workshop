# Infrastructure / Cyber

Raspberry Pi 5 :
- Raspberry Pi OS 64-bit ;
- Docker / Docker Compose ;
- Mosquitto ;
- PostgreSQL ;
- MQTTS/TLS ;
- UFW ;
- SSH par clé ;
- journalisation et vérifications de ports.

Ne jamais versionner les clés privées dans `infra/mosquitto/certs`.

Voir [`docs/mqtt-tls.md`](../docs/mqtt-tls.md) pour préparer le broker Docker
sécurisé. Créer les certificats et comptes sur le Pi avant de démarrer `mqtt`.
