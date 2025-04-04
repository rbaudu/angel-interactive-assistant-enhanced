#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Moteur de recommandations qui analyse le contexte et propose des activités adaptées.
"""

import asyncio
import logging
import random
from datetime import datetime, time, timedelta
from typing import Dict, Any, List, Optional, Tuple, Set

from config.settings import Settings
from events.event_manager import EventManager
from events.event_types import Event, EventType, EventPriority
from connectors.angel_server_connector import AngelServerConnector

logger = logging.getLogger("angel.decision")

class RecommendationEngine:
    """
    Moteur de recommandations qui propose des activités adaptées au contexte.
    """
    
    def __init__(self, event_manager: EventManager, settings: Settings):
        """
        Initialise le moteur de recommandations
        
        Args:
            event_manager (EventManager): Gestionnaire d'événements
            settings (Settings): Configuration de l'application
        """
        self.event_manager = event_manager
        self.settings = settings
        self.running = False
        self.tasks = []
        
        # Contexte actuel
        self.current_context = {
            'activities': [],           # Activités récentes de l'utilisateur
            'weather': None,            # Météo actuelle
            'weather_forecast': None,   # Prévisions météo
            'time_of_day': None,        # Période de la journée (matin, midi, soir, nuit)
            'last_meal': None,          # Dernière heure de repas
            'last_medication': None,    # Dernière prise de médicament
            'last_recommendations': {}  # Dernières recommandations par type
        }
        
        # Périodes minimales entre deux recommandations du même type (en minutes)
        self.recommendation_intervals = {
            'medication': 60,  # 1 heure
            'meal': 120,       # 2 heures
            'activity': 60,    # 1 heure
            'weather': 180     # 3 heures
        }
        
        # S'abonner aux événements pertinents
        self.event_manager.subscribe(EventType.USER_ACTIVITY, self._handle_user_activity)
        self.event_manager.subscribe(EventType.WEATHER_UPDATE, self._handle_weather_update)
        self.event_manager.subscribe_to_priority(EventPriority.HIGH, self._handle_high_priority)
        
        # Variables pour le contrôle des tâches planifiées
        self.scheduled_tasks = {}
        
        logger.info("Moteur de recommandations initialisé")
    
    async def start(self):
        """Démarre le moteur de recommandations"""
        if self.running:
            logger.warning("Le moteur de recommandations est déjà en cours d'exécution")
            return
        
        logger.info("Démarrage du moteur de recommandations")
        self.running = True
        
        # Démarrer la tâche de mise à jour du contexte
        self.tasks.append(asyncio.create_task(self._update_context_periodically()))
        
        # Planifier les vérifications périodiques
        self.tasks.append(asyncio.create_task(self._schedule_periodic_checks()))
        
        logger.info("Moteur de recommandations démarré")
    
    async def stop(self):
        """Arrête le moteur de recommandations"""
        if not self.running:
            logger.warning("Le moteur de recommandations n'est pas en cours d'exécution")
            return
        
        logger.info("Arrêt du moteur de recommandations")
        self.running = False
        
        # Annuler toutes les tâches en cours
        for task in self.tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # Annuler les tâches planifiées
        for task_name, task in self.scheduled_tasks.items():
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        self.tasks = []
        self.scheduled_tasks = {}
        
        logger.info("Moteur de recommandations arrêté")
    
    async def _update_context_periodically(self):
        """
        Met à jour périodiquement le contexte avec les données les plus récentes
        """
        while self.running:
            try:
                # Mettre à jour le contexte
                now = datetime.now()
                
                # Définir la période de la journée
                hour = now.hour
                if 5 <= hour < 12:
                    self.current_context['time_of_day'] = 'morning'
                elif 12 <= hour < 14:
                    self.current_context['time_of_day'] = 'noon'
                elif 14 <= hour < 18:
                    self.current_context['time_of_day'] = 'afternoon'
                elif 18 <= hour < 22:
                    self.current_context['time_of_day'] = 'evening'
                else:
                    self.current_context['time_of_day'] = 'night'
                
                # Nettoyer les activités trop anciennes (> 24h)
                cutoff_time = now - timedelta(hours=24)
                self.current_context['activities'] = [
                    activity for activity in self.current_context['activities']
                    if datetime.fromisoformat(activity.get('timestamp', now.isoformat())) > cutoff_time
                ]
                
                # Attendre avant la prochaine mise à jour (toutes les 5 minutes)
                await asyncio.sleep(300)
            
            except asyncio.CancelledError:
                logger.info("Mise à jour du contexte annulée")
                break
            except Exception as e:
                logger.error(f"Erreur lors de la mise à jour du contexte: {e}")
                await asyncio.sleep(60)  # Attendre 1 minute en cas d'erreur
    
    async def _schedule_periodic_checks(self):
        """
        Planifie les vérifications périodiques pour les différentes recommandations
        """
        try:
            # Planifier les vérifications de médicaments
            for med_time_str in self.settings.medication_times:
                med_hour, med_minute = map(int, med_time_str.split(':'))
                self._schedule_daily_task(
                    f"medication_{med_time_str}",
                    time(med_hour, med_minute),
                    self._check_medication_time
                )
            
            # Planifier les vérifications de repas
            for meal_time_str in self.settings.meal_times:
                meal_hour, meal_minute = map(int, meal_time_str.split(':'))
                self._schedule_daily_task(
                    f"meal_{meal_time_str}",
                    time(meal_hour, meal_minute),
                    self._check_meal_time
                )
            
            # Planifier les vérifications météo
            for weather_time_str in self.settings.weather_check_times:
                weather_hour, weather_minute = map(int, weather_time_str.split(':'))
                self._schedule_daily_task(
                    f"weather_{weather_time_str}",
                    time(weather_hour, weather_minute),
                    self._check_weather_conditions
                )
            
            # Attendre indéfiniment (les tâches sont planifiées de manière asynchrone)
            while self.running:
                await asyncio.sleep(60)  # Vérifier périodiquement si nous devons nous arrêter
        
        except asyncio.CancelledError:
            logger.info("Planification des vérifications annulée")
        except Exception as e:
            logger.error(f"Erreur lors de la planification des vérifications: {e}")
    
    def _schedule_daily_task(self, task_name: str, target_time: time, callback: callable):
        """
        Planifie une tâche quotidienne à une heure précise
        
        Args:
            task_name (str): Nom de la tâche (pour le suivi)
            target_time (time): Heure d'exécution
            callback (callable): Fonction à appeler
        """
        async def _schedule_and_run():
            while self.running:
                now = datetime.now()
                target = datetime.combine(now.date(), target_time)
                
                # Si l'heure cible est déjà passée aujourd'hui, programmer pour demain
                if target < now:
                    target = datetime.combine(now.date() + timedelta(days=1), target_time)
                
                # Calculer le délai d'attente
                wait_seconds = (target - now).total_seconds()
                logger.debug(f"Tâche {task_name} planifiée dans {wait_seconds} secondes")
                
                # Attendre jusqu'à l'heure cible
                await asyncio.sleep(wait_seconds)
                
                if not self.running:
                    break
                
                # Exécuter la tâche
                try:
                    await callback()
                    logger.info(f"Tâche {task_name} exécutée avec succès")
                except Exception as e:
                    logger.error(f"Erreur lors de l'exécution de la tâche {task_name}: {e}")
                
                # Attendre un peu avant de reprogrammer (pour éviter les exécutions multiples)
                await asyncio.sleep(60)
        
        # Créer et stocker la tâche
        task = asyncio.create_task(_schedule_and_run())
        self.scheduled_tasks[task_name] = task
    
    async def _handle_user_activity(self, event: Event):
        """
        Traite un événement d'activité utilisateur
        
        Args:
            event (Event): Événement d'activité
        """
        activity = event.data
        
        # Ajouter l'activité au contexte
        self.current_context['activities'].append(activity)
        
        # Analyser l'activité pour détecter des contextes spécifiques
        activity_type = activity.get('activity_type', '').lower()
        description = activity.get('description', '').lower()
        
        # Détecter les repas
        if 'eating' in activity_type or 'meal' in activity_type or 'food' in description:
            self.current_context['last_meal'] = activity.get('timestamp', datetime.now().isoformat())
            logger.debug(f"Repas détecté: {description}")
        
        # Détecter la prise de médicaments
        if 'medication' in activity_type or 'pill' in activity_type or 'medicine' in description:
            self.current_context['last_medication'] = activity.get('timestamp', datetime.now().isoformat())
            logger.debug(f"Prise de médicament détectée: {description}")
        
        # Analyser l'activité pour des recommandations contextuelles
        await self._check_activity_based_recommendations(activity)
    
    async def _handle_weather_update(self, event: Event):
        """
        Traite un événement de mise à jour météo
        
        Args:
            event (Event): Événement météo
        """
        weather_data = event.data
        
        # Mettre à jour le contexte météo
        self.current_context['weather'] = weather_data
        
        # Analyser les données météo pour des recommandations éventuelles
        await self._check_weather_based_recommendations(weather_data)
    
    async def _handle_high_priority(self, event: Event):
        """
        Traite un événement de haute priorité
        
        Args:
            event (Event): Événement haute priorité
        """
        # Pour les événements de haute priorité, créer une recommandation immédiate
        if event.event_type == EventType.WHATSAPP_CALL:
            caller = event.data.get('caller', 'Quelqu\'un')
            await self._create_recommendation(
                'communication',
                f"Appel WhatsApp de {caller}",
                EventPriority.HIGH,
                {'event_id': event.id, 'caller': caller}
            )
        
        elif event.event_type == EventType.PHONE_CALL:
            caller = event.data.get('caller', 'Quelqu\'un')
            await self._create_recommendation(
                'communication',
                f"Appel téléphonique de {caller}",
                EventPriority.HIGH,
                {'event_id': event.id, 'caller': caller}
            )
        
        elif event.event_type == EventType.SMS_RECEIVED and event.data.get('urgent', False):
            sender = event.data.get('sender', 'Quelqu\'un')
            await self._create_recommendation(
                'communication',
                f"SMS urgent de {sender}",
                EventPriority.HIGH,
                {'event_id': event.id, 'sender': sender, 'message': event.data.get('message', '')}
            )
        
        elif event.event_type == EventType.EMAIL_RECEIVED and event.data.get('urgent', False):
            sender = event.data.get('sender', 'Quelqu\'un')
            await self._create_recommendation(
                'communication',
                f"Email urgent de {sender}",
                EventPriority.HIGH,
                {'event_id': event.id, 'sender': sender, 'subject': event.data.get('subject', '')}
            )
        
        elif event.event_type == EventType.WEATHER_ALERT:
            alert_type = event.data.get('alert_type', 'Alerte météo')
            description = event.data.get('description', 'Conditions météorologiques importantes')
            await self._create_recommendation(
                'weather_alert',
                f"{alert_type}: {description}",
                event.priority,
                {'event_id': event.id, 'alert_type': alert_type, 'description': description}
            )
    
    async def _check_medication_time(self):
        """
        Vérifie s'il est temps de rappeler la prise de médicament
        """
        now = datetime.now()
        now_str = now.strftime('%H:%M')
        
        # Vérifier si la prise de médicament a déjà été effectuée récemment
        if self.current_context['last_medication']:
            last_med_time = datetime.fromisoformat(self.current_context['last_medication'])
            elapsed = now - last_med_time
            
            # Si la dernière prise était il y a moins de 30 minutes, ne pas rappeler
            if elapsed < timedelta(minutes=30):
                logger.debug(f"Prise de médicament récente ({elapsed.total_seconds() / 60:.0f} min), pas de rappel")
                return
        
        # Vérifier si nous sommes dans une période de repas
        for med_time in self.settings.medication_times:
            med_hour, med_minute = map(int, med_time.split(':'))
            med_datetime = datetime.combine(now.date(), time(med_hour, med_minute))
            
            # Si nous sommes dans les 30 minutes avant ou après l'heure prévue
            if abs((now - med_datetime).total_seconds()) < 1800:  # 30 minutes
                # Vérifier si nous avons déjà envoyé une recommandation récemment
                if self._can_send_recommendation('medication'):
                    await self._create_recommendation(
                        'medication',
                        f"N'oubliez pas de prendre vos médicaments",
                        EventPriority.MEDIUM,
                        {'time': med_time}
                    )
                break
    
    async def _check_meal_time(self):
        """
        Vérifie s'il est temps de rappeler un repas
        """
        now = datetime.now()
        now_str = now.strftime('%H:%M')
        
        # Vérifier si un repas a déjà été pris récemment
        if self.current_context['last_meal']:
            last_meal_time = datetime.fromisoformat(self.current_context['last_meal'])
            elapsed = now - last_meal_time
            
            # Si le dernier repas était il y a moins d'une heure, ne pas rappeler
            if elapsed < timedelta(hours=1):
                logger.debug(f"Repas récent ({elapsed.total_seconds() / 3600:.1f}h), pas de rappel")
                return
        
        # Vérifier si nous sommes dans une période de repas
        for meal_time in self.settings.meal_times:
            meal_hour, meal_minute = map(int, meal_time.split(':'))
            meal_datetime = datetime.combine(now.date(), time(meal_hour, meal_minute))
            
            # Si nous sommes dans les 30 minutes avant ou après l'heure prévue
            if abs((now - meal_datetime).total_seconds()) < 1800:  # 30 minutes
                # Vérifier si la personne est inactive (pour ne pas interrompre une activité importante)
                is_inactive = self._check_inactivity(timedelta(minutes=15))
                
                if is_inactive and self._can_send_recommendation('meal'):
                    # Déterminer le type de repas en fonction de l'heure
                    meal_type = "repas"
                    if 6 <= meal_hour < 10:
                        meal_type = "petit-déjeuner"
                    elif 11 <= meal_hour < 14:
                        meal_type = "déjeuner"
                    elif 18 <= meal_hour < 21:
                        meal_type = "dîner"
                    
                    await self._create_recommendation(
                        'meal',
                        f"Il est temps de préparer votre {meal_type}",
                        EventPriority.MEDIUM,
                        {'time': meal_time, 'meal_type': meal_type}
                    )
                break
    
    async def _check_weather_conditions(self):
        """
        Vérifie les conditions météo pour proposer des recommandations adaptées
        """
        if not self.current_context['weather']:
            logger.debug("Pas de données météo disponibles pour les recommandations")
            return
        
        # Vérifier si nous pouvons envoyer une recommandation météo
        if not self._can_send_recommendation('weather'):
            return
        
        weather = self.current_context['weather']
        status = weather.get('detailed_status', '').lower()
        temp = weather.get('temperature', {}).get('temp', 20)  # Température par défaut: 20°C
        
        # Recommandations basées sur la météo
        if 'rain' in status or 'shower' in status:
            await self._create_recommendation(
                'weather',
                f"Il pleut actuellement. N'oubliez pas votre parapluie si vous sortez.",
                EventPriority.MEDIUM,
                {'weather': weather}
            )
        
        elif 'snow' in status:
            await self._create_recommendation(
                'weather',
                f"Il neige actuellement. Habillez-vous chaudement si vous sortez.",
                EventPriority.MEDIUM,
                {'weather': weather}
            )
        
        elif temp < 5:
            await self._create_recommendation(
                'weather',
                f"Il fait très froid actuellement ({temp:.1f}°C). Habillez-vous chaudement si vous sortez.",
                EventPriority.MEDIUM,
                {'weather': weather}
            )
        
        elif temp > 30:
            await self._create_recommendation(
                'weather',
                f"Il fait très chaud actuellement ({temp:.1f}°C). Pensez à bien vous hydrater.",
                EventPriority.MEDIUM,
                {'weather': weather}
            )
    
    async def _check_activity_based_recommendations(self, activity: Dict[str, Any]):
        """
        Génère des recommandations basées sur l'activité détectée
        
        Args:
            activity (Dict[str, Any]): Activité détectée
        """
        activity_type = activity.get('activity_type', '').lower()
        description = activity.get('description', '').lower()
        
        # Si l'utilisateur mange, rappeler les médicaments si c'est l'heure
        if ('eating' in activity_type or 'meal' in activity_type) and self._can_send_recommendation('medication_with_meal'):
            now = datetime.now()
            
            # Vérifier si une prise de médicament est prévue autour de cette heure
            for med_time in self.settings.medication_times:
                med_hour, med_minute = map(int, med_time.split(':'))
                med_datetime = datetime.combine(now.date(), time(med_hour, med_minute))
                
                # Si nous sommes dans les 60 minutes avant ou après l'heure prévue
                if abs((now - med_datetime).total_seconds()) < 3600:  # 60 minutes
                    await self._create_recommendation(
                        'medication_with_meal',
                        f"Pendant que vous mangez, n'oubliez pas de prendre vos médicaments",
                        EventPriority.MEDIUM,
                        {'time': med_time}
                    )
                    break
        
        # Si l'utilisateur est inactif pendant longtemps, suggérer une activité
        elif 'idle' in activity_type and self._can_send_recommendation('activity_suggestion'):
            # Vérifier la météo pour suggérer une activité adaptée
            if self.current_context['weather']:
                weather = self.current_context['weather']
                status = weather.get('detailed_status', '').lower()
                temp = weather.get('temperature', {}).get('temp', 20)
                
                if ('clear' in status or 'sun' in status) and 15 <= temp <= 25:
                    await self._create_recommendation(
                        'activity_suggestion',
                        f"Il fait beau dehors ({temp:.1f}°C). C'est peut-être le moment idéal pour une promenade ?",
                        EventPriority.LOW,
                        {'weather': weather}
                    )
                else:
                    # Activité intérieure
                    indoor_activities = [
                        "lire un livre",
                        "regarder un film",
                        "cuisiner quelque chose de nouveau",
                        "appeler un ami",
                        "faire un peu de rangement"
                    ]
                    suggestion = random.choice(indoor_activities)
                    await self._create_recommendation(
                        'activity_suggestion',
                        f"Vous êtes inactif depuis un moment. Que diriez-vous de {suggestion} ?",
                        EventPriority.LOW,
                        {'suggestion': suggestion}
                    )
    
    async def _check_weather_based_recommendations(self, weather: Dict[str, Any]):
        """
        Génère des recommandations basées sur les conditions météo
        
        Args:
            weather (Dict[str, Any]): Données météo
        """
        # Cette méthode est appelée à chaque mise à jour météo
        # Les recommandations régulières sont gérées par _check_weather_conditions
        pass
    
    async def _create_recommendation(self, rec_type: str, message: str, priority: EventPriority, 
                                   metadata: Optional[Dict[str, Any]] = None):
        """
        Crée et envoie une recommandation
        
        Args:
            rec_type (str): Type de recommandation
            message (str): Message de la recommandation
            priority (EventPriority): Priorité de la recommandation
            metadata (Optional[Dict[str, Any]], optional): Métadonnées supplémentaires. Defaults to None.
        """
        # Créer un événement de recommandation
        event = Event(
            event_type=EventType.ACTIVITY_SUGGESTION,
            priority=priority,
            source="recommendation_engine",
            data={
                'recommendation_type': rec_type,
                'message': message,
                'metadata': metadata or {}
            }
        )
        
        # Publier l'événement
        await self.event_manager.publish(event)
        
        # Mettre à jour le suivi des recommandations
        self.current_context['last_recommendations'][rec_type] = datetime.now().isoformat()
        
        logger.info(f"Recommandation créée: {rec_type} - {message}")
    
    def _can_send_recommendation(self, rec_type: str) -> bool:
        """
        Vérifie si une recommandation d'un certain type peut être envoyée
        
        Args:
            rec_type (str): Type de recommandation
            
        Returns:
            bool: True si la recommandation peut être envoyée, False sinon
        """
        # Vérifier si nous avons déjà envoyé une recommandation de ce type récemment
        if rec_type in self.current_context['last_recommendations']:
            last_time_str = self.current_context['last_recommendations'][rec_type]
            last_time = datetime.fromisoformat(last_time_str)
            now = datetime.now()
            
            # Obtenir l'intervalle minimum pour ce type (ou utiliser 30 minutes par défaut)
            min_interval = self.recommendation_intervals.get(rec_type, 30)
            
            # Vérifier si assez de temps s'est écoulé
            if (now - last_time) < timedelta(minutes=min_interval):
                logger.debug(f"Recommandation {rec_type} envoyée récemment, attente de {min_interval} minutes")
                return False
        
        return True
    
    def _check_inactivity(self, duration: timedelta) -> bool:
        """
        Vérifie si l'utilisateur est inactif depuis une certaine durée
        
        Args:
            duration (timedelta): Durée d'inactivité à vérifier
            
        Returns:
            bool: True si l'utilisateur est inactif, False sinon
        """
        if not self.current_context['activities']:
            return True
        
        # Trouver l'activité la plus récente
        now = datetime.now()
        latest_activity = max(
            self.current_context['activities'],
            key=lambda a: datetime.fromisoformat(a.get('timestamp', '2000-01-01T00:00:00'))
        )
        
        latest_time = datetime.fromisoformat(latest_activity.get('timestamp', now.isoformat()))
        elapsed = now - latest_time
        
        return elapsed > duration
