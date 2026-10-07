# Broker Docker MQTTS — préparation et validation

Voir le [compte rendu des tests sur le Pi](mqtt-validation.md) pour distinguer
les contrôles réalisés des validations restantes.

Le Compose active désormais uniquement le listener MQTT TLS sur `8883`.
Les profils de démonstration locale restent distincts : ne pas utiliser
`scripts/local.py` pour déployer ce broker sur le Pi.

## Fichiers privés à préparer sur le Pi

| Chemin | Utilisation |
| --- | --- |
| `infra/mosquitto/certs/ca.crt` | CA publique à distribuer aux clients |
| `infra/mosquitto/certs/server.crt` | Certificat serveur signé par la CA |
| `infra/mosquitto/certs/server.key` | Clé privée serveur |
| `secrets/mqtt/passwords` | Mots de passe hachés par `mosquitto_passwd` |

Ces chemins sont ignorés par Git. Conserver la clé privée de la CA dans un
emplacement privé hors du dossier `certs`, non monté dans le broker.
Sauvegarder les clés hors Git ; ne jamais les copier dans un chat.

## Comptes et droits

Les noms correspondent aux sections de `infra/mosquitto/config/acl`.
Tout topic non autorisé est refusé.

| Compte | Publication | Lecture |
| --- | --- | --- |
| `sentinel-esp` | Télémétrie, état device, alertes locales | Commandes, alertes |
| `sentinel-api` | Alertes et commandes manuelles (endpoints existants) | Télémétrie, état device, résultats IA, alertes |
| `sentinel-ai` | Résultats vision et anomalie | Télémétrie |
| `sentinel-controller` | Alertes consolidées, commandes automatiques | Télémétrie, état device, résultats IA, alertes |

Flux cible : IA → MQTT sur le Pi → service de décision Pi → alertes et
commandes → ESP (LED/buzzer). L'API lit les informations pour le dashboard.
Le service de décision n'est pas encore implémenté ; ces ACL préparent son
compte sans activer d'alarme automatique. Le firmware reste à intégrer.
L'ESP publie ses alertes locales et reçoit les événements consolidés sur
`sentinel/alerts` ; les ordres LED/buzzer gardent le format `sentinel/commands`.
Le service de décision devra filtrer les alertes qu'il publie pour éviter les
boucles et définir les règles d'activation, d'arrêt et de priorité.
L'API actuelle crée encore des alertes à partir de l'IA et ne lit pas
`sentinel/alerts` : déplacer cette décision vers le service Pi et ajouter
l'abonnement API seront des modifications ultérieures, à valider ensemble.
Les endpoints manuels obligatoires restent présents ; leurs droits pourront
être resserrés une fois leur rôle et l'authentification finalisés.

L'API actuelle ne s'abonne pas encore à l'état device ; son droit de lecture
prépare cette intégration. Le contrat `docs/contracts.md` reste inchangé.

## Préparation avant démarrage

1. Confirmer le nom réellement résolu par tous les clients. Le modèle utilise
   `SentinelPi-1.local` : tester sa résolution mDNS sur l'ESP. Si nécessaire,
   choisir un nom DNS ou une IP réservée dans le plan réseau existant.
2. Générer une CA privée et un certificat serveur RSA adapté à l'ESP8266.
   Le SAN doit inclure le nom choisi, ainsi que `DNS:mqtt` si la future API
   conteneurisée utilise le nom de service Compose et `DNS:localhost` pour
   les contrôles depuis le Pi. Une connexion par IP exige un SAN de type IP.
   Vérifier dates, chaîne et SAN ; synchroniser l'heure du Pi et de l'ESP.
3. Créer les comptes avec des secrets distincts via les invites
   interactives de `mosquitto_passwd` dans l'image `eclipse-mosquitto:2`.
   Ne pas utiliser `-b` (mot de passe dans les arguments). Utiliser `-c`
   uniquement pour le premier compte ; sans `-c` pour les suivants.
4. Vérifier l'UID/GID avec `id mosquitto` dans l'image avant de définir les
   propriétaires. Rendre `server.key`, `passwords` et le fichier `config/acl` lisibles par cet
   utilisateur en `0600`. Les répertoires parents doivent lui permettre
   la traversée. Les certificats publics peuvent être en `0644`.

Les étapes de génération et les tests seront exécutés progressivement sur le
Pi ; aucun certificat ni secret n'est fourni par ce dépôt. Les bind mounts
refusent de créer silencieusement les chemins privés absents. Ne pas résoudre
un problème de permission avec `chmod 777`.

## Démarrage du broker seul

Le broker seul ne nécessite pas de secret PostgreSQL. Pour déployer la DB et
l'API ensuite, suivre le [guide PostgreSQL](postgresql-pi.md) : le Compose actuel
utilise un fichier de mot de passe privé, avec les noms DB/utilisateur du `.env`.

```bash
sudo docker compose config --quiet
sudo docker compose up -d mqtt
sudo docker compose ps mqtt
sudo docker compose logs --tail=50 mqtt
sudo ss -lntp
```

`up -d mqtt` ne démarre ni l'API ni PostgreSQL. Le broker n'a pas encore de
healthcheck authentifié : `running` ne prouve pas que TLS/MQTT fonctionne.
Les logs vont sur stdout avec rotation Docker (3 fichiers de 10 Mo) ; les
données MQTT persistent dans `mqtt_data`.

## Validation obligatoire

Avec le SAN `DNS:localhost`, vérifier chaîne et nom depuis le Pi :

```bash
openssl s_client -connect localhost:8883 -servername localhost \
  -CAfile infra/mosquitto/certs/ca.crt \
  -verify_hostname localhost -verify_return_error </dev/null
```

Attendu : vérification réussie. Répéter depuis le poste admin avec le nom réseau
réel et la CA publique. Un nom erroné ou une CA étrangère doit être refusé.
Ne jamais utiliser `--insecure` ou `setInsecure()`.

Avec les clients Mosquitto, utiliser des fichiers de configuration clients
privés (`0600`, hors Git) pour éviter les mots de passe dans les arguments :

- connexion anonyme et mauvais mot de passe refusés ;
- publication ESP sur `sentinel/telemetry`, réception par API/IA ;
- publication API sur `sentinel/commands`, réception par ESP ;
- publication IA vision/anomalie, réception par API ;
- réception des alertes ESP par le futur contrôleur et l'API après intégration ;
- publication automatique du contrôleur sur `sentinel/commands`, réception
  par ESP (à tester après implémentation du service de décision) ;
- publication de commandes par ESP/IA refusée : MQTT v5/QoS 1 pour observer
  le refus, et vérifier l'absence de réception par ESP ;
- aucune connexion sur `1883` ;
- reconnexion après redémarrage du broker.

TLS authentifie le serveur. `require_certificate false` signifie que les
clients utilisent leurs identifiants MQTT sans certificat client.
`tls_version tlsv1.2` fixe le minimum à TLS 1.2. Les ACL limitent les topics,
sans valider le contenu JSON ; la validation applicative reste nécessaire.

Pour les clients, régler `MQTT_TLS=true`, `MQTT_PORT=8883`, le chemin CA et
le compte correspondant. Le modèle racine vise l'API ; configurer l'IA
séparément avec `sentinel-ai`. Le hostname doit correspondre au SAN.

Vérifier le filtrage Docker en IPv4 et IPv6 depuis une autre machine : UFW
seul ne protège pas les ports publiés. La compatibilité ARM64 et la charge
restent à valider sur le Pi. Cette préparation ne constitue pas une validation
de sécurité ni un déploiement terminé.

Références : [Mosquitto](https://mosquitto.org/man/mosquitto-conf-5.html),
[Docker et filtrage réseau](https://docs.docker.com/engine/network/packet-filtering-firewalls/).
