#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Point d'entrée principal pour l'assistant interactif Angel Enhanced.
Ce script démarre les différents services et composants de l'application.
"""

import asyncio
import logging
import sys
import signal
from config.settings import Settings
from core.app_manager import AppManager

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/angel.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("angel")

def signal_handler(sig, frame):
    """Gestionnaire de signal pour arrêter proprement l'application"""
    logger.info("Signal d'arrêt reçu, arrêt en cours...")
    app_manager.stop()
    sys.exit(0)

async def main():
    """Fonction principale asynchrone"""
    global app_manager
    
    # Charger les paramètres de configuration
    settings = Settings()
    logger.info(f"Configuration chargée depuis {settings.config_file}")
    
    # Créer et démarrer le gestionnaire d'application
    app_manager = AppManager(settings)
    
    # Configurer les gestionnaires de signaux
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Démarrer l'application
    await app_manager.start()
    
    # Maintenir l'application en fonctionnement
    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Arrêt demandé par l'utilisateur...")
    finally:
        await app_manager.stop()

if __name__ == "__main__":
    try:
        # Créer le dossier de logs s'il n'existe pas
        import os
        os.makedirs("logs", exist_ok=True)
        
        # Démarrer la boucle asyncio
        asyncio.run(main())
    except Exception as e:
        logger.exception(f"Erreur fatale: {e}")
        sys.exit(1)
