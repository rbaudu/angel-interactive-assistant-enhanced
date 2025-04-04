#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Module de configuration pour l'assistant Angel.
Centralise tous les paramètres configurables de l'application.
"""

import os
import json
import logging
from pathlib import Path
from dotenv import load_dotenv

# Chargement des variables d'environnement depuis .env s'il existe
load_dotenv()

logger = logging.getLogger("angel.config")

class Settings:
    """Classe qui contient tous les paramètres de configuration"""
    
    def __init__(self, config_file=None):
        """
        Initialise la configuration
        
        Args:
            config_file (str, optional): Chemin vers un fichier de configuration personnalisé
        """
        # Chemins de base
        self.base_dir = Path(__file__).parent.parent
        self.config_dir = self.base_dir / "config"
        
        # Fichier de configuration (par défaut ou personnalisé)
        self.config_file = config_file or os.environ.get("ANGEL_CONFIG", str(self.config_dir / "default_settings.json"))
        self._load_config()
        
        # SECTION SERVER
        self.host = self.config.get("server", {}).get("host", "127.0.0.1")
        self.port = int(self.config.get("server", {}).get("port", 8000))
        self.debug = self.config.get("server", {}).get("debug", False)
        
        # SECTION AVATAR
        self.avatar_enabled = self.config.get("avatar", {}).get("enabled", True)
        self.avatar_position = self.config.get("avatar", {}).get("position", "bottom-right")
        self.avatar_size = self.config.get("avatar", {}).get("size", "medium")
        
        # SECTION ANGEL-SERVER-CAPTURE
        self.angel_server_url = self.config.get("angel_server_capture", {}).get("url", "http://localhost:5000")
        self.angel_server_key = self.config.get("angel_server_capture", {}).get("api_key", None)
        self.polling_interval = int(self.config.get("angel_server_capture", {}).get("polling_interval", 10))
        
        # SECTION PRIORITIES
        self.high_priority_duration = int(self.config.get("priorities", {}).get("high_priority_duration", 60))
        self.medium_priority_duration = int(self.config.get("priorities", {}).get("medium_priority_duration", 300))
        self.priority_thresholds = self.config.get("priorities", {}).get("thresholds", {
            "high": 80,
            "medium": 50,
            "low": 20
        })
        
        # SECTION RECOMMENDATIONS
        self.medication_times = self.config.get("recommendations", {}).get("medication_times", ["08:00", "12:00", "18:00", "22:00"])
        self.meal_times = self.config.get("recommendations", {}).get("meal_times", ["07:30", "12:30", "19:00"])
        self.weather_check_times = self.config.get("recommendations", {}).get("weather_check_times", ["07:00", "12:00", "18:00"])
        
        # SECTION WEATHER
        self.weather_api_key = self.config.get("weather", {}).get("api_key", os.getenv("WEATHER_API_KEY", ""))
        self.weather_location = self.config.get("weather", {}).get("location", "Paris,FR")
        
        # SECTION NOTIFICATIONS
        self.enable_desktop_notifications = self.config.get("notifications", {}).get("enable_desktop", True)
        self.notification_sound = self.config.get("notifications", {}).get("sound", True)
        self.notification_duration = int(self.config.get("notifications", {}).get("duration", 10))
        
        # SECTION INTRUSIVE_EVENTS
        self.intrusive_events = self.config.get("intrusive_events", {
            "whatsapp_call": True,
            "phone_call": True,
            "urgent_email": True,
            "weather_alert": True,
            "sms": True
        })
        
        # Validation
        self._validate_settings()
    
    def _load_config(self):
        """Charge la configuration depuis un fichier JSON"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                    logger.info(f"Configuration chargée depuis {self.config_file}")
            else:
                logger.warning(f"Fichier de configuration {self.config_file} non trouvé, utilisation des valeurs par défaut")
                self.config = {}
        except Exception as e:
            logger.error(f"Erreur lors du chargement de la configuration: {e}")
            self.config = {}
    
    def _validate_settings(self):
        """Valide les paramètres de configuration"""
        # Vérification de base pour s'assurer que les paramètres obligatoires sont présents
        if not self.angel_server_url:
            logger.warning("URL du serveur Angel non configurée")
        
        if not self.weather_api_key and any([self.intrusive_events.get("weather_alert"), len(self.weather_check_times) > 0]):
            logger.warning("Clé API météo non configurée mais fonctionnalités météo activées")
    
    def save(self, config_file=None):
        """
        Sauvegarde la configuration actuelle dans un fichier
        
        Args:
            config_file (str, optional): Chemin vers le fichier de destination
        """
        save_path = config_file or self.config_file
        
        # Mise à jour de la configuration avec les valeurs actuelles
        config = {
            "server": {
                "host": self.host,
                "port": self.port,
                "debug": self.debug
            },
            "avatar": {
                "enabled": self.avatar_enabled,
                "position": self.avatar_position,
                "size": self.avatar_size
            },
            "angel_server_capture": {
                "url": self.angel_server_url,
                "api_key": self.angel_server_key,
                "polling_interval": self.polling_interval
            },
            "priorities": {
                "high_priority_duration": self.high_priority_duration,
                "medium_priority_duration": self.medium_priority_duration,
                "thresholds": self.priority_thresholds
            },
            "recommendations": {
                "medication_times": self.medication_times,
                "meal_times": self.meal_times,
                "weather_check_times": self.weather_check_times
            },
            "weather": {
                "api_key": self.weather_api_key,
                "location": self.weather_location
            },
            "notifications": {
                "enable_desktop": self.enable_desktop_notifications,
                "sound": self.notification_sound,
                "duration": self.notification_duration
            },
            "intrusive_events": self.intrusive_events
        }
        
        try:
            # Créer le répertoire parent si nécessaire
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4)
            
            logger.info(f"Configuration sauvegardée dans {save_path}")
            return True
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde de la configuration: {e}")
            return False
