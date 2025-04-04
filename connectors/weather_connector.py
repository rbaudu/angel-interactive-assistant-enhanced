#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Connecteur pour le service météo.
Permet de récupérer les prévisions météo actuelles et futures.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

import aiohttp
import pyowm
from pyowm.weatherapi25.weather import Weather

from events.event_manager import EventManager
from events.event_types import Event, EventType, EventPriority, IntrusiveEvents

logger = logging.getLogger("angel.connectors.weather")

class WeatherConnector:
    """
    Connecteur pour les services météorologiques.
    Permet de récupérer les données météo et d'envoyer des alertes.
    """
    
    def __init__(self, api_key: str, location: str, event_manager: EventManager):
        """
        Initialise le connecteur météo
        
        Args:
            api_key (str): Clé API pour le service météo
            location (str): Emplacement par défaut (ex: "Paris,FR")
            event_manager (EventManager): Gestionnaire d'événements
        """
        self.api_key = api_key
        self.location = location
        self.event_manager = event_manager
        self.owm = None if not api_key else pyowm.OWM(api_key)
        self.running = False
        self.update_task = None
        self.last_weather = None
        
        logger.info(f"Connecteur météo initialisé pour l'emplacement: {self.location}")
    
    async def start(self):
        """Démarre le connecteur météo"""
        if self.running:
            logger.warning("Le connecteur météo est déjà en cours d'exécution")
            return
        
        if not self.api_key or not self.owm:
            logger.error("Impossible de démarrer le connecteur météo: clé API manquante")
            return
        
        logger.info("Démarrage du connecteur météo")
        self.running = True
        
        # Effectuer une première mise à jour immédiate
        try:
            weather = await self.get_current_weather()
            if weather:
                self.last_weather = weather
                await self._publish_weather_update(weather)
        except Exception as e:
            logger.error(f"Erreur lors de la récupération initiale de la météo: {e}")
        
        # Démarrer la tâche de mise à jour périodique
        self.update_task = asyncio.create_task(self._periodic_update())
        logger.info("Connecteur météo démarré")
    
    async def stop(self):
        """Arrête le connecteur météo"""
        if not self.running:
            logger.warning("Le connecteur météo n'est pas en cours d'exécution")
            return
        
        logger.info("Arrêt du connecteur météo")
        self.running = False
        
        # Annuler la tâche de mise à jour périodique
        if self.update_task and not self.update_task.done():
            self.update_task.cancel()
            try:
                await self.update_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Connecteur météo arrêté")
    
    async def _periodic_update(self):
        """
        Effectue des mises à jour périodiques de la météo
        """
        # Mettre à jour toutes les heures
        update_interval = 3600  # 1 heure en secondes
        
        while self.running:
            try:
                # Attendre avant la prochaine mise à jour
                await asyncio.sleep(update_interval)
                
                # Récupérer la météo actuelle
                weather = await self.get_current_weather()
                if weather:
                    old_weather = self.last_weather
                    self.last_weather = weather
                    
                    # Publier la mise à jour météo
                    await self._publish_weather_update(weather)
                    
                    # Vérifier s'il y a des conditions météo importantes à signaler
                    if old_weather:
                        await self._check_weather_changes(old_weather, weather)
            
            except asyncio.CancelledError:
                logger.info("Mise à jour météo périodique annulée")
                break
            except Exception as e:
                logger.error(f"Erreur lors de la mise à jour météo: {e}")
                await asyncio.sleep(300)  # Attendre 5 minutes en cas d'erreur
    
    async def get_current_weather(self) -> Optional[Dict[str, Any]]:
        """
        Récupère la météo actuelle
        
        Returns:
            Optional[Dict[str, Any]]: Données météo actuelles
        """
        if not self.owm:
            logger.error("Service météo non initialisé")
            return None
        
        try:
            # Utiliser un thread pour éviter de bloquer la boucle asyncio
            loop = asyncio.get_running_loop()
            weather = await loop.run_in_executor(None, self._fetch_weather)
            
            if not weather:
                return None
            
            # Convertir l'objet Weather en dictionnaire
            return {
                'temperature': weather.temperature('celsius'),
                'status': weather.status,
                'detailed_status': weather.detailed_status,
                'wind': weather.wind(),
                'humidity': weather.humidity,
                'rain': weather.rain,
                'snow': weather.snow,
                'clouds': weather.clouds,
                'reference_time': weather.ref_time,
                'timestamp': datetime.now().isoformat()
            }
        
        except Exception as e:
            logger.error(f"Erreur lors de la récupération de la météo: {e}")
            return None
    
    def _fetch_weather(self) -> Optional[Weather]:
        """
        Récupère les données météo depuis l'API OWM (exécution synchrone)
        
        Returns:
            Optional[Weather]: Objet Weather ou None en cas d'erreur
        """
        try:
            mgr = self.owm.weather_manager()
            observation = mgr.weather_at_place(self.location)
            return observation.weather
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des données météo: {e}")
            return None
    
    async def get_forecast(self, days: int = 3) -> List[Dict[str, Any]]:
        """
        Récupère les prévisions météo pour les prochains jours
        
        Args:
            days (int, optional): Nombre de jours de prévision. Defaults to 3.
            
        Returns:
            List[Dict[str, Any]]: Prévisions météo
        """
        if not self.owm:
            logger.error("Service météo non initialisé")
            return []
        
        try:
            # Utiliser un thread pour éviter de bloquer la boucle asyncio
            loop = asyncio.get_running_loop()
            forecast = await loop.run_in_executor(None, lambda: self._fetch_forecast(days))
            
            # Convertir les prévisions en format utilisable
            result = []
            for item in forecast:
                result.append({
                    'temperature': item.temperature('celsius'),
                    'status': item.status,
                    'detailed_status': item.detailed_status,
                    'wind': item.wind(),
                    'humidity': item.humidity,
                    'rain': item.rain,
                    'snow': item.snow,
                    'clouds': item.clouds,
                    'reference_time': item.ref_time,
                    'timestamp': datetime.fromtimestamp(item.ref_time).isoformat()
                })
            
            return result
        
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des prévisions: {e}")
            return []
    
    def _fetch_forecast(self, days: int) -> List[Weather]:
        """
        Récupère les prévisions météo depuis l'API OWM (exécution synchrone)
        
        Args:
            days (int): Nombre de jours de prévision
            
        Returns:
            List[Weather]: Liste d'objets Weather
        """
        try:
            mgr = self.owm.weather_manager()
            forecaster = mgr.forecast_at_place(self.location, '3h')
            forecast = forecaster.forecast
            
            # Limiter les prévisions à la période demandée
            limit_time = datetime.now() + timedelta(days=days)
            limit_timestamp = limit_time.timestamp()
            
            # Extraire les prévisions
            result = []
            for weather in forecast:
                if weather.ref_time <= limit_timestamp:
                    result.append(weather)
            
            return result
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des prévisions météo: {e}")
            return []
    
    async def check_weather_alerts(self) -> List[Dict[str, Any]]:
        """
        Vérifie s'il y a des alertes météo pour l'emplacement actuel
        
        Returns:
            List[Dict[str, Any]]: Liste des alertes météo
        """
        if not self.owm:
            logger.error("Service météo non initialisé")
            return []
        
        try:
            # Utiliser un thread pour éviter de bloquer la boucle asyncio
            loop = asyncio.get_running_loop()
            alerts = await loop.run_in_executor(None, self._fetch_alerts)
            
            return alerts
        
        except Exception as e:
            logger.error(f"Erreur lors de la vérification des alertes météo: {e}")
            return []
    
    def _fetch_alerts(self) -> List[Dict[str, Any]]:
        """
        Récupère les alertes météo depuis l'API OWM (exécution synchrone)
        
        Returns:
            List[Dict[str, Any]]: Liste des alertes météo
        """
        try:
            mgr = self.owm.weather_manager()
            # Extraire la latitude et longitude depuis le nom de l'emplacement
            reg = self.owm.city_id_registry()
            locations = reg.locations_for(self.location.split(',')[0], country=self.location.split(',')[1] if ',' in self.location else None)
            
            if not locations:
                logger.error(f"Emplacement non trouvé: {self.location}")
                return []
            
            lat, lon = locations[0].lat, locations[0].lon
            
            # Récupérer les alertes
            alerts = mgr.weather_alerts_manager().get_alerts((lon, lat))
            
            # Formater les alertes
            result = []
            for alert in alerts.alerts:
                result.append({
                    'sender': alert.sender_name,
                    'event': alert.type,
                    'description': alert.description,
                    'start': datetime.fromtimestamp(alert.start).isoformat(),
                    'end': datetime.fromtimestamp(alert.end).isoformat(),
                    'severity': self._get_alert_severity(alert.type)
                })
            
            return result
        
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des alertes météo: {e}")
            return []
    
    def _get_alert_severity(self, alert_type: str) -> int:
        """
        Détermine la gravité d'une alerte météo
        
        Args:
            alert_type (str): Type d'alerte
            
        Returns:
            int: Niveau de gravité (1-3)
        """
        # Alertes de haute gravité
        high_severity = ["TORNADO", "HURRICANE", "TSUNAMI", "EARTHQUAKE", "FLOOD", "THUNDERSTORM"]
        
        # Alertes de gravité moyenne
        medium_severity = ["RAIN", "WIND", "SNOW", "FOG", "EXTREME_TEMPERATURE", "COASTAL"]
        
        # Normaliser le type d'alerte
        normalized_type = alert_type.upper().strip()
        
        # Vérifier la gravité
        for alert in high_severity:
            if alert in normalized_type:
                return 3
        
        for alert in medium_severity:
            if alert in normalized_type:
                return 2
        
        # Par défaut, gravité faible
        return 1
    
    async def _publish_weather_update(self, weather: Dict[str, Any]):
        """
        Publie une mise à jour météo
        
        Args:
            weather (Dict[str, Any]): Données météo
        """
        # Créer un événement de mise à jour météo
        event = Event(
            event_type=EventType.WEATHER_UPDATE,
            priority=EventPriority.LOW,
            source="weather_service",
            data=weather
        )
        
        # Publier l'événement
        await self.event_manager.publish(event)
        logger.debug(f"Mise à jour météo publiée: {weather['status']}")
    
    async def _check_weather_changes(self, old_weather: Dict[str, Any], new_weather: Dict[str, Any]):
        """
        Vérifie s'il y a des changements importants dans la météo
        
        Args:
            old_weather (Dict[str, Any]): Ancienne météo
            new_weather (Dict[str, Any]): Nouvelle météo
        """
        # Vérifier les changements de conditions météorologiques
        old_status = old_weather['detailed_status'].lower()
        new_status = new_weather['detailed_status'].lower()
        
        # Déterminer si un changement important s'est produit
        important_change = False
        alert_type = None
        description = None
        severity = 1
        
        # Changements liés à la pluie
        if ('rain' in new_status or 'shower' in new_status) and not ('rain' in old_status or 'shower' in old_status):
            important_change = True
            alert_type = "RAIN_STARTING"
            description = "La pluie va commencer prochainement"
        
        # Changements liés à la neige
        elif 'snow' in new_status and not 'snow' in old_status:
            important_change = True
            alert_type = "SNOW_STARTING"
            description = "De la neige est prévue prochainement"
            severity = 2
        
        # Changements liés aux orages
        elif ('thunder' in new_status or 'storm' in new_status) and not ('thunder' in old_status or 'storm' in old_status):
            important_change = True
            alert_type = "THUNDERSTORM_STARTING"
            description = "Des orages sont prévus prochainement"
            severity = 2
        
        # Changements de température importants
        old_temp = old_weather['temperature']['temp']
        new_temp = new_weather['temperature']['temp']
        
        if abs(new_temp - old_temp) > 10:  # Changement de plus de 10°C
            important_change = True
            if new_temp > old_temp:
                alert_type = "TEMPERATURE_RISE"
                description = f"Augmentation importante de la température: {int(old_temp)}°C → {int(new_temp)}°C"
            else:
                alert_type = "TEMPERATURE_DROP"
                description = f"Baisse importante de la température: {int(old_temp)}°C → {int(new_temp)}°C"
            
            severity = 2 if abs(new_temp - old_temp) > 15 else 1
        
        # Si un changement important est détecté, envoyer une alerte
        if important_change and alert_type and description:
            # Créer un événement d'alerte météo
            event = IntrusiveEvents.weather_alert(alert_type, description, severity)
            
            # Publier l'événement
            await self.event_manager.publish(event)
            logger.info(f"Alerte météo publiée: {alert_type} - {description}")
