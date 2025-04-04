#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Gestionnaire principal de l'application.
Coordonne les différents services et modules.
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional

from config.settings import Settings
from connectors.angel_server_connector import AngelServerConnector
from events.event_manager import EventManager
from events.event_types import EventPriority
from decision.recommendation_engine import RecommendationEngine
from avatar.avatar_controller import AvatarController
from api.api_server import ApiServer

logger = logging.getLogger("angel.core")

class AppManager:
    """
    Gestionnaire principal de l'application.
    Coordonne tous les services et composants.
    """
    
    def __init__(self, settings: Settings):
        """
        Initialise le gestionnaire d'application
        
        Args:
            settings (Settings): Configuration de l'application
        """
        self.settings = settings
        logger.info("Initialisation du gestionnaire d'application")
        
        # Initialisation des composants
        self.event_manager = EventManager()
        self.angel_connector = AngelServerConnector(
            settings.angel_server_url, 
            settings.angel_server_key,
            self.event_manager
        )
        self.recommendation_engine = RecommendationEngine(
            self.event_manager,
            settings
        )
        self.avatar_controller = None
        if settings.avatar_enabled:
            self.avatar_controller = AvatarController(
                self.event_manager,
                settings
            )
        
        # API pour les interactions externes
        self.api_server = ApiServer(
            settings.host,
            settings.port,
            self.event_manager,
            settings
        )
        
        # État de l'application
        self.running = False
        self.tasks = []
    
    async def start(self):
        """Démarre tous les services de l'application"""
        if self.running:
            logger.warning("L'application est déjà en cours d'exécution")
            return
        
        logger.info("Démarrage de l'application...")
        self.running = True
        
        # Démarrer le gestionnaire d'événements
        await self.event_manager.start()
        
        # Démarrer le connecteur au serveur Angel
        await self.angel_connector.start()
        
        # Démarrer le moteur de recommandations
        await self.recommendation_engine.start()
        
        # Démarrer le contrôleur d'avatar si activé
        if self.avatar_controller:
            await self.avatar_controller.start()
        
        # Démarrer le serveur API
        self.tasks.append(asyncio.create_task(self.api_server.start()))
        
        logger.info("Application démarrée avec succès")
    
    async def stop(self):
        """Arrête tous les services de l'application"""
        if not self.running:
            logger.warning("L'application n'est pas en cours d'exécution")
            return
        
        logger.info("Arrêt de l'application...")
        self.running = False
        
        # Arrêter le serveur API
        await self.api_server.stop()
        
        # Arrêter le contrôleur d'avatar si activé
        if self.avatar_controller:
            await self.avatar_controller.stop()
        
        # Arrêter le moteur de recommandations
        await self.recommendation_engine.stop()
        
        # Arrêter le connecteur au serveur Angel
        await self.angel_connector.stop()
        
        # Arrêter le gestionnaire d'événements
        await self.event_manager.stop()
        
        # Annuler toutes les tâches en cours
        for task in self.tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        logger.info("Application arrêtée avec succès")
    
    async def restart(self):
        """Redémarre l'application"""
        logger.info("Redémarrage de l'application...")
        await self.stop()
        await asyncio.sleep(1)  # Attendre un peu pour s'assurer que tout est bien arrêté
        await self.start()
