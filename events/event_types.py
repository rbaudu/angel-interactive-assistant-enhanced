#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Définition des types d'événements utilisés dans l'application.
"""

from enum import Enum, auto
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime

class EventType(Enum):
    """Types d'événements gérés par l'application"""
    # Événements de l'utilisateur et du système
    USER_ACTIVITY = auto()         # Activité détectée par angel-server-capture
    SYSTEM_STATUS = auto()         # État du système (démarrage, arrêt, etc.)
    
    # Événements de communication
    WHATSAPP_CALL = auto()         # Appel WhatsApp entrant
    PHONE_CALL = auto()            # Appel téléphonique entrant
    SMS_RECEIVED = auto()          # SMS reçu
    EMAIL_RECEIVED = auto()        # Email reçu
    
    # Événements liés à l'environnement
    WEATHER_UPDATE = auto()        # Mise à jour météo
    WEATHER_ALERT = auto()         # Alerte météo importante
    
    # Événements liés aux recommandations
    MEDICATION_REMINDER = auto()   # Rappel de prise de médicament
    MEAL_REMINDER = auto()         # Rappel de repas
    ACTIVITY_SUGGESTION = auto()   # Suggestion d'activité
    
    # Événements de contrôle
    UI_INTERACTION = auto()        # Interaction avec l'interface utilisateur
    AVATAR_STATE_CHANGE = auto()   # Changement d'état de l'avatar
    
    # Événements personnalisés
    CUSTOM = auto()                # Événement personnalisé


class EventPriority(Enum):
    """Priorités pour les événements"""
    LOW = 0      # Basse priorité (suggestions, informations)
    MEDIUM = 1   # Priorité moyenne (rappels, recommandations)
    HIGH = 2     # Haute priorité (alertes, appels)
    CRITICAL = 3 # Priorité critique (urgences)


@dataclass
class Event:
    """
    Classe représentant un événement dans le système
    """
    event_type: EventType
    priority: EventPriority
    source: str
    timestamp: datetime = None
    data: Dict[str, Any] = None
    id: str = None
    
    def __post_init__(self):
        """Initialisation automatique des champs manquants"""
        if self.timestamp is None:
            self.timestamp = datetime.now()
        
        if self.data is None:
            self.data = {}
        
        if self.id is None:
            # Générer un ID unique basé sur le timestamp et le type
            self.id = f"{self.event_type.name}_{int(self.timestamp.timestamp())}"
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convertit l'événement en dictionnaire pour la sérialisation
        
        Returns:
            Dict[str, Any]: Représentation de l'événement sous forme de dictionnaire
        """
        return {
            "id": self.id,
            "event_type": self.event_type.name,
            "priority": self.priority.name,
            "source": self.source,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Event':
        """
        Crée un événement à partir d'un dictionnaire
        
        Args:
            data (Dict[str, Any]): Dictionnaire contenant les données de l'événement
            
        Returns:
            Event: Instance de l'événement
        """
        return cls(
            event_type=EventType[data["event_type"]],
            priority=EventPriority[data["priority"]],
            source=data["source"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            data=data.get("data", {}),
            id=data.get("id")
        )


# Définition d'événements intrusifs spécifiques
class IntrusiveEvents:
    """Classe utilitaire pour créer des événements intrusifs"""
    
    @staticmethod
    def whatsapp_call(caller: str, video: bool = False) -> Event:
        """
        Crée un événement d'appel WhatsApp
        
        Args:
            caller (str): Nom ou numéro de l'appelant
            video (bool, optional): Indique si c'est un appel vidéo. Defaults to False.
            
        Returns:
            Event: Événement d'appel WhatsApp
        """
        return Event(
            event_type=EventType.WHATSAPP_CALL,
            priority=EventPriority.HIGH,
            source="whatsapp",
            data={
                "caller": caller,
                "video": video
            }
        )
    
    @staticmethod
    def phone_call(caller: str) -> Event:
        """
        Crée un événement d'appel téléphonique
        
        Args:
            caller (str): Nom ou numéro de l'appelant
            
        Returns:
            Event: Événement d'appel téléphonique
        """
        return Event(
            event_type=EventType.PHONE_CALL,
            priority=EventPriority.HIGH,
            source="phone",
            data={
                "caller": caller
            }
        )
    
    @staticmethod
    def sms_received(sender: str, message: str, urgent: bool = False) -> Event:
        """
        Crée un événement de SMS reçu
        
        Args:
            sender (str): Expéditeur du SMS
            message (str): Contenu du message
            urgent (bool, optional): Indique si le message est urgent. Defaults to False.
            
        Returns:
            Event: Événement de SMS reçu
        """
        return Event(
            event_type=EventType.SMS_RECEIVED,
            priority=EventPriority.HIGH if urgent else EventPriority.MEDIUM,
            source="sms",
            data={
                "sender": sender,
                "message": message,
                "urgent": urgent
            }
        )
    
    @staticmethod
    def email_received(sender: str, subject: str, urgent: bool = False) -> Event:
        """
        Crée un événement d'email reçu
        
        Args:
            sender (str): Expéditeur de l'email
            subject (str): Sujet de l'email
            urgent (bool, optional): Indique si l'email est urgent. Defaults to False.
            
        Returns:
            Event: Événement d'email reçu
        """
        return Event(
            event_type=EventType.EMAIL_RECEIVED,
            priority=EventPriority.HIGH if urgent else EventPriority.LOW,
            source="email",
            data={
                "sender": sender,
                "subject": subject,
                "urgent": urgent
            }
        )
    
    @staticmethod
    def weather_alert(alert_type: str, description: str, severity: int = 1) -> Event:
        """
        Crée un événement d'alerte météo
        
        Args:
            alert_type (str): Type d'alerte (tempête, inondation, etc.)
            description (str): Description de l'alerte
            severity (int, optional): Niveau de gravité (1-3). Defaults to 1.
            
        Returns:
            Event: Événement d'alerte météo
        """
        priority = EventPriority.MEDIUM
        if severity >= 3:
            priority = EventPriority.CRITICAL
        elif severity == 2:
            priority = EventPriority.HIGH
            
        return Event(
            event_type=EventType.WEATHER_ALERT,
            priority=priority,
            source="weather_service",
            data={
                "alert_type": alert_type,
                "description": description,
                "severity": severity
            }
        )
