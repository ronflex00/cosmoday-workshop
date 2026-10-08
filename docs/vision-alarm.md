# Alerte courte à la détection d'une personne

L'API reçoit `sentinel/ai/vision` et, avec `AI_VISION_ALARM=true`, commande
un bip d'une seconde et la LED rouge pendant cinq secondes sur l'ESP.
Le firmware et le programme caméra restent inchangés.

Une présence continue ne prolonge pas le bip. Les résultats négatifs doivent
couvrir trois secondes, avec des résultats espacés d'au plus deux secondes,
avant de réarmer une nouvelle détection. Les messages anciens (plus de trente
secondes), désordonnés, dupliqués ou issus d'une connexion MQTT obsolète
ne déclenchent pas le buzzer. Les commandes manuelles restent prioritaires :
une alarme activée manuellement reste active à la fin du bip automatique.

`AI_AUTO_ALARM` concerne séparément l'IA environnement. Activer la caméra
ne nécessite pas d'activer cette option.

## Déploiement

Depuis Git Bash sur le PC :

```bash
cd ~/Perso/cosmoday-workshop
scp .runtime/vision-alarm-deploy.tar.gz sentinelpi1@SentinelPi-1.local:~/cosmoday-workshop/
```

Dans une session SSH sur le Pi :

```bash
cd ~/cosmoday-workshop
tar -xzf vision-alarm-deploy.tar.gz
sed -i '/^AI_VISION_ALARM=/d' .env
printf '\nAI_VISION_ALARM=true\n' >> .env
sudo docker compose up -d --build api
curl --fail --show-error -H 'Content-Type: application/json' \
  -d '{"buzzer":false,"led":"green"}' http://127.0.0.1:8000/api/v1/commands
```

La dernière commande établit explicitement l'état manuel initial arrêté ;
elle arrête aussi une éventuelle alarme manuelle en cours.
Laisser l'ESP avec le firmware Sentinel et le programme `src.vision_main`
en fonctionnement. Passer devant la caméra : un bip, puis arrêt du buzzer
après une seconde et extinction de la LED après cinq secondes. Attendre trois
secondes de résultats sans personne puis revenir pour tester le réarmement.
Si la LED physique ne fonctionne pas, vérifier le buzzer et les commandes
dans le moniteur série ; l'affichage `LED : ON` ne prouve pas le câblage.

Pour désactiver les bips caméra, remettre `AI_VISION_ALARM=false` dans `.env`
et recréer l'API avec `sudo docker compose up -d api`.
