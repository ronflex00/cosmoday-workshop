# AI Environment Intelligence

Cette couche interprète les mesures et la persistance des résultats
IsolationForest. Elle conserve le modèle, ses scores, les pages Overview et
AI Vision, ainsi que tous les panneaux de la page `/environment`.
Les observations décrivent ce qui se passe pendant une anomalie ; elles
n'attribuent pas une cause au modèle et ne prédisent pas un incident.

## Niveaux et épisodes

| Niveau | Signification | Réaction automatique |
| --- | --- | --- |
| NORMAL | Le modèle est prêt, classifie la mesure comme normale et aucune tendance inhabituelle n'est observée | Aucune |
| WATCH | Le modèle classifie la mesure comme normale, mais les dernières mesures varient sensiblement | Aucune |
| WARNING | Une anomalie IsolationForest isolée | Affichage et alerte existante |
| CRITICAL | Au moins deux anomalies parmi les trois derniers résultats distincts | Un événement critique par épisode ; impulsion physique uniquement si activée |

Un épisode critique reste mémorisé jusqu'à **deux résultats normaux consécutifs**.
Les résultats supplémentaires pendant l'épisode ne provoquent pas de nouveau bip.
Une nouvelle anomalie persistante après ce réarmement peut déclencher une
nouvelle impulsion. STOP ALARM interrompt l'impulsion courante sans réarmer le
modèle ni provoquer de nouveau déclenchement dans le même épisode.

Seuls des résultats `ready=true`, issus de `isolation_forest`, avec un timestamp
strictement croissant sont comptés. Ils doivent être âgés d'au plus 30 secondes
et ne pas être situés plus de cinq secondes dans le futur. Les doublons et
résultats reçus dans le désordre ne renforcent pas la persistance. Un intervalle
de plus de 30 secondes, une calibration ou une coupure MQTT interrompent la
fenêtre de résultats ; ils ne réarment pas à eux seuls un épisode critique.

La carte **AI ENVIRONMENT INTERPRETATION** décrit la température, l'humidité et
le gaz sur les dernières mesures fraîches d'un même appareil. Elle affiche les
variations absolues et relatives, la stabilité et l'intensité des tendances.
Une référence à zéro ne produit pas de pourcentage infini. Les bandes utilisées
pour décrire une variation ne remplacent jamais la classification du modèle.
Le risque affiché est reconstruit depuis l'historique reçu par le navigateur :
des épisodes plus anciens ou certaines coupures MQTT peuvent manquer dans ce
cache borné. Le backend conserve indépendamment l'état qui pilote les alarmes.
Une connexion absente, des résultats périmés, un modèle en calibration ou trop
peu de données donnent un état d'attente explicite, sans affirmation de sécurité.

## Configuration

Dans `backend/.env` pour un lancement manuel, ou `.env.local` avec le lanceur :

```dotenv
AI_AUTO_ALARM=false
```

La valeur par défaut est `false`. L'interprétation, la carte et l'événement
critique restent actifs ; aucune commande physique automatique n'est publiée.
Passer à `true` puis redémarrer le backend active les impulsions pour les
nouveaux épisodes critiques. Docker transmet cette variable au service `api`.
Le backend fonctionne en **un seul processus** : plusieurs workers ne doivent
pas piloter le même ESP sans coordination supplémentaire.

Pour masquer uniquement la nouvelle carte, ajouter dans `frontend/.env` :

```dotenv
VITE_ENVIRONMENT_INTELLIGENCE=false
```

Puis relancer Vite, ou reconstruire le frontend. Ce réglage d'affichage ne
désactive pas l'orchestration backend.

## Commandes et priorité manuelle

Le navigateur ne pilote jamais les alarmes automatiques. Avec
`AI_AUTO_ALARM=true`, le backend publie sur le topic existant
`sentinel/commands`, en conservant exactement les deux champs du contrat :

| Temps après activation | Sans alarme manuelle active |
| --- | --- |
| 0 seconde | `{"buzzer":true,"led":"red"}` |
| 0,5 seconde | `{"buzzer":false,"led":"red"}` |
| 0,8 seconde | `{"buzzer":true,"led":"red"}` |
| 1,3 seconde | `{"buzzer":false,"led":"red"}` |
| Environ 5 secondes | `{"buzzer":false,"led":"green"}` |

Les publications sont sérialisées et calculées à partir de l'état manuel et
de l'état IA. Si ACTIVATE ALARM a activé le buzzer, la fin de l'impulsion IA
le conserve actif. Une LED rouge demandée manuellement reste également active.
STOP ALARM annule l'impulsion IA et demande l'arrêt des sorties distantes.
L'environnement utilise deux bips de 0,5 seconde séparés par 0,3 seconde.
La caméra conserve son bip unique et ne peut pas interrompre une impulsion
critique environnement déjà en cours.

Toutes les commandes manuelles distantes doivent passer par
`POST /api/v1/commands`. Le contrat MQTT n'indique ni origine ni état physique :
un autre contrôleur publiant directement sur `sentinel/commands` échappe à cet
arbitrage. Après mise à jour depuis une ancienne version, envoyer explicitement
STOP ALARM ou ACTIVATE ALARM via l'API pour établir l'état manuel suivi.
Si une ancienne base contient déjà des données sans état manuel enregistré,
le backend suspend les impulsions IA tant que cette commande explicite n'a
pas réussi. Les événements critiques continuent à être enregistrés.
Sur le firmware actuel, `red` allume l'unique LED et `green` l'éteint ; la commande
ne transforme pas le matériel en LED bicolore.

## Stockage et reprise

Une alerte supplémentaire utilise le type existant
`ENVIRONMENTAL_ANOMALY`, avec `severity=critical`. Elle est enregistrée avec le
résultat du modèle avant sa diffusion REST/WebSocket/MQTT. L'alerte initiale
de sévérité `warning` est conservée. Les autres mesures de l'épisode restent
dans l'historique sans multiplier les événements critiques.
Une alternance de résultats anormaux et d'une seule mesure normale pendant
l'épisode ne duplique pas non plus l'alerte initiale `warning`. Les deux résultats
normaux consécutifs autorisent ensuite de nouvelles alertes pour un autre épisode.

La table interne additive `sentinel_environment_state` conserve l'épisode et
l'état des commandes manuelles. Les tables sont créées automatiquement ; les
historiques existants et leurs endpoints ne changent pas. Le redémarrage ne
rejoue aucune impulsion depuis des résultats historiques. Si une impulsion a
été interrompue, le contrôleur tente de remettre les sorties distantes dans
l'état manuel mémorisé après reconnexion.
L'intention d'une commande manuelle est enregistrée avant sa publication.
Si la base ne permet pas cet enregistrement, ACTIVATE ALARM renvoie `503`
sans envoyer ON. STOP ALARM tente tout de même l'arrêt, mais renvoie `503`
si son état durable n'a pas pu être confirmé : le répéter une fois la base
disponible. Une extinction IA interrompue peut être réessayée, même si le flag
est ensuite désactivé ; aucun nouvel épisode IA n'est activé dans ce cas.
Le script de migration SQLite vers PostgreSQL transfère également ces états
internes, et accepte les anciennes bases qui ne possèdent pas encore la table.

MQTT reste en QoS 0, sans retain ni accusé de réception physique. Les durées
sont celles de l'orchestration ; une coupure réseau peut empêcher la livraison
d'un OFF à temps. Le firmware conserve son état distant jusqu'à réception
d'une nouvelle commande. Une garantie matérielle d'extinction pendant une
coupure nécessiterait un mécanisme supplémentaire côté ESP.

## Test manuel

Depuis la racine du dépôt, lancer le projet sans générateur automatique :

```bash
AI_AUTO_ALARM=false python3 scripts/local.py start --no-demo
```

Ajouter `--no-camera` pour tester sans webcam. Si une session tourne déjà,
arrêter d'abord cette session avec `python3 scripts/local.py stop` avant de
la relancer. Ouvrir **http://localhost:5173/environment** et vérifier que tous
les anciens panneaux restent présents avec la nouvelle carte.

Observer commandes et événements dans un deuxième terminal :

```bash
mosquitto_sub -h localhost -p 18883 \
  -t sentinel/commands -t sentinel/ai/anomaly -t sentinel/alerts -v
```

Pour une vérification logicielle sans capteurs, envoyer des télémétries de
test dans un troisième terminal. Le générateur n'étiquette aucune mesure ;
IsolationForest prend toujours la décision :

```bash
MQTT_HOST=localhost MQTT_PORT=18883 MQTT_TLS=false MQTT_USERNAME='' MQTT_PASSWORD='' \
  ai/.venv/bin/python ai/scripts/send_fake_telemetry.py --mode demo --interval 1.1
```

Avec une IA fraîchement démarrée, les 20 premières mesures servent à la
calibration, puis cinq mesures extrêmes sont analysées. Vérifier WARNING puis
CRITICAL si le modèle émet les anomalies persistantes attendues. Une alerte
critique doit apparaître dans les événements et dans la base, sans commande
automatique lorsque le flag vaut `false` :

```bash
curl --fail 'http://localhost:8000/api/v1/history/alerts?limit=20'
curl --fail 'http://localhost:8000/api/v1/history/anomalies?limit=20'
```

Pour tester le matériel, relancer avec `AI_AUTO_ALARM=true` et un ESP connecté
au même broker. Établir d'abord l'état distant suivi :

```bash
curl --fail http://localhost:8000/api/v1/commands \
  -H 'Content-Type: application/json' -d '{"buzzer":false,"led":"green"}'
```

Un épisode enregistré avec le flag désactivé n'est pas rejoué en l'activant.
Après le redémarrage de l'IA, envoyer assez de mesures pour calibrer le modèle
et obtenir deux résultats normaux consécutifs, puis des mesures extrêmes :

```bash
MQTT_HOST=localhost MQTT_PORT=18883 MQTT_TLS=false MQTT_USERNAME='' MQTT_PASSWORD='' \
  ai/.venv/bin/python ai/scripts/send_fake_telemetry.py --mode normal --count 30 --interval 1.1
MQTT_HOST=localhost MQTT_PORT=18883 MQTT_TLS=false MQTT_USERNAME='' MQTT_PASSWORD='' \
  ai/.venv/bin/python ai/scripts/send_fake_telemetry.py --mode anomaly --count 5 --interval 1.1
```

Observer une seule séquence ON, OFF buzzer, retour LED par épisode.
Sans ESP, l'observateur MQTT permet de
vérifier les commandes publiées. Le navigateur peut être fermé pendant ce test.

Envoyer ensuite des mesures normales ; les **résultats du modèle** doivent
contenir deux classifications normales consécutives pour réarmer :

```bash
MQTT_HOST=localhost MQTT_PORT=18883 MQTT_TLS=false MQTT_USERNAME='' MQTT_PASSWORD='' \
  ai/.venv/bin/python ai/scripts/send_fake_telemetry.py --mode normal --count 10 --interval 1.1
MQTT_HOST=localhost MQTT_PORT=18883 MQTT_TLS=false MQTT_USERNAME='' MQTT_PASSWORD='' \
  ai/.venv/bin/python ai/scripts/send_fake_telemetry.py --mode anomaly --count 5 --interval 1.1
```

Une nouvelle séquence est alors autorisée. Le modèle peut classer certaines
mesures du mode `normal` comme atypiques : consulter sa sortie pour confirmer
le réarmement. L'IA actuelle date ses résultats à la seconde ; l'intervalle
de 1,1 seconde évite de compter deux publications au même timestamp.

Pendant une impulsion, tester ACTIVATE ALARM depuis l'Overview et vérifier que
le buzzer reste actif au-delà de cinq secondes. STOP ALARM doit ensuite arrêter
les sorties distantes. Les mêmes actions se testent dans un quatrième terminal :

```bash
curl --fail http://localhost:8000/api/v1/commands \
  -H 'Content-Type: application/json' -d '{"buzzer":true,"led":"red"}'
curl --fail http://localhost:8000/api/v1/commands \
  -H 'Content-Type: application/json' -d '{"buzzer":false,"led":"green"}'
```

Adapter les ports et les identifiants pour un broker MQTTS. Pour tester avec
des données réelles, conserver `--no-demo` et laisser l'ESP publier la
télémétrie ; ne pas lancer `send_fake_telemetry.py`.

## Tests automatisés

```bash
(cd backend && .venv/bin/python -m unittest discover -s tests -v)
(cd ai && .venv/bin/python -m unittest discover -s tests -v)
python3 -m unittest discover -s tests -v
(cd frontend && npm test)
(cd frontend && npm run typecheck)
(cd frontend && npm run build)
```

Les tests utilisent des bases temporaires, des clients MQTT isolés et des
horloges contrôlées pour vérifier les durées, le réarmement, les priorités
manuelles et les reprises, sans action sur le matériel de la démo.
