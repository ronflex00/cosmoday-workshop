# Firmware ESP8266 — prototype matériel actuel

La télémétrie contient aussi `buzzer`, l'état réellement appliqué à la sortie.
Ce retour est envoyé toutes les 2 secondes. Le petit écran affiche « En alerte »
quand il reçoit buzzer=true ou une commande d'activation publiée par l'API.
Une commande publiée n'est pas un accusé de réception de l'ESP.

Le sketch `sentinel_x/sentinel_x.ino` adapte le code fonctionnel fourni par
l'utilisateur. Le HC-SR04 mesure la distance et ne déclenche plus d'alarme locale.
Les seuils gaz/température/humidité et les alarmes locales sont supprimés :
l'IA environnement du Pi décide des alertes, puis l'API commande les sorties.

| Élément | Broche / comportement |
| --- | --- |
| HC-SR04 | D5 trig, D6 echo, distance en cm ; null sans écho |
| PIR HW-416 | D3, HIGH = sortie active, distincte de la distance |
| MQ-2 | A0, moyenne 10 mesures ADC brutes, aucun seuil local |
| DHT11 | D4, intervalle 2 secondes |
| LED unique | D2, red = allumée, green = éteinte |
| Buzzer | D8, tone 2000 Hz |

Le matériel actuel utilise DHT11 + HC-SR04 + un capteur de présence numérique
sur D3. `motion` est ici une présence de proximité,
pas une détection humaine. Le MQ-2 transmet une valeur ADC brute, pas des ppm.
Le seuil de proximité historique à 80 cm reste uniquement pour la compatibilité
de `motion` et ne déclenche aucune alarme.

## Changements réseau

- BearSSL vérifie le certificat serveur avec la CA publique, port 8883.
- La synchronisation NTP est requise avant la connexion et la télémétrie.
- Compte MQTT `sentinel-esp`, reconnexion Wi-Fi/MQTT conservée.
- Last Will retained `online=false`, statut retained `online=true` à connexion.
- Commandes analysées avec ArduinoJson : exactement un booléen `buzzer` et
  `led` égal à `red` ou `green`. JSON incorrect ignoré sans changer les sorties.
- Réception des alertes informative ; seules les commandes pilotent les sorties.
  L'ESP ne publie plus d'alertes de dépassement de seuil.

Une commande distante d'activation reste active jusqu'à une commande d'arrêt
ou un redémarrage, y compris lors d'une coupure MQTT. La politique finale
d'expiration/arrêt devra être définie avec le contrôleur.
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
Distance, PIR, gaz, température et humidité sont relevés dans le même cycle
toutes les 2 secondes. Une seule ligne regroupe les mesures et les sorties,
puis un seul message de télémétrie est publié si le DHT et l'heure sont valides.
Les lectures sont successives, pas simultanées physiquement. Une variation entre deux relevés
peut donc ne pas être observée. MQTT et les timers des sorties restent servis
entre les cycles, sans attente bloquante de 2 secondes.
Les logs connexion/erreur restent visibles. Pour afficher aussi le JSON MQTT,
définir `MQTT_VERBOSE_TELEMETRY=1` dans `config.h` (0 par défaut).

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
- Vérifier que les anciennes limites n'activent plus les sorties ; tester les
  commandes distantes séparément de la détection IA.
- Couper/reprendre Wi-Fi et broker ; vérifier reconnexion et abonnements.

L'API lit la télémétrie, le statut device et les alertes MQTT et les diffuse
au dashboard par WebSocket. La distance et la présence sont deux mesures distinctes :
`motion` conserve le signal historique de proximité ultrason pour compatibilité,
`distance_sensor=true` indique que la distance est disponible, `distance_cm=null`
signifie sans écho. `presence=null` signifie que le capteur de présence n'est pas
configuré ; le dashboard affiche UNKNOWN, jamais une absence supposée.
Le capteur numérique actuel est sur D3, actif HIGH. Le sketch utilise D3 même
avec l'ancien `config.h`. Si `PRESENCE_SENSOR_PIN` y est déjà défini, vérifier
qu'il vaut D3 ; -1 désactive le capteur. `PRESENCE_SENSOR_ACTIVE_LEVEL` permet
d'adapter la polarité à LOW si le modèle le nécessite. La lecture `INPUT`
suppose une sortie numérique pilotée.
D3 correspond à GPIO0, qui doit rester HIGH au démarrage normal de l'ESP8266.
Si le capteur maintient sa sortie LOW au reset, l'ESP peut entrer en mode
programmation : préférer une broche libre sans fonction de boot si cela arrive.
Voir les [modes de démarrage du core ESP8266](https://arduino-esp8266.readthedocs.io/en/3.0.2/boards.html).
L'orchestration d'alarme environnementale ajoutée au backend utilise toujours
les commandes existantes `buzzer` booléen et `led` red/green.

## Tester les ajouts distance et présence

Ouvrir le sketch directement depuis le dépôt dans Arduino IDE, avec le `config.h`
existant dans le même dossier : ne pas le remplacer par les valeurs d'exemple.
Choisir NodeMCU 1.0 (ESP-12E Module), CPU 160 MHz et le port USB de l'ESP.
Cliquer Vérifier puis Téléverser ; ouvrir le moniteur série à 115200 bauds.
Après connexion MQTT, vérifier distance, présence et
`signal=HIGH/LOW` dans la ligne de relevé. Les champs JSON se vérifient côté
API ou en activant temporairement `MQTT_VERBOSE_TELEMETRY`.

Sur le Pi, les données réellement reçues par FastAPI se vérifient ainsi :

```bash
cd ~/cosmoday-workshop
curl --fail --show-error http://127.0.0.1:8080/api/v1/sensors/latest
```

Présenter un objet devant le HC-SR04, puis le retirer : vérifier une distance
numérique puis null si aucun écho revient. Le bloc Distance doit suivre ces
mesures ; il ne remplace pas le bloc Presence du nouveau capteur.
Déclencher puis laisser revenir au repos le capteur D3 : `presence` doit passer
de true à false, indépendamment de `motion`. Les deux dashboards suivent ce champ.
Le PIR HW-416 maintient sa sortie pendant une durée réglable de 8 à 200 secondes,
selon la [fiche fabricant](https://www.szhwmake.com/prod_view.aspx?FId=t3%3A77%3A3&Id=337&TypeId=77).
Cette mesure indique une sortie PIR active, pas une preuve de présence humaine
immobile. Pour tester son retour au repos, régler la temporisation au minimum
et rester hors de son champ. Ne pas inverser HIGH/LOW pour masquer un signal
constamment actif. Vérifier OUT vers D3 et une masse commune ; le fabricant
indique une alimentation 3,6–20 V et une sortie HIGH à 3,3 V.
Les données live sont diffusées à chaque réception ; seules les tendances
par minute sont enregistrées en mode TELEMETRY_STORAGE=trends.

### Mettre à jour API et dashboard sur le Pi

Le paquet `.runtime/sensors-dashboard-deploy.tar.gz` contient uniquement le code
API/frontend et les fichiers de build, sans configuration privée ni données.
Depuis Git Bash sur le PC :

```bash
scp .runtime/sensors-dashboard-deploy.tar.gz sentinelpi1@SentinelPi-1.local:~/cosmoday-workshop/
```

Puis dans la session SSH du Pi :

```bash
cd ~/cosmoday-workshop
tar -xzf sensors-dashboard-deploy.tar.gz
sudo docker compose up -d --build api frontend
sudo docker compose ps api frontend
curl --fail --show-error http://127.0.0.1:8080/api/v1/sensors/latest
```

Recharger le dashboard du navigateur après le build. L'écran PiTFT existant
lit déjà `presence` et n'a pas besoin d'être remplacé pour cette lecture.

Références : [BearSSL ESP8266](https://arduino-esp8266.readthedocs.io/en/latest/esp8266wifi/bearssl-client-secure-class.html),
[ArduinoJson](https://arduinojson.org/v7/api/json/deserializejson/).
