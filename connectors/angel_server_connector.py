#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Connecteur pour interagir avec angel-server-capture.
Permet de récupérer les activités détectées et de proposer des activités.
"""

import asyncio
import logging
import json
import time
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
import aiohttp

from events.event_manager import EventManager
from events.event_types import Event, EventType, EventPriority

logger = logging.getLogger("angel.connectors.angel_server")

class AngelServerConnector:
    """
    Connecteur pour interagir avec le serveur Angel.
    Permet de récupérer les activités de l'utilisateur et de proposer des activités.
    """
    
    def __init__(self, server_url: str, api_key: Optional[str], event_manager: EventManager):
        """
        Initialise le connecteur Angel Server
        
        Args:
            server_url (str): URL du serveur Angel
            api_key (Optional[str]): Clé API pour l'authentification (peut être None)
            event_manager (EventManager): Gestionnaire d'événements pour publier les activités
        """
        self.server_url = server_url.rstrip('/')
        self.api_key = api_key
        self.event_manager = event_manager
        self.session = None
        self.running = False
        self.poll_task = None
        self.last_activity_id = None
        
        logger.info(f"Connecteur Angel Server initialisé: {self.server_url}")
    
    async def start(self):
        """Démarre le connecteur et initialise la session HTTP"""
        if self.running:
            logger.warning("Le connecteur Angel Server est déjà en cours d'exécution")
            return
        
        logger.info("Démarrage du connecteur Angel Server")
        self.running = True
        self.session = aiohttp.ClientSession()
        
        # Vérifier la connexion au serveur
        try:
            await self._check_server_connection()
        except Exception as e:
            logger.error(f"Erreur lors de la connexion au serveur Angel: {e}")
            await self.session.close()
            self.session = None
            self.running = False
            return
        
        # Démarrer la tâche de récupération des activités
        self.poll_task = asyncio.create_task(self._poll_activities())
        logger.info("Connecteur Angel Server démarré")
    
    async def stop(self):
        """Arrête le connecteur et ferme la session HTTP"""
        if not self.running:
            logger.warning("Le connecteur Angel Server n'est pas en cours d'exécution")
            return
        
        logger.info("Arrêt du connecteur Angel Server")
        self.running = False
        
        # Annuler la tâche de récupération des activités
        if self.poll_task and not self.poll_task.done():
            self.poll_task.cancel()
            try:
                await self.poll_task
            except asyncio.CancelledError:
                pass
        
        # Fermer la session HTTP
        if self.session:
            await self.session.close()
            self.session = None
        
        logger.info("Connecteur Angel Server arrêté")
    
    async def _check_server_connection(self):
        """
        Vérifie la connexion au serveur Angel
        
        Raises:
            Exception: Si la connexion échoue
        """
        if not self.session:
            raise Exception("Session HTTP non initialisée")
        
        try:
            headers = self._get_headers()
            async with self.session.get(f"{self.server_url}/api/status", headers=headers) as response:
                if response.status != 200:
                    raise Exception(f"Erreur de connexion au serveur Angel: {response.status}")
                
                data = await response.json()
                logger.info(f"Connexion au serveur Angel établie: {data.get('status', 'Inconnu')}")
        except aiohttp.ClientError as e:
            raise Exception(f"Erreur de connexion au serveur Angel: {e}")
    
    async def _poll_activities(self):
        """
        Récupère périodiquement les activités du serveur Angel
        """
        while self.running:
            try:
                activities = await self.get_recent_activities()
                
                if activities:
                    for activity in activities:
                        # Convertir l'activité en événement et le publier
                        event = self._activity_to_event(activity)
                        await self.event_manager.publish(event)
                        
                        # Mettre à jour l'ID de la dernière activité
                        if 'id' in activity:
                            self.last_activity_id = activity['id']
                
                # Attendre avant la prochaine récupération
                await asyncio.sleep(10)  # Polling toutes les 10 secondes
            
            except asyncio.CancelledError:
                logger.info("Récupération des activités annulée")
                break
            except Exception as e:
                logger.error(f"Erreur lors de la récupération des activités: {e}")
                await asyncio.sleep(30)  # Attendre plus longtemps en cas d'erreur
    
    async def get_recent_activities(self) -> List[Dict[str, Any]]:
        """
        Récupère les activités récentes du serveur Angel
        
        Returns:
            List[Dict[str, Any]]: Liste des activités récentes
        """
        if not self.session:
            logger.error("Session HTTP non initialisée")
            return []
        
        try:
            headers = self._get_headers()
            params = {}
            
            if self.last_activity_id:
                params['since_id'] = self.last_activity_id
            
            async with self.session.get(
                f"{self.server_url}/api/activities",
                headers=headers,
                params=params
            ) as response:
                if response.status != 200:
                    logger.error(f"Erreur lors de la récupération des activités: {response.status}")
                    return []
                
                data = await response.json()
                return data.get('activities', [])
        
        except aiohttp.ClientError as e:
            logger.error(f"Erreur lors de la récupération des activités: {e}")
            return []
        except Exception as e:
            logger.error(f"Erreur inattendue lors de la récupération des activités: {e}")
            return []
    
    async def propose_activity(self, activity_type: str, description: str, 
                              priority: EventPriority = EventPriority.MEDIUM,
                              metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Propose une activité à l'utilisateur via le serveur Angel
        
        Args:
            activity_type (str): Type d'activité à proposer
            description (str): Description de l'activité
            priority (EventPriority, optional): Priorité de l'activité. Defaults to EventPriority.MEDIUM.
            metadata (Optional[Dict[str, Any]], optional): Métadonnées supplémentaires. Defaults to None.
            
        Returns:
            bool: True si l'activité a été proposée avec succès, False sinon
        """
        if not self.session:
            logger.error("Session HTTP non initialisée")
            return False
        
        try:
            headers = self._get_headers()
            
            # Préparer les données de l'activité
            payload = {
                "activity_type": activity_type,
                "description": description,
                "priority": priority.name,
                "timestamp": datetime.now().isoformat(),
                "metadata": metadata or {}
            }
            
            # Envoyer la proposition d'activité
            async with self.session.post(
                f"{self.server_url}/api/propose_activity",
                headers=headers,
                json=payload
            ) as response:
                if response.status != 200 and response.status != 201:
                    logger.error(f"Erreur lors de la proposition d'activité: {response.status}")
                    return False
                
                data = await response.json()
                logger.info(f"Activité proposée avec succès: {activity_type}")
                return True
        
        except aiohttp.ClientError as e:
            logger.error(f"Erreur lors de la proposition d'activité: {e}")
            return False
        except Exception as e:
            logger.error(f"Erreur inattendue lors de la proposition d'activité: {e}")
            return False
    
    async def get_user_context(self) -> Dict[str, Any]:
        """
        Récupère le contexte utilisateur actuel du serveur Angel
        
        Returns:
            Dict[str, Any]: Contexte utilisateur
        """
        if not self.session:
            logger.error("Session HTTP non initialisée")
            return {}
        
        try:
            headers = self._get_headers()
            
            async with self.session.get(
                f"{self.server_url}/api/user_context",
                headers=headers
            ) as response:
                if response.status != 200:
                    logger.error(f"Erreur lors de la récupération du contexte utilisateur: {response.status}")
                    return {}
                
                data = await response.json()
                return data.get('context', {})
        
        except aiohttp.ClientError as e:
            logger.error(f"Erreur lors de la récupération du contexte utilisateur: {e}")
            return {}
        except Exception as e:
            logger.error(f"Erreur inattendue lors de la récupération du contexte utilisateur: {e}")
            return {}
    
    def _get_headers(self) -> Dict[str, str]:
        """
        Construit les en-têtes HTTP pour les requêtes API
        
        Returns:
            Dict[str, str]: En-têtes HTTP
        """
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        return headers
    
    def _activity_to_event(self, activity: Dict[str, Any]) -> Event:
        """
        Convertit une activité du serveur Angel en événement interne
        
        Args:
            activity (Dict[str, Any]): Activité provenant du serveur Angel
            
        Returns:
            Event: Événement interne
        """
        # Déterminer la priorité en fonction du niveau d'importance de l'activité
        importance = activity.get('importance', 0)
        priority = EventPriority.LOW
        
        if importance >= 80:
            priority = EventPriority.HIGH
        elif importance >= 40:
            priority = EventPriority.MEDIUM
        
        # Créer l'événement
        return Event(
            event_type=EventType.USER_ACTIVITY,
            priority=priority,
            source="angel_server",
            timestamp=datetime.fromisoformat(activity.get('timestamp', datetime.now().isoformat())),
            data=activity
        )
