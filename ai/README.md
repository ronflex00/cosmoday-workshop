# Sentinel-X AI Service

## Fonctionnalités

- Détection de personnes avec YOLO nano (`yolov8n.pt`) sur CPU.
- Détection d'anomalies environnementales avec `sklearn.ensemble.IsolationForest`.
- Communication MQTT, reconnexion automatique et TLS configurable.
- Exécution dans un venv sur PC Linux ou Raspberry Pi 5, sans frontend ni Docker IA.

## Architecture

```text
Webcam USB → OpenCV → YOLO person → sentinel/ai/vision → Mosquitto
                  └→ annotated MJPEG stream → AI Vision dashboard

ESP8266 / simulateur → sentinel/telemetry → callback MQTT
                                              │ validation JSON
                                              ▼
                                          Queue (128)
                                              │ thread séparé
                                              ▼
                               Référence → IsolationForest
                                              │
                                              ▼
                                    sentinel/ai/anomaly → Mosquitto → FastAPI
```

`src/config.py` centralise les variables d'environnement. `common/` gère MQTT et
les schémas ; `vision/` gère la caméra et YOLO ; `anomaly/` gère le buffer et le
worker. `src/main.py` orchestre ces éléments.

Le callback réseau ne fait aucun apprentissage. Les deux modèles utilisent le
CPU ; YOLO est lancé avec `device="cpu"`, IsolationForest avec `n_jobs=1`.
La vision traite une frame sur N et capture par défaut en 640×480, avec une
inférence à 320 pixels. Aucun visage n'est identifié.

## Installation PC Linux

### Analyse environnement seule sur le Pi

Depuis `ai/`, installer `requirements-environment.txt` dans un venv, puis lancer
`python -m src.environment_main` après configuration MQTT/TLS dans `ai/.env`.
Ce point d'entrée réutilise le modèle et les contrats existants, sans import
OpenCV/YOLO ni accès caméra. Il analyse les mesures individuelles ; il n'ajoute
pas encore de caractéristiques de tendance temporelle. L'apprentissage est
recommencé au démarrage. Garder `AI_AUTO_ALARM=false` côté API durant la validation.

Python **3.10 minimum** ; le Python fourni par l'OS convient si les wheels des
dépendances sont disponibles. Le PC du workshop utilise Arch Linux et possède
déjà un venv fonctionnel : pour valider ce projet, réutiliser `.venv` sans
réinstallation.

Sur une nouvelle machine Debian/Ubuntu, les dépendances système peuvent être
installées avec les commandes suivantes. Le nom du paquet GLib varie selon
la version de Debian/Ubuntu ; le choix est automatique :

```bash
sudo apt update
if apt-cache show libglib2.0-0t64 >/dev/null 2>&1; then
    sentinel_glib_package=libglib2.0-0t64
else
    sentinel_glib_package=libglib2.0-0
fi
sudo apt install -y python3-venv python3-pip libgl1 "$sentinel_glib_package" v4l-utils mosquitto-clients
```

Sur une autre distribution Linux, installer les équivalents avec le gestionnaire
système. Ensuite, depuis la racine du dépôt :

```bash
cd ai
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.txt
cp -n ../.env.example .env
```

Installer PyTorch depuis son index CPU avant les autres dépendances évite de
sélectionner une distribution CUDA sur PC. Voir les
[instructions officielles PyTorch](https://pytorch.org/get-started/locally/).
`cp -n` conserve un `.env` local déjà existant. Adapter ses paramètres MQTT avant
le lancement ; les identifiants `CHANGE_ME` du modèle ne sont pas des identifiants
utilisables pour un broker anonyme.

Le paquet `opencv-python` permet le debug graphique et fonctionne aussi lorsque
le service n'affiche aucune fenêtre. Ne pas le mélanger avec
`opencv-python-headless`, qui fournit également `cv2`. Si les deux sont déjà
installés, corriger le venv avant d'utiliser la fenêtre :

```bash
python -m pip uninstall -y opencv-python opencv-python-headless
python -m pip install opencv-python
```

## Installation Raspberry Pi 5

Utiliser **Raspberry Pi OS 64 bits** (Bookworm ou Trixie), une webcam USB compatible
V4L2 et le Python de l'OS. Le même code source est utilisé sur PC et Pi ; seules
les variables de configuration changent. Vérifier le système :

```bash
uname -m
getconf LONG_BIT
python3 --version
```

Attendu : `aarch64` et `64`. Créer le venv sur le Pi : ne pas copier celui du PC.
Les installations pip se font dans le venv, conformément à la
[documentation Raspberry Pi OS](https://www.raspberrypi.com/documentation/computers/os.html#install-python-libraries-using-pip).
La procédure Ultralytics pour ARM est décrite dans son
[guide Raspberry Pi](https://docs.ultralytics.com/guides/raspberry-pi/).

Commandes à exécuter **sur le Pi** après transfert des sources :

```bash
sudo apt update
if apt-cache show libglib2.0-0t64 >/dev/null 2>&1; then
    sentinel_glib_package=libglib2.0-0t64
else
    sentinel_glib_package=libglib2.0-0
fi
sudo apt install -y python3-venv python3-pip libgl1 "$sentinel_glib_package" v4l-utils mosquitto-clients

# Depuis la racine du dépôt transféré sur le Pi :
cd ai
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.txt
cp -n ../.env.example .env
```

Les paquets principaux ont des wheels ARM64, et Ultralytics est un paquet Python
portable. La disponibilité d'une wheel dépend aussi de la version de Python et
de la libc. Si pip annonce `No matching distribution`, vérifier ces éléments
avec les instructions officielles ; ne pas copier une wheel x86_64 sur le Pi.
Aucun verrouillage de version ancien ni compilation CUDA n'est imposé.

Vérifications après installation :

```bash
python -m pip check
python -c 'import torch; print("PyTorch:", torch.__version__, "CUDA build:", torch.version.cuda)'
python scripts/check_environment.py
python -m unittest discover -s tests -v
```

Avec la distribution CPU, `CUDA build` doit être `None`. Le diagnostic importe
les bibliothèques et lit une frame puis libère la caméra. Il ne télécharge pas de
modèle, n'installe rien et ne contacte pas MQTT. Le lancer avec les autres
applications caméra fermées. `--skip-camera` permet de vérifier les imports
seuls, `--camera-index 1` de tester un autre index. Code de sortie : 0 si les
contrôles demandés passent, 1 en cas d'échec.

Cette procédure prépare l'intégration ARM64 ; les performances et le couple
webcam/Pi doivent encore être validés sur le matériel cible.

## Configuration

Le service lit `ai/.env`, ou le `.env` à la racine si `ai/.env` n'existe pas.
Les variables exportées dans le terminal priment sur le fichier. Les chemins de
modèle et certificats sont plus faciles à partager lorsqu'ils sont absolus ; un
chemin relatif est résolu depuis le répertoire de lancement (`ai/`).

| Variable | Défaut sans .env | Usage |
|---|---|---|
| `MQTT_HOST` | `localhost` | Broker local au Pi, ou nom fourni par l'équipe infra |
| `MQTT_PORT` | `1883`, ou `8883` avec TLS | Port réellement utilisé |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | vides | Authentification, si exigée par le broker |
| `MQTT_TLS` | `false` | Activer TLS et la vérification du serveur |
| `MQTT_TLS_CA` | vide | Autorité privée ; vide = autorités système |
| `MQTT_TLS_CERT` / `MQTT_TLS_KEY` | vides | Paire certificat/clé client pour TLS mutuel |
| `AI_CAMERA_INDEX` | `0` | Webcam USB `/dev/video0` sur Linux |
| `AI_CAMERA_WIDTH` / `AI_CAMERA_HEIGHT` | `640` / `480` | Résolution demandée à la caméra |
| `AI_YOLO_MODEL` | `yolov8n.pt` | Modèle local contenant la classe `person` |
| `AI_CONFIDENCE` | `0.55` | Confiance minimale YOLO, dans `(0, 1]` |
| `AI_PROCESS_EVERY_N_FRAMES` | `3` | Traiter une frame sur N, N ≥ 1 |
| `AI_INFERENCE_SIZE` | `320` | Taille d'entrée de l'inférence |
| `AI_SHOW_WINDOW` | `false` | Fenêtre debug, rectangles et confiance |
| `AI_VISION_STREAM_HOST` | `127.0.0.1` | Interface HTTP locale du flux webcam |
| `AI_VISION_STREAM_PORT` | `8765` | Port HTTP du flux MJPEG et des métriques vision |
| `AI_VISION_STREAM_ORIGIN` | `http://localhost:5173` | Origine frontend autorisée à lire les métriques |
| `AI_TRAINING_SAMPLES` | `20` | Nombre de mesures de référence, minimum 2 |
| `AI_CONTAMINATION` | `0.1` | Réglage du seuil IsolationForest, dans `(0, 0.5]` |
| `AI_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` ou `CRITICAL` |

Les noms historiques `CAMERA_INDEX`, `AI_MODEL` et `AI_FRAME_SKIP` restent acceptés
si leurs nouveaux équivalents ne sont pas définis. `MQTT_TLS_PORT` reste dans le
modèle partagé pour les autres composants ; ce service utilise **`MQTT_PORT`**.
Aucune adresse Raspberry ni aucun identifiant réel n'est présent dans le code.

Configuration d'intégration si le broker tourne sur le même Pi, en MQTT anonyme :

```dotenv
MQTT_HOST=localhost
MQTT_PORT=1883
MQTT_USERNAME=
MQTT_PASSWORD=
MQTT_TLS=false
AI_CAMERA_INDEX=0
AI_CAMERA_WIDTH=640
AI_CAMERA_HEIGHT=480
AI_YOLO_MODEL=yolov8n.pt
AI_CONFIDENCE=0.55
AI_PROCESS_EVERY_N_FRAMES=3
AI_INFERENCE_SIZE=320
AI_SHOW_WINDOW=false
AI_VISION_STREAM_HOST=127.0.0.1
AI_VISION_STREAM_PORT=8765
AI_VISION_STREAM_ORIGIN=http://localhost:5173
AI_TRAINING_SAMPLES=20
AI_CONTAMINATION=0.1
AI_LOG_LEVEL=INFO
```

Si le broker est distant ou authentifié, remplacer l'hôte et les identifiants par
ceux fournis par l'équipe infra. Le port **18883 est réservé aux tests locaux**.

## Lancement

Depuis `ai/`, après configuration de `.env` :

```bash
source .venv/bin/activate
python scripts/check_environment.py
python -m src.main
```

Au premier lancement, Ultralytics peut télécharger `yolov8n.pt`. Prévoir Internet
à cette étape ou transférer les poids déjà téléchargés. Garder un modèle local
avant la démonstration hors ligne ; les poids sont ignorés par Git.

Attendre `Connected`, `Subscribed to sentinel/telemetry`, `YOLO model loaded` et
`Camera opened`. `Ctrl+C` ou `SIGTERM` demande l'arrêt : la caméra est libérée, le
worker termine son traitement courant, puis la boucle réseau MQTT s'arrête.
Une erreur de caméra arrête le service avec un code non nul ; elle ne publie pas
une fausse absence de personne. Une panne MQTT déclenche des tentatives de
reconnexion avec un délai croissant de 1 à 30 secondes.

Après l'ouverture de la caméra, le service sert les images annotées sur
`http://localhost:8765/stream.mjpg` et les métriques sur
`http://localhost:8765/metrics`. Ouvrir le frontend sur `/vision`. Pour un
frontend provenant d'une autre machine, configurer `AI_VISION_STREAM_HOST` sur
l'interface réseau de l'IA, `AI_VISION_STREAM_ORIGIN` sur l'origine exacte du
frontend et `VITE_VISION_STREAM_URL` dans `frontend/.env` vers l'URL du flux.
Le serveur du flux n'a pas d'authentification : ne pas l'exposer à un réseau non
fiable.

## Topics MQTT

| Topic | Direction | Payload |
|---|---|---|
| `sentinel/telemetry` | Entrée | `device_id`, `ts`, `temperature`, `humidity`, `gas`, `motion` |
| `sentinel/ai/vision` | Sortie | `ts`, `person_detected`, `confidence`, `source` |
| `sentinel/ai/anomaly` | Sortie | `ts`, `anomaly`, `ready`, `score`, `model`, `features` |

Les topics correspondent exactement à `../docs/contracts.md`. Le résultat
anomalie reprend ses champs et ajoute `ready`, demandé et validé à l'étape 3.
Pendant l'apprentissage, `score` est `null` : le consommateur FastAPI doit
accepter un score optionnel et utiliser le score seulement si `ready=true`.
Le contrat partagé reste inchangé ; confirmer cette extension avec l'équipe API.

Tous les résultats utilisent des timestamps ISO-8601 UTC, des booléens JSON,
des nombres Python convertis depuis les résultats des modèles et aucun NaN.
Les télémétries mal formées, incomplètes, hors des types attendus ou non finies
sont ignorées avec un log. `motion` est validé, mais n'entre pas dans le modèle.

Exemples de sortie :

```json
{"ts":"2026-10-05T14:30:05Z","person_detected":true,"confidence":0.94,"source":"camera-0"}
```

```json
{"ts":"2026-10-05T14:30:06Z","anomaly":false,"ready":false,"score":null,"model":"isolation_forest","features":{"temperature":24.3,"humidity":46.0,"gas":173.0}}
```

```json
{"ts":"2026-10-05T14:30:07Z","anomaly":true,"ready":true,"score":-0.065,"model":"isolation_forest","features":{"temperature":36.0,"humidity":72.0,"gas":550.0}}
```

Les publications sont QoS 0, sans retain. La vision publie un changement de
présence dès l'inférence suivante, et un heartbeat environ chaque seconde si
l'état reste identique ; aucune publication systématique à chaque frame. Des
changements rapides de présence peuvent dépasser un message par seconde.
Les anomalies sont publiées une fois par télémétrie traitée. Après reconnexion,
l'abonnement est renouvelé et le modèle est conservé. Une file pleine ou une
publication impossible produit un log ; les pertes ne sont pas rejouées.

## Test vision

Sur le broker d'intégration, dans un autre terminal :

```bash
mosquitto_sub -h localhost -p 1883 -t 'sentinel/ai/vision' -v
```

Adapter hôte, authentification et TLS à la configuration du service. En session
graphique, lancer depuis `ai/` :

```bash
AI_SHOW_WINDOW=true python -m src.main
```

Passer devant la caméra, puis sortir du champ : vérifier `true` avec une confiance
cohérente, puis `false` avec `confidence=0.0`. Appuyer sur Q, Échap ou Ctrl+C pour
arrêter. Pour un diagnostic de capture seul :

```bash
python scripts/check_environment.py --camera-index 0
```

Les bibliothèques sont importées par le diagnostic, mais aucun modèle YOLO n'est
chargé et aucune inférence n'est lancée.

## Test Isolation Forest

Les premières `AI_TRAINING_SAMPLES` mesures valides constituent la référence et
publient toutes `ready=false`, `anomaly=false`, `score=null`. Après la dernière,
le log affiche `IsolationForest ready`. Les nouvelles mesures sont ensuite
classées avec `IsolationForest.predict` et scorées avec `decision_function`.
Un score négatif indique une anomalie selon la
[documentation scikit-learn](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.IsolationForest.html).

La référence reste fixe jusqu'au redémarrage. Commencer avec des mesures normales
variées : une référence constante ou déjà anormale limite la qualité de détection.
`AI_CONTAMINATION=0.1` ne garantit pas que chaque mesure normale sera acceptée.
Le prototype utilise une référence commune ; intégrer un seul appareil à la
fois pour éviter de mélanger des capteurs différents.

Les tests sans webcam, broker ou installation supplémentaire :

```bash
python -m unittest discover -s tests -v
python -m pip check
```

Ils couvrent validation et JSON, entraînement réel, scores, buffer, file réseau,
réabonnement, TLS et erreurs de fermeture. Le test TLS vérifie la configuration
et la validation des certificats ; une connexion au broker MQTTS cible reste à
valider avec les certificats fournis par l'équipe infra.

## Fake telemetry

Le simulateur génère seulement des mesures. Aucune décision d'anomalie n'est
prise dans le script : elles proviennent toutes d'IsolationForest dans le service.
Les modes `normal`, `anomaly` et `demo` utilisent la même configuration MQTT.

Démo locale avec quatre terminaux ; elle ne change pas le broker de production.
Depuis la racine du dépôt pour les commandes `cd ai` :

**Terminal 1 — Mosquitto local de test :**

```bash
mosquitto -p 18883 -v
```

**Terminal 2 — service :**

```bash
cd ai
source .venv/bin/activate
export MQTT_HOST=localhost MQTT_PORT=18883 MQTT_USERNAME='' MQTT_PASSWORD='' MQTT_TLS=false
AI_TRAINING_SAMPLES=20 AI_CONTAMINATION=0.1 AI_SHOW_WINDOW=false python -m src.main
```

**Terminal 3 — résultats :**

```bash
mosquitto_sub -h localhost -p 18883 -t 'sentinel/ai/#' -v
```

**Terminal 4 — simulateur, après le log de souscription du terminal 2 :**

```bash
cd ai
source .venv/bin/activate
export MQTT_HOST=localhost MQTT_PORT=18883 MQTT_USERNAME='' MQTT_PASSWORD='' MQTT_TLS=false
AI_TRAINING_SAMPLES=20 python scripts/send_fake_telemetry.py --mode demo
```

La démo envoie 20 mesures normales, attend 2 secondes, puis 5 mesures extrêmes.
Résultat attendu : 20 messages d'apprentissage puis 5 anomalies prêtes. Le nombre
de mesures de référence suit `AI_TRAINING_SAMPLES`, sauf `--normal-count` explicite.
Redémarrer le service avant une nouvelle démo pour réinitialiser la référence.

Autres modes, depuis le terminal 4 :

```bash
python scripts/send_fake_telemetry.py --mode normal --count 20
python scripts/send_fake_telemetry.py --mode anomaly --count 5
```

Plages normales : température 22–25, humidité 40–50, gaz 100–180. Plages extrêmes :
température 36–40, humidité 65–80, gaz 450–650. `--interval` règle le délai (0.5 s
par défaut), `--seed` la génération reproductible, `--device-id` l'identifiant.
Ne pas mélanger la télémétrie réelle et simulée pendant l'apprentissage de démo.

## Lancement headless

Sur le Pi, depuis `ai/`, après configuration pour le broker infra :

```bash
source .venv/bin/activate
AI_CAMERA_INDEX=0 AI_SHOW_WINDOW=false python -m src.main
```

Aucune session graphique ni fenêtre n'est utilisée. `opencv-python` conserve ses
dépendances système même en headless : les paquets GL/GLib de l'installation
restent nécessaires. Pour mesurer sans changer la cadence ni les publications :

```bash
AI_LOG_LEVEL=DEBUG AI_SHOW_WINDOW=false python -m src.main
```

Un log DEBUG apparaît toutes les 30 inférences : temps moyen YOLO en ms et débit
d'inférence théorique. Ce débit n'est pas le FPS caméra ou celui de toute la
boucle ; il exclut capture, annotation et publication. Les logs INFO restent
limités aux changements de présence, connexions et résultats des capteurs.

## Passage MQTT → MQTTS

L'équipe infra fournit le listener 8883 et les certificats. Aucun certificat
n'est créé par l'IA. Configurer `ai/.env` avec les valeurs fournies :

```dotenv
MQTT_HOST=nom-du-broker-correspondant-au-certificat
MQTT_PORT=8883
MQTT_TLS=true
MQTT_TLS_CA=/chemin/absolu/fourni-par-infra/ca.crt
# Seulement si le broker exige TLS mutuel :
# MQTT_TLS_CERT=/chemin/absolu/fourni-par-infra/client.crt
# MQTT_TLS_KEY=/chemin/absolu/fourni-par-infra/client.key
```

Conserver les identifiants MQTT si le broker les exige. La CA peut être omise
pour un certificat reconnu par les autorités système. Certificat et clé client
sont configurés ensemble pour TLS mutuel. `MQTT_TLS=true` appelle réellement
`Paho.Client.tls_set` ; la vérification du serveur et de son nom reste activée.
Ne pas utiliser de désactivation de validation TLS. L'hôte doit correspondre au
certificat, même si le broker tourne localement.

Supprimer les anciens overrides exportés avant de lire la configuration TLS :

```bash
unset MQTT_HOST MQTT_PORT MQTT_USERNAME MQTT_PASSWORD MQTT_TLS MQTT_TLS_CA MQTT_TLS_CERT MQTT_TLS_KEY
python -m src.main
```

Pour contrôler les résultats avec les valeurs et la CA fournies (ajouter les
options d'authentification si nécessaires) :

```bash
mosquitto_sub -h NOM_DU_BROKER -p 8883 --cafile /chemin/fourni/ca.crt -t 'sentinel/ai/#' -v
```

En TLS mutuel, ajouter aussi `--cert /chemin/fourni/client.crt` et
`--key /chemin/fourni/client.key`. Valider la connexion au listener réel avant
la démonstration finale.

## Dépannage

| Symptôme | Vérification / correction |
|---|---|
| Caméra introuvable | Fermer les autres applications caméra, vérifier USB et `AI_CAMERA_INDEX`, lancer le diagnostic |
| `/dev/video0` absent | `ls /dev/video*` puis `v4l2-ctl --list-devices` ; vérifier que la webcam USB est reconnue, essayer l'index indiqué |
| Permissions caméra | `ls -l /dev/video0` et `id -nG` ; si nécessaire `sudo usermod -aG video "$USER"`, puis rouvrir la session |
| Aucune frame / coupure USB | Vérifier câble et alimentation ; le service s'arrête avec un log, puis peut être relancé |
| MQTT inaccessible | Vérifier hôte, port, listener, identifiants et réseau ; consulter les logs de reconnexion |
| Toujours `ready=false` | Attendre N télémétries valides et consulter les logs de rejet ; vérifier le topic exact |
| YOLO impossible à charger | Transférer les poids ou autoriser le téléchargement initial ; contrôler `AI_YOLO_MODEL` et la classe `person` |
| Fenêtre OpenCV impossible | `AI_SHOW_WINDOW=false` via SSH ; pour le debug, utiliser une session graphique et `opencv-python` |
| `libGL.so.1` / GLib manquant | Installer les bibliothèques système GL/GLib indiquées pour l'OS |
| Erreur de certificat TLS | Vérifier CA, nom du serveur, dates et chemins fournis par l'équipe infra |
| Installation ARM64 impossible | Vérifier OS 64 bits, Python, pip et wheels ARM64 ; ne pas utiliser le venv ou les wheels x86 du PC |
| CPU trop lent | Garder le nano et `AI_INFERENCE_SIZE=320`, augmenter N à 3 ou 4, désactiver l'affichage, consulter les logs DEBUG |

Avant intégration, valider sur le Pi la capture USB, les performances CPU, la
référence de capteurs réels, le traitement de `ready`/`score=null` côté API et la
connexion au broker infra, puis MQTTS. Aucun accès au Pi n'est nécessaire pour les
tests unitaires, mais ces derniers ne remplacent pas la validation matérielle.
