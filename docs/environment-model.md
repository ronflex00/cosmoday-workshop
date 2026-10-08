# Modèle environnement sur le Raspberry Pi

Le processus `src.environment_main` recharge automatiquement
`ai/models/environment.joblib` au démarrage. En l'absence de fichier,
il apprend la référence puis sauvegarde le modèle. Le chemin est configurable
avec `AI_ENVIRONMENT_MODEL_PATH`. Le fichier contient le modèle, la date,
le nombre de mesures, l'ordre des trois variables et la version de scikit-learn.
Charger uniquement un fichier créé localement par ce projet : joblib utilise
la sérialisation Python. Une version incompatible ou un fichier corrompu
arrête le démarrage et demande un réentraînement explicite.

Pour refaire la référence, définir `AI_ENVIRONMENT_RETRAIN=true` uniquement
sur la commande d'apprentissage. L'ancien modèle est conservé jusqu'à la
sauvegarde complète du nouveau. Ne pas laisser cette option dans `.env` :
elle ferait réentraîner à chaque redémarrage.

## Sur le Pi

Après transfert des sources à jour, arrêter le processus environnement existant
avant de lancer le nouveau (la caméra reste indépendante) :

```bash
pkill -TERM -f '[p]ython.*-m src.environment_main'
```

Vérifier avec `pgrep -af '[s]rc.environment_main'` qu'il est bien arrêté.
Lancer l'apprentissage sur 300 mesures dans des conditions normales :

```bash
cd ~/cosmoday-workshop/ai
nohup env AI_TRAINING_SAMPLES=300 AI_ENVIRONMENT_RETRAIN=true \
  .venv/bin/python -u -m src.environment_main \
  > environment.log 2>&1 < /dev/null &
tail -f environment.log
```

Le message `IsolationForest saved` confirme la sauvegarde. Ctrl+C ferme
`tail` sans arrêter l'IA. Le modèle continue à analyser et publier vers
`sentinel/ai/anomaly`, que l'API et le dashboard consomment déjà.

Après l'apprentissage, vérifier le rechargement en arrêtant ce processus
comme ci-dessus, puis en le relançant sans `AI_ENVIRONMENT_RETRAIN` :

```bash
cd ~/cosmoday-workshop/ai
nohup env AI_ENVIRONMENT_RETRAIN=false \
  .venv/bin/python -u -m src.environment_main \
  > environment.log 2>&1 < /dev/null &
tail -f environment.log
```

Attendre `IsolationForest loaded`, puis vérifier une date récente et
`ready:true` via `curl http://127.0.0.1:8080/api/v1/ai/status`.
Conserver `AI_AUTO_ALARM=false` tant que les fausses alertes ne sont pas
validées. La détection apprend les valeurs température, humidité et gaz ;
elle n'analyse pas encore des fenêtres de tendance temporelle.
