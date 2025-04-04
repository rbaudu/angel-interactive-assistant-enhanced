# Angel Interactive Assistant Enhanced

Assistant interactif proactif avancé qui surveille les activités et propose des recommandations contextuelles adaptées aux besoins de l'utilisateur.

## Caractéristiques

- Surveillance proactive des activités via angel-server-capture
- Système de recommandations contextuelles (repas, médicaments, etc.)
- Gestion des événements intrusifs (appels, emails urgents, etc.)
- Suggestions contextuelles basées sur la météo et les activités
- Interface utilisateur avec avatar pour une interaction naturelle

## Architecture

Le système est organisé en plusieurs modules :

- **Core** : Noyau principal et configuration
- **Connectors** : Connecteurs pour angel-server-capture et autres services
- **Decision** : Logique de décision pour les recommandations
- **Events** : Gestion des différents types d'événements
- **Avatar** : Interface utilisateur avec avatar
- **API** : API pour les interactions externes

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

Modifiez le fichier `config/settings.py` pour ajuster les paramètres selon vos besoins.

## Démarrage

```bash
python main.py
```