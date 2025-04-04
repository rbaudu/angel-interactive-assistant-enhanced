#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Gestionnaire d'événements centralisé pour l'application.
Permet aux différents composants de publier et de s'abonner à des événements.
"""

import asyncio
import logging
from typing import Dict, Callable, List, Set, Any, Coroutine, Optional
from datetime import datetime, timedelta
from collections import defaultdict, deque

from events.event_types import Event, EventType, EventPriority

logger = logging.getLogger("angel.events")

class EventManager:
    """
    Gestionnaire d'événements central qui permet aux composants
    de s'abonner et de publier des événements.
    """
    
    def __init__(self, max_history: int = 100):
        """
        Initialise le gestionnaire d'événements
        
        Args:
            max_history (int, optional): Nombre maximum d'événements à conserver dans l'historique.
                Defaults to 100.
        """
        # Callbacks par type d'événement
        self._subscribers: Dict[EventType, List[Callable]] = defaultdict(list)
        
        # Callbacks par priorité d'événement
        self._priority_subscribers: Dict[EventPriority, List[Callable]] = defaultdict(list)
        
        # Historique des événements
        self._history = deque(maxlen=max_history)
        
        # État du gestionnaire
        self._running = False
        
        # File d'attente d'événements
        self._queue = asyncio.Queue()
        
        # Éventuelles tâches de traitement
        self._tasks = []
        
        logger.info("Gestionnaire d'événements initialisé")
    
    async def start(self):
        """Démarre le gestionnaire d'événements"""
        if self._running:
            logger.warning("Le gestionnaire d'événements est déjà en cours d'exécution")
            return
        
        self._running = True
        self._tasks.append(asyncio.create_task(self._event_processor()))
        logger.info("Gestionnaire d'événements démarré")
    
    async def stop(self):
        """Arrête le gestionnaire d'événements"""
        if not self._running:
            logger.warning("Le gestionnaire d'événements n'est pas en cours d'exécution")
            return
        
        self._running = False
        
        # Annuler toutes les tâches en cours
        for task in self._tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        self._tasks = []
        logger.info("Gestionnaire d'événements arrêté")
    
    def subscribe(self, event_type: EventType, callback: Callable[[Event], Any]) -> None:
        """
        S'abonne à un type d'événement spécifique
        
        Args:
            event_type (EventType): Type d'événement auquel s'abonner
            callback (Callable[[Event], Any]): Fonction à appeler lorsque l'événement se produit
        """
        self._subscribers[event_type].append(callback)
        logger.debug(f"Abonnement au type d'événement: {event_type.name}")
    
    def subscribe_to_priority(self, priority: EventPriority, callback: Callable[[Event], Any]) -> None:
        """
        S'abonne à tous les événements d'une priorité spécifique
        
        Args:
            priority (EventPriority): Priorité d'événements à laquelle s'abonner
            callback (Callable[[Event], Any]): Fonction à appeler lorsque l'événement se produit
        """
        self._priority_subscribers[priority].append(callback)
        logger.debug(f"Abonnement à la priorité d'événement: {priority.name}")
    
    def unsubscribe(self, event_type: EventType, callback: Callable[[Event], Any]) -> None:
        """
        Se désabonne d'un type d'événement
        
        Args:
            event_type (EventType): Type d'événement dont se désabonner
            callback (Callable[[Event], Any]): Fonction à retirer des abonnés
        """
        if event_type in self._subscribers:
            try:
                self._subscribers[event_type].remove(callback)
                logger.debug(f"Désabonnement du type d'événement: {event_type.name}")
            except ValueError:
                logger.warning(f"Tentative de désabonnement d'une fonction non abonnée pour {event_type.name}")
    
    def unsubscribe_from_priority(self, priority: EventPriority, callback: Callable[[Event], Any]) -> None:
        """
        Se désabonne d'une priorité d'événements
        
        Args:
            priority (EventPriority): Priorité d'événements dont se désabonner
            callback (Callable[[Event], Any]): Fonction à retirer des abonnés
        """
        if priority in self._priority_subscribers:
            try:
                self._priority_subscribers[priority].remove(callback)
                logger.debug(f"Désabonnement de la priorité d'événement: {priority.name}")
            except ValueError:
                logger.warning(f"Tentative de désabonnement d'une fonction non abonnée pour la priorité {priority.name}")
    
    async def publish(self, event: Event) -> None:
        """
        Publie un événement aux abonnés de manière asynchrone
        
        Args:
            event (Event): Événement à publier
        """
        await self._queue.put(event)
    
    def publish_sync(self, event: Event) -> None:
        """
        Publie un événement de manière synchrone (pour les contextes non-async)
        
        Args:
            event (Event): Événement à publier
        """
        # Utiliser asyncio.run_coroutine_threadsafe si nous sommes dans un thread différent
        # sinon, simplement mettre l'événement dans la file d'attente
        try:
            loop = asyncio.get_running_loop()
            asyncio.run_coroutine_threadsafe(self._queue.put(event), loop)
        except RuntimeError:
            # Pas de boucle asyncio en cours d'exécution
            # Créer une nouvelle boucle temporaire pour publier l'événement
            async def _publish():
                await self._queue.put(event)
            
            asyncio.run(_publish())
    
    async def _event_processor(self) -> None:
        """
        Traite les événements dans la file d'attente et les distribue aux abonnés
        """
        while self._running:
            try:
                # Attendre le prochain événement avec un timeout pour pouvoir vérifier
                # régulièrement si nous devons continuer à fonctionner
                try:
                    event = await asyncio.wait_for(self._queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                
                # Ajouter à l'historique
                self._history.append(event)
                
                # Notifier les abonnés par type d'événement
                if event.event_type in self._subscribers:
                    for callback in self._subscribers[event.event_type]:
                        try:
                            result = callback(event)
                            # Gérer les coroutines retournées
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception as e:
                            logger.error(f"Erreur lors de l'exécution du callback pour {event.event_type.name}: {e}")
                
                # Notifier les abonnés par priorité
                if event.priority in self._priority_subscribers:
                    for callback in self._priority_subscribers[event.priority]:
                        try:
                            result = callback(event)
                            # Gérer les coroutines retournées
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception as e:
                            logger.error(f"Erreur lors de l'exécution du callback pour priorité {event.priority.name}: {e}")
                
                # Marquer l'événement comme traité
                self._queue.task_done()
                
                logger.debug(f"Événement traité: {event.event_type.name} ({event.priority.name})")
            
            except asyncio.CancelledError:
                logger.info("Traitement des événements annulé")
                break
            except Exception as e:
                logger.error(f"Erreur dans le processeur d'événements: {e}")
    
    def get_history(self, event_type: Optional[EventType] = None, 
                   since: Optional[datetime] = None,
                   limit: int = 50) -> List[Event]:
        """
        Récupère l'historique des événements avec filtrage optionnel
        
        Args:
            event_type (Optional[EventType], optional): Type d'événement à filtrer. Defaults to None.
            since (Optional[datetime], optional): Timestamp minimum. Defaults to None.
            limit (int, optional): Nombre maximum d'événements à retourner. Defaults to 50.
            
        Returns:
            List[Event]: Liste des événements correspondant aux critères
        """
        result = []
        count = 0
        
        # Parcourir l'historique du plus récent au plus ancien
        for event in reversed(self._history):
            # Appliquer les filtres
            if event_type is not None and event.event_type != event_type:
                continue
                
            if since is not None and event.timestamp < since:
                continue
                
            result.append(event)
            count += 1
            
            if count >= limit:
                break
                
        return result
