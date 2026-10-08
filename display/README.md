# Dashboard local PiTFT

Écran Adafruit PiTFT 2.8 résistif, 320×240, `/dev/fb0`, RGB565 16 bits.
L'affichage a été reconnu après activation de l'overlay
`pitft28-resistive,drm,rotate=90,speed=32000000` et `dtparam=spi=on`.
Le tactile STMPE610 était en erreur au démarrage. L'affichage seul a été validé
sur le Pi ; le dashboard sans interaction tactile n'en dépend pas.

Interface sombre : six cartes colorées (température, humidité, gaz, distance,
présence et alerte), sans sous-titre. Le haut indique la connexion API à MQTT.
Le HC-SR04 affiche sa distance ; « Sans écho » est un état normal sans mesure
de retour et ne déclenche pas une alerte. Cela ne garantit pas l'absence physique
d'un obstacle : un écho peut manquer pour plusieurs raisons. Le PIR HW-416 sur D3
est distinct : OUI/NON représente le booléen `presence` actuel, « — » représente
une mesure absente, désactivée ou périmée. Aucun remplacement par `motion`.
Les valeurs sont masquées
si l'API, MQTT, l'ESP ou la fraîcheur des mesures ne permettent pas un affichage
actuel. L'écran reçoit les snapshots WebSocket de FastAPI sur loopback, sans secret
MQTT et sans nouvelle écriture en base.
Chaque nouvelle mesure/alerte/statut reçu redessine l'écran. En l'absence de
messages, un rafraîchissement par seconde détecte les mesures périmées. La
connexion est rétablie automatiquement après une coupure. Aucun résumé minute
n'est utilisé pour le direct.

La carte alerte affiche « En alerte » pour une alerte critical de moins de
60 secondes, une commande buzzer ON publiée avec succès par l'API, ou une
mesure actuelle `buzzer=true` reçue de l'ESP. Une commande OFF efface l'état
de commande ON ; un buzzer confirmé actif reste signalé jusqu'au prochain relevé.
Ces commandes sont diffusées immédiatement par WebSocket, sans attendre la télémétrie.
L'état de commande est inconnu au redémarrage et ne constitue pas un accusé de
réception matériel. Les commandes externes MQTT sont visibles par le retour ESP.
La carte affiche « Avertissement » pour warning, et « Neutre » sans alerte récente
avec des données actuelles. Une API/MQTT inaccessible ou des mesures périmées
sans alerte récente affichent « — », jamais un état neutre trompeur. Ce n'est
pas un acquittement d'alarme physique : le contrat ne fournit pas de fin d'alerte.

Les six cartes restent visibles, y compris lors d'une alerte critique.

Le firmware ajoute `distance_sensor=true`, `distance_cm` (cm ou null sans écho)
et `presence=true/false` (PIR D3, null si désactivé). Les anciens firmwares restent acceptés mais
n'affichent pas de distance. Le champ `motion` conserve sa signification
historique de proximité pour compatibilité ; il ne pilote plus l'alarme locale
HC-SR04 ni le bloc présence de cet écran. Les alertes environnementales sont
décidées par l'IA du Pi ; l'ESP applique les commandes de l'API.
Les tendances conservent aussi la moyenne/min/max des distances
valides, le nombre de mesures sans écho et les détections du futur capteur.

## PC — Git Bash

```bash
cd ~/Perso/cosmoday-workshop
scp .runtime/display-deploy.tar.gz sentinelpi1@SentinelPi-1.local:~/cosmoday-workshop/
```

Recréer le paquet : `tar -czf .runtime/display-deploy.tar.gz display`.

## Pi — premier essai

```bash
cd ~/cosmoday-workshop
tar -xzf display-deploy.tar.gz
sudo apt install python3-pil python3-websockets fonts-dejavu-core
curl --fail http://127.0.0.1:8000/health
sudo python3 display/sentinel_dashboard.py --tty /dev/tty1
```

Laisser la commande tourner et observer l'écran. Ctrl+C restaure le mode texte.
Le premier essai est exécuté avec sudo pour isoler les éventuels problèmes de
droits console. Le service final utilise `sentinelpi1`, les groupes vidéo/tty et
la seule capacité de configuration console. Ni bureau ni Chromium nécessaires.
Le service autorise l'écriture du groupe tty sur `/dev/tty1` avant chaque lancement,
car getty peut laisser cette console en mode 0600. Le framebuffer reste limité
au groupe video ; aucun accès n'est accordé aux autres utilisateurs.
La géométrie, le format RGB et la longueur des lignes sont lus par ioctl avant
écriture ; le programme refuse un format différent plutôt que de deviner.
Le framebuffer est écrit par mémoire partagée `mmap` pour utiliser le suivi
des pages modifiées du pilote. Voir la [documentation noyau](https://kernel.org/doc/html/v5.12/fb/deferred_io.html).

Si la console reste visible, arrêter avec Ctrl+C et isoler le test d'affichage :

```bash
sudo python3 display/sentinel_dashboard.py --demo --tty /dev/tty1
```

Ce test utilise des valeurs simulées, sans API. Le log « First frame written to
framebuffer » confirme que le programme a écrit, mais seule l'observation de
l'écran confirme le résultat. Si nécessaire, relever `cat /sys/class/tty/tty0/active`
et `cat /proc/fb` pour vérifier la console active et le framebuffer.

## Démarrage automatique après validation visuelle

Arrêter le test manuel avant d'activer le service.

```bash
sudo install -m 644 display/sentinel-display.service /etc/systemd/system/sentinel-display.service
sudo systemctl daemon-reload
sudo systemctl enable --now sentinel-display
systemctl status sentinel-display --no-pager
```

En cas d'erreur : `journalctl -u sentinel-display -n 40 --no-pager`.
Vérifier après redémarrage du Pi que les données reviennent et qu'une API
indisponible est signalée. Ne pas rendre `/dev/fb0` accessible à tous.
Arrêter : `sudo systemctl disable --now sentinel-display`.

## Prévisualisation sans écran

```bash
python display/sentinel_dashboard.py --demo --preview .runtime/pitft-preview.png
```

L'aperçu est simulé. Le fonctionnement physique, les permissions systemd et la
restauration de console doivent être validés sur le Pi avant d'être déclarés acquis.
