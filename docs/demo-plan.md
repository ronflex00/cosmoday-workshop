# Démo live cible

1. Dashboard : système en ligne, capteurs visibles.
2. Une personne passe devant la caméra -> `person_detected=true` -> alerte intrusion.
3. Le dashboard passe en alerte.
4. Bouton "Activer alarme" -> API -> MQTT -> ESP -> LED/buzzer.
5. Variation simulée des capteurs -> IsolationForest publie une anomalie.
6. Montrer rapidement Docker, MQTTS/TLS et UFW pour prouver la partie infra/cyber.
