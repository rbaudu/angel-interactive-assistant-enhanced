#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Serveur API pour les interactions externes avec l'assistant Angel.
"""

import asyncio
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple, Set, Union

import uvicorn
from fastapi import FastAPI, HTTPException, Depends, Query, Path, Body, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from config.settings import Settings
from events.event_manager import EventManager
from events.event_types import Event, EventType, EventPriority, IntrusiveEvents

logger = logging.getLogger("angel.api")

# Modèles de données pour l'API
class EventData(BaseModel):
    """Modèle pour les données d'événements"""
    event_type: str
    priority: str = "MEDIUM"
    source: str
    data: Dict[str, Any] = Field(default_factory=dict)
    
class ActivityData(BaseModel):
    """Modèle pour les données d'activité"""
    activity_type: str
    description: str
    priority: str = "MEDIUM"
    metadata: Dict[str, Any] = Field(default_factory=dict)

class NotificationData(BaseModel):
    """Modèle pour les notifications"""
    title: str
    message: str
    priority: str = "MEDIUM"
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ApiKeyAuth:
    """Classe pour la vérification de la clé API"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
    
    async def __call__(self, request: Request):
        if not self.api_key:
            return True
            
        api_key = request.headers.get("Authorization")
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key manquante"
            )
        
        if api_key != f"Bearer {self.api_key}":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key invalide"
            )
        
        return True

class ApiServer:
    """
    Serveur API pour interagir avec l'assistant Angel.
    """
    
    def __init__(self, host: str, port: int, event_manager: EventManager, settings: Settings):
        """
        Initialise le serveur API
        
        Args:
            host (str): Hôte sur lequel démarrer le serveur
            port (int): Port sur lequel démarrer le serveur
            event_manager (EventManager): Gestionnaire d'événements
            settings (Settings): Configuration de l'application
        """
        self.host = host
        self.port = port
        self.event_manager = event_manager
        self.settings = settings
        
        # Créer l'application FastAPI
        self.app = FastAPI(
            title="Angel Interactive Assistant API",
            description="API pour interagir avec l'assistant Angel",
            version="1.0.0"
        )
        
        # Middleware CORS
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        # Authentification API
        self.api_auth = ApiKeyAuth(settings.angel_server_key)
        
        # Définir les routes API
        self._setup_routes()
        
        # Serveur Uvicorn
        self.server = None
        
        logger.info(f"Serveur API initialisé sur {host}:{port}")
    
    def _setup_routes(self):
        """
        Configure les routes de l'API
        """
        
        @self.app.get("/api/status", tags=["Système"])
        async def get_status(auth: bool = Depends(self.api_auth)):
            """
            Obtient le statut actuel du système
            """
            return {
                "status": "running",
                "timestamp": datetime.now().isoformat(),
                "version": "1.0.0"
            }
        
        @self.app.post("/api/events", tags=["Événements"])
        async def create_event(event_data: EventData, auth: bool = Depends(self.api_auth)):
            """
            Crée un nouvel événement dans le système
            """
            try:
                # Vérifier le type d'événement
                try:
                    event_type = EventType[event_data.event_type.upper()]
                except KeyError:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Type d'événement non reconnu: {event_data.event_type}"
                    )
                
                # Vérifier la priorité
                try:
                    priority = EventPriority[event_data.priority.upper()]
                except KeyError:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Priorité non reconnue: {event_data.priority}"
                    )
                
                # Créer l'événement
                event = Event(
                    event_type=event_type,
                    priority=priority,
                    source=event_data.source,
                    data=event_data.data
                )
                
                # Publier l'événement
                await self.event_manager.publish(event)
                
                return {
                    "status": "success",
                    "event_id": event.id,
                    "timestamp": event.timestamp.isoformat()
                }
            
            except Exception as e:
                logger.error(f"Erreur lors de la création de l'événement: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Erreur lors de la création de l'événement: {str(e)}"
                )
        
        @self.app.get("/api/events", tags=["Événements"])
        async def get_events(
            event_type: Optional[str] = None,
            priority: Optional[str] = None,
            since: Optional[str] = None,
            limit: int = Query(50, ge=1, le=100),
            auth: bool = Depends(self.api_auth)
        ):
            """
            Récupère les événements du système avec des filtres optionnels
            """
            try:
                # Convertir les filtres si nécessaire
                event_type_filter = None
                if event_type:
                    try:
                        event_type_filter = EventType[event_type.upper()]
                    except KeyError:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Type d'événement non reconnu: {event_type}"
                        )
                
                # Convertir le timestamp depuis si fourni
                since_datetime = None
                if since:
                    try:
                        since_datetime = datetime.fromisoformat(since)
                    except ValueError:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Format de date invalide pour 'since': {since}"
                        )
                
                # Récupérer les événements
                events = self.event_manager.get_history(
                    event_type=event_type_filter,
                    since=since_datetime,
                    limit=limit
                )
                
                # Filtrer par priorité si demandé
                if priority:
                    try:
                        priority_filter = EventPriority[priority.upper()]
                        events = [e for e in events if e.priority == priority_filter]
                    except KeyError:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Priorité non reconnue: {priority}"
                        )
                
                # Convertir en dictionnaires pour la sortie JSON
                events_json = [event.to_dict() for event in events]
                
                return {
                    "events": events_json,
                    "count": len(events_json),
                    "timestamp": datetime.now().isoformat()
                }
            
            except Exception as e:
                logger.error(f"Erreur lors de la récupération des événements: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Erreur lors de la récupération des événements: {str(e)}"
                )
        
        @self.app.post("/api/activities/propose", tags=["Activités"])
        async def propose_activity(activity_data: ActivityData, auth: bool = Depends(self.api_auth)):
            """
            Propose une activité à l'utilisateur
            """
            try:
                # Déterminer la priorité
                try:
                    priority = EventPriority[activity_data.priority.upper()]
                except KeyError:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Priorité non reconnue: {activity_data.priority}"
                    )
                
                # Créer un événement de suggestion d'activité
                event = Event(
                    event_type=EventType.ACTIVITY_SUGGESTION,
                    priority=priority,
                    source="api",
                    data={
                        'recommendation_type': activity_data.activity_type,
                        'message': activity_data.description,
                        'metadata': activity_data.metadata
                    }
                )
                
                # Publier l'événement
                await self.event_manager.publish(event)
                
                return {
                    "status": "success",
                    "event_id": event.id,
                    "timestamp": event.timestamp.isoformat()
                }
            
            except Exception as e:
                logger.error(f"Erreur lors de la proposition d'activité: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Erreur lors de la proposition d'activité: {str(e)}"
                )
        
        @self.app.post("/api/notifications", tags=["Notifications"])
        async def send_notification(notification_data: NotificationData, auth: bool = Depends(self.api_auth)):
            """
            Envoie une notification à l'utilisateur
            """
            try:
                # Déterminer la priorité
                try:
                    priority = EventPriority[notification_data.priority.upper()]
                except KeyError:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Priorité non reconnue: {notification_data.priority}"
                    )
                
                # Créer un événement de notification
                event = Event(
                    event_type=EventType.UI_INTERACTION,
                    priority=priority,
                    source="api",
                    data={
                        'notification_type': 'message',
                        'title': notification_data.title,
                        'message': notification_data.message,
                        'metadata': notification_data.metadata
                    }
                )
                
                # Publier l'événement
                await self.event_manager.publish(event)
                
                return {
                    "status": "success",
                    "event_id": event.id,
                    "timestamp": event.timestamp.isoformat()
                }
            
            except Exception as e:
                logger.error(f"Erreur lors de l'envoi de la notification: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Erreur lors de l'envoi de la notification: {str(e)}"
                )
        
        @self.app.post("/api/events/intrusive/{event_type}", tags=["Événements intrusifs"])
        async def create_intrusive_event(
            event_type: str = Path(..., description="Type d'événement intrusif"),
            data: Dict[str, Any] = Body(..., description="Données de l'événement"),
            auth: bool = Depends(self.api_auth)
        ):
            """
            Crée un événement intrusif (appel, SMS, alerte météo, etc.)
            """
            try:
                # Déterminer le type d'événement intrusif
                event = None
                
                if event_type.lower() == "whatsapp_call":
                    event = IntrusiveEvents.whatsapp_call(
                        data.get("caller", "Inconnu"),
                        data.get("video", False)
                    )
                
                elif event_type.lower() == "phone_call":
                    event = IntrusiveEvents.phone_call(
                        data.get("caller", "Inconnu")
                    )
                
                elif event_type.lower() == "sms":
                    event = IntrusiveEvents.sms_received(
                        data.get("sender", "Inconnu"),
                        data.get("message", ""),
                        data.get("urgent", False)
                    )
                
                elif event_type.lower() == "email":
                    event = IntrusiveEvents.email_received(
                        data.get("sender", "Inconnu"),
                        data.get("subject", ""),
                        data.get("urgent", False)
                    )
                
                elif event_type.lower() == "weather_alert":
                    event = IntrusiveEvents.weather_alert(
                        data.get("alert_type", "Alerte météo"),
                        data.get("description", ""),
                        data.get("severity", 1)
                    )
                
                else:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Type d'événement intrusif non reconnu: {event_type}"
                    )
                
                # Publier l'événement
                await self.event_manager.publish(event)
                
                return {
                    "status": "success",
                    "event_id": event.id,
                    "timestamp": event.timestamp.isoformat()
                }
            
            except Exception as e:
                logger.error(f"Erreur lors de la création de l'événement intrusif: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Erreur lors de la création de l'événement intrusif: {str(e)}"
                )
        
        @self.app.get("/api/config", tags=["Configuration"])
        async def get_config(auth: bool = Depends(self.api_auth)):
            """
            Récupère la configuration actuelle de l'application
            """
            try:
                # Exclure les données sensibles
                config = {
                    "server": {
                        "host": self.settings.host,
                        "port": self.settings.port,
                        "debug": self.settings.debug
                    },
                    "avatar": {
                        "enabled": self.settings.avatar_enabled,
                        "position": self.settings.avatar_position,
                        "size": self.settings.avatar_size
                    },
                    "priorities": {
                        "high_priority_duration": self.settings.high_priority_duration,
                        "medium_priority_duration": self.settings.medium_priority_duration,
                        "thresholds": self.settings.priority_thresholds
                    },
                    "recommendations": {
                        "medication_times": self.settings.medication_times,
                        "meal_times": self.settings.meal_times,
                        "weather_check_times": self.settings.weather_check_times
                    },
                    "intrusive_events": self.settings.intrusive_events
                }
                
                return config
            
            except Exception as e:
                logger.error(f"Erreur lors de la récupération de la configuration: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Erreur lors de la récupération de la configuration: {str(e)}"
                )
    
    async def start(self):
        """
        Démarre le serveur API
        """
        # Créer et démarrer le serveur Uvicorn
        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.port,
            log_level="info" if not self.settings.debug else "debug"
        )
        
        self.server = uvicorn.Server(config)
        
        # Démarrer le serveur dans une tâche asyncio
        await self.server.serve()
    
    async def stop(self):
        """
        Arrête le serveur API
        """
        if self.server:
            self.server.should_exit = True
            logger.info("Serveur API arrêté")
