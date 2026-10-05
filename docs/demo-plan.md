# Démo live cible

Lancer d'abord les services avec le [guide local](local-demo.md), ou utiliser
les paramètres du [guide Raspberry](raspberry.md). Attendre les abonnements MQTT
avant d'envoyer la télémétrie. Le mode `demo` de l'IA validée envoie 20 mesures
normales, attend deux secondes, puis envoie cinq mesures extrêmes.

1. Dashboard : système en ligne, capteurs visibles.
2. Une personne passe devant la caméra -> `person_detected=true` -> alerte intrusion.
3. Le dashboard passe en alerte.
4. Bouton "Activer alarme" -> API -> MQTT -> ESP -> LED/buzzer.
5. Variation simulée des capteurs -> IsolationForest publie une anomalie.
6. Montrer Docker, MQTTS/TLS et UFW lorsque leur intégration a été validée par
   l'équipe infra ; ces fonctions ne sont pas activées par le backend/dashboard.

## Ce qui doit être visible

- Backend ONLINE et MQTT CONNECTED.
- Température, humidité, gaz et mouvement issus de messages réels.
- CALIBRATING avec score absent, puis score numérique calculé par IsolationForest.
- Présence humaine avec confiance et panneau rouge ; anomalie avec panneau rouge,
  calibration orange et fonctionnement normal vert.
- Trois courbes, une alerte par activation, aucun doublon sur les détections répétées.
- Deux payloads de commande exacts reçus sur `sentinel/commands`.

La confirmation dashboard valide l'envoi de la commande. L'effet physique se
montre sur l'ESP ; le protocole actuel ne fournit pas d'accusé de réception.
Après la démo finie, continuer à envoyer des mesures si nécessaire pour garder
les données actuelles. Le seuil STALE est de 30 secondes par défaut.

En bonus, arrêter puis relancer volontairement l'API : les valeurs restent
visibles pendant la coupure, les commandes sont désactivées, puis React se
reconnecte sans recharger la page. Les nouvelles publications remplissent
l'état backend après son redémarrage.
