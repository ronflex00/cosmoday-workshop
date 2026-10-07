# Firmware ESP8266 — prototype matériel actuel

Le sketch `sentinel_x/sentinel_x.ino` adapte le code fonctionnel fourni par
l'utilisateur. Les lectures, seuils et sorties locales sont conservés.

| Élément | Broche / comportement |
| --- | --- |
| HC-SR04 | D5 trig, D6 echo, présence de proximité < 80 cm |
| MQ-2 | A0, moyenne 10 mesures, référence de démarrage 50 mesures |
| DHT11 | D4, intervalle 2 secondes |
| LED unique | D2, red = allumée, green = éteinte |
| Buzzer | D8, tone 2000 Hz |

Le matériel actuel est DHT11 + HC-SR04 : il ne satisfait pas encore les
exigences DHT22 + PIR + OLED. `motion` est ici une présence de proximité,
pas une détection humaine. La calibration MQ-2 est une référence ADC relative,
pas une mesure ppm ou une calibration industrielle. Les règles de seuil ne
sont pas le modèle prédictif demandé au projet.

## Changements réseau

- BearSSL vérifie le certificat serveur avec la CA publique, port 8883.
- La synchronisation NTP est requise avant la connexion et la télémétrie.
- Compte MQTT `sentinel-esp`, reconnexion Wi-Fi/MQTT conservée.
- Last Will retained `online=false`, statut retained `online=true` à connexion.
- Commandes analysées avec ArduinoJson : exactement un booléen `buzzer` et
  `led` égal à `red` ou `green`. JSON incorrect ignoré sans changer les sorties.
- Publication des alertes locales selon `docs/contracts.md` ; réception des
  alertes informative. Seules les commandes pilotent les sorties distantes,
  afin de ne pas redéclencher une alarme avec ses propres messages.

Les protections locales restent prioritaires : une commande d'arrêt distante
ne coupe pas un timer d'alerte locale en cours (buzzer 1 s, LED 5 s).
Une commande distante d'activation reste active jusqu'à une commande d'arrêt
ou un redémarrage, y compris lors d'une coupure MQTT. La politique finale
d'expiration/arrêt devra être définie avec le contrôleur.
Les alertes émises hors connexion ne sont pas stockées ni rejouées.
Les lectures MQ-2 et `pulseIn` restent bloquantes, et une négociation TLS peut
prendre plusieurs secondes : les durées des sorties ne sont pas garanties
avec une précision stricte pendant ces opérations.

## Préparer Arduino IDE sur le PC

1. Ouvrir `sentinel_x/sentinel_x.ino`, carte **NodeMCU 1.0 (ESP-12E Module)**.
2. Bibliothèques : PubSubClient 2.8, DHT sensor library 1.4.7,
   Adafruit Unified Sensor 1.1.15, ArduinoJson 7.4.2 ; core ESP8266 3.1.2.
   BearSSL et les fonctions NTP sont inclus dans le core.
3. Copier `config.example.h` vers `config.h` dans le même dossier. Renseigner
   Wi-Fi et le mot de passe `sentinel-esp` localement. `config.h` est ignoré.
4. Copier uniquement `infra/mosquitto/certs/ca.crt` depuis le Pi vers le PC,
   puis coller son PEM complet dans `MQTT_CA_CERT`. Jamais une clé privée.
5. Garder `MQTT_SERVER=SentinelPi-1.local` si résolu par l'ESP. Le support mDNS
   a fonctionné pendant les essais matériels du 7 octobre 2026 sur ce réseau.
   En cas d'échec DNS, corriger la résolution/SAN,
   sans désactiver TLS. Ne pas remplacer au hasard le nom par une IP.

Le nom Wi-Fi, mot de passe et la CA ne sont pas fournis dans l'exemple.
Le sketch ne peut pas se connecter avec les valeurs d'exemple.
Choisir 160 MHz pour les essais TLS, suivant la documentation BearSSL.
Le moniteur série est à 115200 bauds. Aucun upload automatique n'est effectué.

## Validation et essais matériels

Compilation de vérification réussie le 7 octobre 2026 avec Arduino CLI,
core ESP8266 3.1.2, cible `esp8266:esp8266:nodemcuv2` et les versions ci-dessus.
La compilation utilise une copie de `config.example.h`, sans vrais secrets ni
CA réelle : elle valide les types et le build, pas TLS sur le matériel.
RAM statique : 31 652 octets (39 %) ; flash : 390 328 octets (37 %).
IRAM rapportée : 94 %, dont 32 768 octets réservés au cache instruction.
La mémoire disponible pendant une connexion TLS doit encore être mesurée.
ArduinoJson 7.4.2 a été ajouté aux bibliothèques Arduino locales pour ce build.

Le 7 octobre 2026, l'utilisateur a téléversé le firmware configuré, confirmé
la connexion MQTTS, et fourni trois mesures reçues sur le Pi. L'activation
et l'arrêt physiques de la LED et du buzzer par le compte contrôleur sont
également confirmés. Voir [le compte rendu](../../docs/mqtt-validation.md).

Essais restant à effectuer :

- Vérifier la première publication statut et Last Will après débranchement.
- Envoyer un JSON incorrect (booléen en chaîne, champ supplémentaire, LED
  inconnue) et vérifier que les sorties ne changent pas.
- Déclencher une alerte locale et observer `sentinel/alerts` ; confirmer
  qu'une alerte reçue n'est pas republiée en boucle.
- Couper/reprendre Wi-Fi et broker ; vérifier reconnexion et abonnements.

L'API actuelle ne lit pas encore le statut device ni les alertes MQTT.
Le contrôleur automatique n'est pas implémenté.

Références : [BearSSL ESP8266](https://arduino-esp8266.readthedocs.io/en/latest/esp8266wifi/bearssl-client-secure-class.html),
[ArduinoJson](https://arduinojson.org/v7/api/json/deserializejson/).
