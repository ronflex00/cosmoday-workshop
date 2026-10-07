# Tests MQTTS — 7 octobre 2026

Résultats observés dans les sorties fournies depuis le Raspberry Pi et le PC.
Aucun secret ni hachage de mot de passe n'est inclus dans ce compte rendu.

## Environnement

- Raspberry Pi OS basé sur Debian 13 Trixie, `aarch64`, 4 Go RAM.
- Pi : `SentinelPi-1`, Wi-Fi DHCP `172.20.10.3`, heure NTP synchronisée.
- PC : `172.20.10.2`. Réseau Wi-Fi actuel : `172.20.10.0/28`.
- ESP réel : `sentinel-01`, Wi-Fi `172.20.10.4`, firmware BearSSL adapté.
- Docker 29.8.2, Compose 5.6.0, Mosquitto 2.1.2 (`eclipse-mosquitto:2`).
- Digest téléchargé : `sha256:38c0da4f2ef84284d47b3b3eeea1cb3bdeabe81ee10caf0cd5c5ff61ee3ea408`.
- CA : `Sentinel-X MQTT CA`, expiration 6 octobre 2031.
- Certificat serveur RSA 2048 : expiration 7 octobre 2027.
- SAN : `SentinelPi-1.local`, `sentinelpi-1.local`, `mqtt`, `localhost`,
  IP `172.20.10.3`. L'IP est DHCP : une modification exige un autre SAN
  ou un nom réseau résolu par le client.

## Résultats

| Contrôle | Résultat observé |
| --- | --- |
| Docker `hello-world` sur Pi | Exécution réussie |
| Certificat signé et hostname correct | `openssl verify`: OK |
| Lecture des fichiers par UID/GID 1883 | `Permissions OK` |
| Démarrage Mosquitto | Listener IPv4 `8883`, broker running |
| TLS depuis Pi vers loopback | TLS 1.3, hostname vérifié, code 0 |
| Nom serveur incorrect | Échec TLS : hostname mismatch, code 62 |
| Connexion anonyme | CONNACK 5, not authorised |
| Mauvais mot de passe ESP | CONNACK 5, not authorised |
| ESP → API, télémétrie | PUBACK 0 et JSON reçu |
| API → ESP, commande | PUBACK 0 et JSON reçu |
| IA → contrôleur, vision | PUBACK 0 et JSON reçu |
| Contrôleur → ESP, commande | PUBACK 0 et JSON reçu |
| ESP publie une commande | Refus Not authorized |
| IA publie une commande | Connexion acceptée, PUBACK 135, publication refusée |
| Port publié Docker | `8883` en IPv4 et IPv6, aucun `1883` publié |
| Sockets conteneur | `8883` et DNS Docker ; aucun listener `1883` |
| PC → Pi TCP 8883 | Test-NetConnection : True |
| PC → Pi TCP 1883 | Test-NetConnection : False (Pi joignable) |
| Redémarrage broker | Sauvegarde et rechargement de la base, écoute 8883 |
| Nouvel échange ESP → API après redémarrage | Authentification et réception réussies |

Les rôles du tableau ci-dessus ont été simulés avec `mosquitto_pub/sub` dans
des conteneurs temporaires. Les essais matériels suivants complètent ces
tests, sans valider encore FastAPI ou le contrôleur automatique.
Les comptes de test sont fournis par des fichiers privés `0600` hors Git.
Le `1883/tcp` sans flèche affiché par Compose est une métadonnée de l'image,
pas une publication de port. La tentative client sur 1883 affichait
`Bad file descriptor` ; l'absence d'écoute a été confirmée par les sockets
et le contrôle externe, plutôt que par ce message ambigu.

Les warnings de permissions ACL ont disparu après propriétaire `1883:1883`
et mode `0600`. L'information de migration `message_size_limit` vers
`max_packet_size` reste présente ; les deux limites n'ont pas la même portée.

## Validation du firmware réel

Après téléversement par l'utilisateur, le moniteur série confirme la connexion
à `SentinelPi-1.local:8883` et le statut `online=true`, IP `172.20.10.4`,
RSSI -51 dBm. Une première tentative avait échoué avec MQTT code 5 ; les
tentatives suivantes ont réussi, sans désactivation de TLS.

Trois télémétries du vrai ESP ont été reçues sur le Pi avec le compte API :
timestamps UTC `2026-10-07T12:22:10Z`, `12:22:13Z` et `12:22:15Z`,
températures 27,6–27,8 °C, humidité 60 %, gaz ADC 13–19, `motion=false`.

L'utilisateur confirme l'activation physique LED/buzzer après publication
du compte contrôleur de `{"buzzer":true,"led":"red"}`, puis leur arrêt
avec `{"buzzer":false,"led":"green"}`. La LED est unique : `green`
signifie éteinte. Le compte contrôleur est utilisé par un client CLI de test,
pas encore par un service automatique.

## Contrôles restant à réaliser

- TLS/MQTT depuis le PC (le test PC réalisé était uniquement TCP ; l'ESP
  réel a depuis validé le flux réseau MQTTS).
- Refus d'une CA étrangère et mesure de la version TLS négociée par l'ESP.
- Alertes locales ESP → contrôleur/API et anomalies IA.
- Reconnexion d'un client maintenu ouvert pendant la coupure broker.
- Persistance d'un message retained/session réellement créé avant redémarrage
  (la base rechargée pendant le test était vide).
- Filtrage et accès IPv6, règles Docker/hôte, charge et limites de connexions.
- Service de décision, arrêt/priorité des alarmes, authentification dashboard.

Ce bilan valide les cas testés, pas une sécurité complète ni un pentest.
