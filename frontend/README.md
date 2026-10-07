# Frontend Sentinel-X

Pour héberger le dashboard avec Docker sur le Raspberry Pi, suivre le
[guide frontend Pi](../docs/frontend-pi.md). Le serveur Nginx relaie REST et
WebSocket vers FastAPI ; le navigateur utilise une seule adresse via SSH.

Dashboard React + Vite + TypeScript, avec Tailwind CSS, Recharts et Lucide React.
Les mesures, résultats IA et alertes suivent la chaîne
MQTT → FastAPI → REST/WebSocket → React.
Les contrats sont dans [`../docs/contracts.md`](../docs/contracts.md).

## Installation et lancement

Prérequis : Node.js 20.19+ dans la série 20, ou 22.12+,
conformément aux [prérequis Vite](https://vite.dev/guide/).

Depuis la racine du dépôt :

```bash
cd frontend
npm ci
cp -n .env.example .env
npm run dev
```

Ouvrir **http://localhost:5173**. Le serveur refuse de changer automatiquement de
port si `5173` est occupé, afin de conserver l'origine autorisée par le backend.
Le dashboard séparé de vision est disponible sur **http://localhost:5173/vision**.

## Configuration

```dotenv
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000/ws
VITE_DATA_STALE_SECONDS=30
VITE_VISION_STREAM_URL=http://localhost:8765/stream.mjpg
```

Ces URL sont utilisées par le navigateur. Pour accéder à une API sur une autre
machine, modifier les deux variables dans `frontend/.env`, puis relancer Vite.
Le backend doit autoriser l'origine du frontend dans `CORS_ORIGINS`, y compris
son port, pour REST et WebSocket. En local, son défaut est `http://localhost:5173`.
Le flux MJPEG et ses métriques sont servis par le processus Python caméra, pas par
MQTT. Par défaut, le frontend cible `localhost:8765`; pour une caméra sur une autre
machine, définir `VITE_VISION_STREAM_URL` dans `frontend/.env` avec l'URL accessible
depuis le navigateur et `AI_VISION_STREAM_ORIGIN` dans la configuration IA avec
l'origine du frontend. Le flux vidéo n'est pas authentifié : le garder sur un réseau
de confiance.

Si `VITE_WS_URL` n'est pas définie, elle est dérivée de `VITE_API_URL` avec
`ws://` ou `wss://` et le chemin `/ws`. Les variables Vite sont intégrées au build ;
les changer pour une version de production nécessite de reconstruire le frontend.

`VITE_DATA_STALE_SECONDS` définit la fraîcheur des données à partir de leur
timestamp source. Par défaut, une mesure de plus de 30 secondes devient périmée.
Une valeur invalide ou inférieure à cinq secondes revient au défaut de 30 secondes.
Un timestamp situé trop loin dans le futur est aussi considéré comme périmé.
Les horloges du PC et des appareils doivent être synchronisées.

## Zones du dashboard

- **System status** : connexion WebSocket au backend, MQTT, activité des deux IA
  et heure de la dernière mise à jour backend.
- **Environment** : température en °C, humidité en %, gaz en valeur brute et
  mouvement YES/NO. Les données absentes affichent `—`, ou UNKNOWN pour le mouvement.
- **AI Vision** (`/vision`) : flux USB annoté par YOLO, détection, confiance,
  FPS d'inférence, latence mesurée, modèle et changements d'état détectés pendant
  la session. Aucun chiffre n'est simulé ; les métriques absentes affichent `—`.
- **AI Environment** (`/environment`) : score brut et classification Isolation
  Forest, historique borné des scores réellement reçus, alertes d'anomalie et
  séries temporelles de température, humidité et gaz. Les flèches résument la
  direction des six derniers points ; elles ne constituent pas des seuils ou une
  décision IA. Le modèle actuel classe chaque échantillon capteur indépendamment,
  et ne prédit pas des incidents futurs.
- **AI Environment** : CALIBRATING lorsque `ready=false`, NORMAL lorsque
  `ready=true/anomaly=false`, ANOMALY lorsque `ready=true/anomaly=true`. Le score
  reste `—` pendant la calibration, puis s'affiche avec trois décimales.
  CALIBRATING est orange, NORMAL vert et ANOMALY rouge. La sévérité backend
  environnementale demeure `warning`, affichée en orange dans le statut global
  et l'historique d'alertes.
- **Environmental trends** : trois courbes Recharts avec leurs unités propres,
  un maximum de 120 mesures réelles et des infobulles. Aucun point n'est inventé
  lorsque l'historique est vide.
- **Alert activity** : les 50 dernières alertes, les plus récentes en premier,
  avec heure, type, message et sévérité. Les transitions et la déduplication sont
  gérées par le backend.
- **Node controls** : activation et arrêt du buzzer/LED via l'API REST.

Le statut global donne priorité à CRITICAL pour une présence humaine actuelle,
puis WARNING pour une anomalie environnementale actuelle, puis CALIBRATING.
SAFE exige des données capteurs et IA actuelles, une calibration terminée et
aucune détection IA. Sinon il affiche WAITING ou OFFLINE. La décision d'anomalie
vient exclusivement du résultat IsolationForest reçu ; React ne la recalcule pas
à partir de seuils capteurs ou du score affiché.

Les heures s'affichent dans le fuseau du navigateur. La barre système indique
la dernière mise à jour backend ; les panneaux indiquent leur timestamp source
et le pied de page indique la dernière réception dans le navigateur.

## Commandes d'alarme

**ACTIVATE ALARM** envoie `POST /api/v1/commands` :

```json
{"buzzer": true, "led": "red"}
```

**STOP ALARM** envoie :

```json
{"buzzer": false, "led": "green"}
```

Le backend publie le payload sur `sentinel/commands`, sans retain. Les deux
boutons sont désactivés pendant une requête et lorsque le backend ou MQTT est
hors ligne. La réponse est validée avant d'afficher la confirmation d'envoi.
Une erreur ou un délai de cinq secondes affiche une publication non confirmée ;
le frontend ne réessaie pas automatiquement la commande.

La confirmation indique que le backend a publié la commande. Le contrat actuel
ne fournit pas encore d'accusé de réception ou d'état du buzzer depuis l'ESP8266.

## Flux et reconnexion

`useSentinelSocket` commence par `GET /api/v1/state`, puis ouvre `/ws`.
Le backend envoie un snapshot initial et ensuite les états complets :

```json
{"type": "state", "data": {"telemetry": null, "vision": null, "anomaly": null, "system": {"mqtt_connected": false, "last_update": null}, "history": [], "alerts": []}}
```

Le hook expose `state`, `connected`, `error` et `receivedAt`. Les champs de la
réponse REST et des messages WebSocket sont vérifiés avant de remplacer l'état.
Un JSON incorrect ou une structure invalide est ignoré avec un avertissement.
Les dernières données valides restent affichées.

Si le backend est arrêté ou inaccessible au chargement, le frontend réessaie
automatiquement après 1, 2, 4, 8 puis 10 secondes maximum entre les tentatives.
Chaque tentative recharge l'état REST avant de rouvrir le WebSocket. Les requêtes
et l'ouverture WebSocket ont un délai de cinq secondes. Les timers, requêtes et
connexions sont nettoyés au démontage du composant, y compris avec React StrictMode.

La perte du WebSocket conserve les dernières mesures visibles et signale la
reconnexion. MQTT affiche alors UNKNOWN. Si seul le broker est arrêté, le backend
reste ONLINE et MQTT affiche OFFLINE. Les résultats IA anciens sont marqués
STALE, les dernières lectures sont atténuées et les contrôles sont désactivés
si le transport est interrompu. Aucun accès MQTT ou webcam n'est effectué depuis
le navigateur.

## Structure

`App.tsx` compose les panneaux à partir de l'état validé par `useSentinelSocket`.
`services/api.ts` centralise REST et la validation des confirmations de commande.
`types/sentinel.ts` décrit les contrats et leurs vérifications à l'exécution.
`utils/` gère le formatage et la fraîcheur, avec `useNow` pour réévaluer les
timestamps même sans nouveau message.

Les composants sont `Header`, `SystemStatus`, `SensorCard`, `VisionPanel`,
`AnomalyPanel`, `SensorChart`, `AlertsPanel`, `CommandPanel` et `StatusBadge`.
Les graphiques sont chargés séparément pour limiter le bundle initial.
Tailwind CSS 4 utilise le plugin Vite et `@import "tailwindcss"` dans
`src/styles.css` ; aucun fichier `tailwind.config` n'est nécessaire pour cette
configuration. Le dashboard s'adapte aux écrans ordinateur et mobile.
Les vues 1920×1080 et 1440×900 contiennent toutes les zones sans défilement.
La vue 1366×768 conserve un court défilement vertical pour garder les textes,
les alertes et les commandes lisibles. Aucun débordement horizontal n'a été
constaté en 1920, 1440, 1366, 390 ou 320 pixels de largeur.

## Démo locale avec l'IA existante

Le [guide local](../docs/local-demo.md) fournit les cinq terminaux, les chemins
configurables pour un dépôt intégré ou des worktrees séparés, et l'observation
des commandes MQTT. Réutiliser le service IA propriétaire de la webcam.

Avec une IA fraîchement démarrée, le simulateur `--mode demo` envoie 20 mesures
normales puis cinq mesures extrêmes. Observer CALIBRATING, le score reçu,
ANOMALY, les courbes et les alertes. Après la fin des publications, les données
concernées deviennent STALE au bout de 30 secondes par défaut.

Pour accéder à l'API Raspberry depuis le PC ou partager le frontend sur le LAN,
voir les exemples d'URL, d'écoute réseau et de CORS dans le
[guide Raspberry](../docs/raspberry.md).

## Vérifications

```bash
npm run typecheck
npm run build
```

`build` vérifie aussi TypeScript et produit `dist/`. Pour vérifier ce build :

```bash
npm run preview
```

Le preview utilise aussi `http://localhost:5173` ; arrêter le serveur de
développement avant de le lancer.

La vérification locale a été effectuée dans Chromium, sur des ports isolés,
avec le vrai Mosquitto, FastAPI et les modules IsolationForest et simulateur de
l'IA existante : calibration de 20 mesures puis cinq anomalies, score reçu,
trois courbes et alerte environnementale. Des payloads de test ont validé
NORMAL, la présence humaine et la confiance de 95 %, sans accéder à la webcam.
Les deux boutons ont été vérifiés jusqu'à la réception des payloads MQTT exacts,
avec blocage pendant l'envoi et affichage d'une erreur sur un refus de l'API.
Les données périmées, les coupures/reconnexions du broker et du backend, les
infobulles et les vues mobile de 390 et 320 pixels ont aussi été vérifiés.
Le rejet des données REST/WebSocket incorrectes avait été validé à l'étape 4.
Aucun framework de tests frontend supplémentaire n'est nécessaire pour lancer
ou construire le projet.

Le [guide de démo locale](../docs/local-demo.md) rassemble les commandes de
lancement et le diagnostic. Le [guide Raspberry](../docs/raspberry.md) décrit
la configuration des URL pour un navigateur situé sur une autre machine.
