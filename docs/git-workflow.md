# Workflow Git — sprint 3 jours

Branches permanentes :

- `main` : version stable et démontrable.
- `feat/infra`
- `feat/api-dashboard`
- `feat/ai`
- `feat/firmware`

Règles :

1. `git pull --rebase origin main` avant de commencer une session.
2. Faire des commits petits et explicites : `feat(ai): detect person with webcam`.
3. Pousser au moins toutes les 1 à 2 heures.
4. Fusionner dans `main` à chaque fonctionnalité démontrable.
5. Ne jamais commit `.env`, certificats privés, mots de passe ou modèles lourds.

Exemples de commits :

```text
feat(infra): add mosquitto docker service
feat(api): subscribe to telemetry topic
feat(front): display live sensor cards
feat(ai): add webcam person detection
feat(ai): publish isolation forest result
fix(mqtt): reconnect client after broker restart
security(mqtt): enable TLS listener
```
