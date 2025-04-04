#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Contrôleur d'avatar qui gère l'interface utilisateur de l'assistant.
"""

import asyncio
import logging
import threading
import queue
import os
from enum import Enum, auto
from typing import Dict, Any, List, Optional, Tuple, Callable
from datetime import datetime, timedelta

from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QWidget, QVBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QSize
from PyQt6.QtGui import QIcon, QPixmap, QFont, QAction, QCloseEvent
from plyer import notification

from config.settings import Settings
from events.event_manager import EventManager
from events.event_types import Event, EventType, EventPriority

logger = logging.getLogger("angel.avatar")

class AvatarState(Enum):
    """États possibles de l'avatar"""
    IDLE = auto()       # Au repos, pas d'activité
    ACTIVE = auto()     # Actif, en train de faire quelque chose
    ALERT = auto()      # Alerte de haute priorité
    SPEAKING = auto()   # En train de parler à l'utilisateur
    HIDDEN = auto()     # Caché
    WAITING = auto()    # En attente de l'utilisateur


class AvatarController(QObject):
    """
    Contrôleur principal pour l'avatar de l'assistant.
    Gère l'interface utilisateur et les interactions.
    """
    
    # Signaux pour la communication avec l'interface Qt
    show_notification_signal = pyqtSignal(str, str, str, int)
    show_avatar_signal = pyqtSignal(dict)
    update_avatar_signal = pyqtSignal(dict)
    hide_avatar_signal = pyqtSignal()
    
    def __init__(self, event_manager: EventManager, settings: Settings):
        """
        Initialise le contrôleur d'avatar
        
        Args:
            event_manager (EventManager): Gestionnaire d'événements
            settings (Settings): Configuration de l'application
        """
        super().__init__()
        self.event_manager = event_manager
        self.settings = settings
        self.running = False
        self.state = AvatarState.HIDDEN
        self.qt_app = None
        self.tray_icon = None
        self.avatar_window = None
        self.message_queue = queue.Queue()
        self.ui_thread = None
        
        # File d'attente des recommandations
        self.pending_recommendations = []
        
        # Timer pour les animations et transitions
        self.animation_timer = None
        self.hide_timer = None
        
        # Connecter les signaux
        self.show_notification_signal.connect(self._show_notification_slot)
        self.show_avatar_signal.connect(self._show_avatar_slot)
        self.update_avatar_signal.connect(self._update_avatar_slot)
        self.hide_avatar_signal.connect(self._hide_avatar_slot)
        
        # S'abonner aux événements pertinents
        self.event_manager.subscribe(EventType.ACTIVITY_SUGGESTION, self._handle_activity_suggestion)
        self.event_manager.subscribe_to_priority(EventPriority.HIGH, self._handle_high_priority)
        self.event_manager.subscribe_to_priority(EventPriority.CRITICAL, self._handle_critical_priority)
        
        logger.info("Contrôleur d'avatar initialisé")
    
    async def start(self):
        """Démarre le contrôleur d'avatar"""
        if self.running:
            logger.warning("Le contrôleur d'avatar est déjà en cours d'exécution")
            return
        
        logger.info("Démarrage du contrôleur d'avatar")
        self.running = True
        
        # Démarrer l'interface Qt dans un thread séparé
        self.ui_thread = threading.Thread(target=self._run_ui_thread)
        self.ui_thread.daemon = True
        self.ui_thread.start()
        
        # Attendre que l'interface Qt soit initialisée
        while not self.qt_app:
            await asyncio.sleep(0.1)
        
        logger.info("Contrôleur d'avatar démarré")
    
    async def stop(self):
        """Arrête le contrôleur d'avatar"""
        if not self.running:
            logger.warning("Le contrôleur d'avatar n'est pas en cours d'exécution")
            return
        
        logger.info("Arrêt du contrôleur d'avatar")
        self.running = False
        
        # Informer le thread UI de s'arrêter
        self.message_queue.put(("quit", None))
        
        # Attendre que le thread UI se termine
        if self.ui_thread:
            self.ui_thread.join(timeout=5)
        
        self.qt_app = None
        self.tray_icon = None
        self.avatar_window = None
        
        logger.info("Contrôleur d'avatar arrêté")
    
    def _run_ui_thread(self):
        """
        Fonction principale du thread UI
        """
        try:
            self.qt_app = QApplication([])
            self.qt_app.setQuitOnLastWindowClosed(False)
            
            # Créer une icône de notification système
            self._create_tray_icon()
            
            # Créer la fenêtre d'avatar (initialement cachée)
            self._create_avatar_window()
            
            # Configurer les timers
            self.animation_timer = QTimer()
            self.animation_timer.timeout.connect(self._update_animation)
            
            self.hide_timer = QTimer()
            self.hide_timer.setSingleShot(True)
            self.hide_timer.timeout.connect(lambda: self.hide_avatar_signal.emit())
            
            # Boucle principale
            while self.running:
                # Traiter les événements Qt
                self.qt_app.processEvents()
                
                # Vérifier les messages de la file d'attente
                try:
                    message_type, message_data = self.message_queue.get(block=False)
                    self._handle_message(message_type, message_data)
                    self.message_queue.task_done()
                except queue.Empty:
                    pass
                
                # Dormir un peu pour ne pas saturer le CPU
                QApplication.instance().thread().msleep(100)
        
        except Exception as e:
            logger.error(f"Erreur dans le thread UI: {e}")
        finally:
            if self.qt_app:
                self.qt_app.quit()
    
    def _handle_message(self, message_type: str, message_data: Any):
        """
        Traite les messages reçus de la file d'attente
        
        Args:
            message_type (str): Type de message
            message_data (Any): Données du message
        """
        if message_type == "quit":
            self.qt_app.quit()
        
        elif message_type == "show_notification":
            title, message, app_name, timeout = message_data
            self.show_notification_signal.emit(title, message, app_name, timeout)
        
        elif message_type == "show_avatar":
            self.show_avatar_signal.emit(message_data)
        
        elif message_type == "update_avatar":
            self.update_avatar_signal.emit(message_data)
        
        elif message_type == "hide_avatar":
            self.hide_avatar_signal.emit()
    
    def _create_tray_icon(self):
        """
        Crée l'icône de notification système
        """
        icon_path = os.path.join(os.path.dirname(__file__), "assets", "tray_icon.png")
        
        # Utiliser une icône par défaut si l'icône personnalisée n'existe pas
        if not os.path.exists(icon_path):
            icon_path = None
        
        self.tray_icon = QSystemTrayIcon()
        if icon_path:
            self.tray_icon.setIcon(QIcon(icon_path))
        else:
            self.tray_icon.setIcon(QIcon.fromTheme("dialog-information"))
        
        # Créer le menu contextuel
        tray_menu = QMenu()
        
        # Action pour afficher l'avatar
        show_action = QAction("Afficher l'avatar", self)
        show_action.triggered.connect(lambda: self.show_avatar_signal.emit({}))
        tray_menu.addAction(show_action)
        
        # Action pour masquer l'avatar
        hide_action = QAction("Masquer l'avatar", self)
        hide_action.triggered.connect(lambda: self.hide_avatar_signal.emit())
        tray_menu.addAction(hide_action)
        
        # Séparateur
        tray_menu.addSeparator()
        
        # Action pour quitter
        quit_action = QAction("Quitter", self)
        quit_action.triggered.connect(self.qt_app.quit)
        tray_menu.addAction(quit_action)
        
        # Définir le menu contextuel
        self.tray_icon.setContextMenu(tray_menu)
        
        # Afficher l'icône
        self.tray_icon.show()
    
    def _create_avatar_window(self):
        """
        Crée la fenêtre de l'avatar
        """
        self.avatar_window = AvatarWindow(self.settings)
        
        # Connecter les signaux de l'avatar
        self.avatar_window.recommendation_accepted.connect(self._on_recommendation_accepted)
        self.avatar_window.recommendation_declined.connect(self._on_recommendation_declined)
        self.avatar_window.avatar_closed.connect(self._on_avatar_closed)
    
    def _show_notification_slot(self, title: str, message: str, app_name: str, timeout: int):
        """
        Affiche une notification système
        
        Args:
            title (str): Titre de la notification
            message (str): Message de la notification
            app_name (str): Nom de l'application
            timeout (int): Délai d'expiration en secondes
        """
        try:
            notification.notify(
                title=title,
                message=message,
                app_name=app_name,
                timeout=timeout
            )
        except Exception as e:
            logger.error(f"Erreur lors de l'affichage de la notification: {e}")
    
    def _show_avatar_slot(self, data: Dict[str, Any]):
        """
        Affiche l'avatar avec les données spécifiées
        
        Args:
            data (Dict[str, Any]): Données à afficher (message, état, etc.)
        """
        if not self.avatar_window:
            logger.error("Fenêtre d'avatar non initialisée")
            return
        
        # Mettre à jour l'état
        self.state = data.get('state', AvatarState.ACTIVE)
        
        # Définir le message et les métadonnées
        message = data.get('message', '')
        metadata = data.get('metadata', {})
        recommendation_id = data.get('recommendation_id', '')
        
        # Afficher la fenêtre avec les données
        self.avatar_window.show_message(message, metadata, recommendation_id)
        self.avatar_window.show()
        
        # Si un délai d'expiration est spécifié, configurer le timer
        if 'timeout' in data and data['timeout'] > 0:
            self.hide_timer.start(data['timeout'] * 1000)
    
    def _update_avatar_slot(self, data: Dict[str, Any]):
        """
        Met à jour l'avatar avec les données spécifiées
        
        Args:
            data (Dict[str, Any]): Données à mettre à jour
        """
        if not self.avatar_window or not self.avatar_window.isVisible():
            return
        
        # Mettre à jour l'état si spécifié
        if 'state' in data:
            self.state = data['state']
        
        # Mettre à jour le message si spécifié
        if 'message' in data:
            self.avatar_window.update_message(data['message'])
    
    def _hide_avatar_slot(self):
        """
        Cache l'avatar
        """
        if self.avatar_window and self.avatar_window.isVisible():
            self.avatar_window.hide()
            self.state = AvatarState.HIDDEN
    
    def _update_animation(self):
        """
        Met à jour l'animation de l'avatar (appelée périodiquement par le timer)
        """
        if not self.avatar_window or not self.avatar_window.isVisible():
            return
        
        # Mettre à jour l'animation en fonction de l'état
        if self.state == AvatarState.SPEAKING:
            self.avatar_window.update_speaking_animation()
        elif self.state == AvatarState.ALERT:
            self.avatar_window.update_alert_animation()
        elif self.state == AvatarState.ACTIVE:
            self.avatar_window.update_active_animation()
    
    def _on_recommendation_accepted(self, recommendation_id: str):
        """
        Appelé lorsqu'une recommandation est acceptée par l'utilisateur
        
        Args:
            recommendation_id (str): ID de la recommandation
        """
        # Passer à la recommandation suivante s'il y en a une
        if self.pending_recommendations:
            next_recommendation = self.pending_recommendations.pop(0)
            
            # Afficher la recommandation suivante après un court délai
            QTimer.singleShot(1000, lambda: self.show_avatar_signal.emit(next_recommendation))
        else:
            # Cacher l'avatar après un court délai
            QTimer.singleShot(2000, lambda: self.hide_avatar_signal.emit())
    
    def _on_recommendation_declined(self, recommendation_id: str):
        """
        Appelé lorsqu'une recommandation est refusée par l'utilisateur
        
        Args:
            recommendation_id (str): ID de la recommandation
        """
        # Passer à la recommandation suivante s'il y en a une
        if self.pending_recommendations:
            next_recommendation = self.pending_recommendations.pop(0)
            
            # Afficher la recommandation suivante après un court délai
            QTimer.singleShot(1000, lambda: self.show_avatar_signal.emit(next_recommendation))
        else:
            # Cacher l'avatar après un court délai
            QTimer.singleShot(1000, lambda: self.hide_avatar_signal.emit())
    
    def _on_avatar_closed(self):
        """
        Appelé lorsque la fenêtre de l'avatar est fermée par l'utilisateur
        """
        # Vider la file d'attente des recommandations
        self.pending_recommendations = []
        
        # Mettre à jour l'état
        self.state = AvatarState.HIDDEN
    
    async def _handle_activity_suggestion(self, event: Event):
        """
        Traite un événement de suggestion d'activité
        
        Args:
            event (Event): Événement de suggestion
        """
        # Extraire les données de la suggestion
        recommendation_type = event.data.get('recommendation_type', 'activity')
        message = event.data.get('message', 'Suggestion d\'activité')
        metadata = event.data.get('metadata', {})
        
        # Créer les données pour l'affichage
        avatar_data = {
            'message': message,
            'metadata': metadata,
            'state': AvatarState.ACTIVE,
            'recommendation_id': event.id,
            'timeout': 30  # Timeout par défaut: 30 secondes
        }
        
        # Si c'est une suggestion de haute priorité, l'afficher immédiatement
        if event.priority in [EventPriority.HIGH, EventPriority.CRITICAL]:
            # Si l'avatar est déjà visible, ajouter à la file d'attente
            if self.state != AvatarState.HIDDEN and self.avatar_window and self.avatar_window.isVisible():
                self.pending_recommendations.append(avatar_data)
            else:
                # Afficher l'avatar immédiatement
                self.message_queue.put(("show_avatar", avatar_data))
        else:
            # Pour les suggestions de priorité normale ou basse,
            # les ajouter à la file d'attente et afficher l'avatar
            # si aucune recommandation n'est en cours
            self.pending_recommendations.append(avatar_data)
            
            if self.state == AvatarState.HIDDEN or not (self.avatar_window and self.avatar_window.isVisible()):
                # Afficher la première recommandation
                if self.pending_recommendations:
                    first_recommendation = self.pending_recommendations.pop(0)
                    self.message_queue.put(("show_avatar", first_recommendation))
    
    async def _handle_high_priority(self, event: Event):
        """
        Traite un événement de haute priorité
        
        Args:
            event (Event): Événement de haute priorité
        """
        # Pour les événements de haute priorité, afficher immédiatement
        # selon le type d'événement
        if event.event_type == EventType.WHATSAPP_CALL:
            caller = event.data.get('caller', 'Quelqu\'un')
            self._show_intrusive_notification(
                "Appel WhatsApp",
                f"Appel entrant de {caller}",
                event
            )
        
        elif event.event_type == EventType.PHONE_CALL:
            caller = event.data.get('caller', 'Quelqu\'un')
            self._show_intrusive_notification(
                "Appel téléphonique",
                f"Appel entrant de {caller}",
                event
            )
        
        elif event.event_type == EventType.SMS_RECEIVED and event.data.get('urgent', False):
            sender = event.data.get('sender', 'Quelqu\'un')
            self._show_intrusive_notification(
                "SMS urgent",
                f"Message de {sender}",
                event
            )
        
        elif event.event_type == EventType.EMAIL_RECEIVED and event.data.get('urgent', False):
            sender = event.data.get('sender', 'Quelqu\'un')
            subject = event.data.get('subject', 'Sans sujet')
            self._show_intrusive_notification(
                "Email urgent",
                f"De: {sender}\nObjet: {subject}",
                event
            )
        
        elif event.event_type == EventType.WEATHER_ALERT:
            alert_type = event.data.get('alert_type', 'Alerte météo')
            description = event.data.get('description', 'Conditions météorologiques importantes')
            self._show_intrusive_notification(
                f"Alerte météo: {alert_type}",
                description,
                event
            )
    
    async def _handle_critical_priority(self, event: Event):
        """
        Traite un événement de priorité critique
        
        Args:
            event (Event): Événement de priorité critique
        """
        # Traiter de la même manière que les événements de haute priorité,
        # mais avec plus d'insistance (son, clignotement, etc.)
        await self._handle_high_priority(event)
    
    def _show_intrusive_notification(self, title: str, message: str, event: Event):
        """
        Affiche une notification intrusive pour un événement important
        
        Args:
            title (str): Titre de la notification
            message (str): Message de la notification
            event (Event): Événement associé
        """
        # Afficher une notification système
        self.message_queue.put((
            "show_notification",
            (title, message, "Angel Assistant", 10)
        ))
        
        # Afficher l'avatar en mode alerte
        avatar_data = {
            'message': message,
            'metadata': event.data,
            'state': AvatarState.ALERT,
            'recommendation_id': event.id,
            'timeout': 0  # Pas de timeout pour les alertes
        }
        
        self.message_queue.put(("show_avatar", avatar_data))
        
        # Démarrer l'animation d'alerte
        if not self.animation_timer.isActive():
            self.animation_timer.start(200)  # Mise à jour toutes les 200ms


class AvatarWindow(QWidget):
    """
    Fenêtre de l'avatar qui affiche les messages et recommandations
    """
    
    # Signaux pour les interactions utilisateur
    recommendation_accepted = pyqtSignal(str)
    recommendation_declined = pyqtSignal(str)
    avatar_closed = pyqtSignal()
    
    def __init__(self, settings: Settings):
        """
        Initialise la fenêtre de l'avatar
        
        Args:
            settings (Settings): Configuration de l'application
        """
        super().__init__(flags=Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        
        self.settings = settings
        self.current_recommendation_id = ""
        self.current_metadata = {}
        self.animation_frame = 0
        
        # Configurer la fenêtre
        self.setWindowTitle("Angel Assistant")
        self.setMinimumSize(300, 200)
        
        # Configurer la position de la fenêtre
        self._setup_position()
        
        # Configurer l'interface utilisateur
        self._setup_ui()
        
        # Masquer initialement
        self.hide()
    
    def _setup_position(self):
        """
        Configure la position de l'avatar selon les paramètres
        """
        desktop = QApplication.primaryScreen().availableGeometry()
        window_width = 300
        window_height = 200
        
        # Position selon les paramètres
        position = self.settings.avatar_position.lower()
        
        if position == "top-left":
            self.setGeometry(10, 10, window_width, window_height)
        elif position == "top-right":
            self.setGeometry(desktop.width() - window_width - 10, 10, window_width, window_height)
        elif position == "bottom-left":
            self.setGeometry(10, desktop.height() - window_height - 10, window_width, window_height)
        else:  # bottom-right par défaut
            self.setGeometry(desktop.width() - window_width - 10, desktop.height() - window_height - 10, window_width, window_height)
    
    def _setup_ui(self):
        """
        Configure l'interface utilisateur de l'avatar
        """
        # Disposition principale
        layout = QVBoxLayout(self)
        
        # Zone d'avatar (image)
        self.avatar_image = QLabel()
        self.avatar_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar_image.setMinimumSize(100, 100)
        
        # Charger l'image d'avatar
        avatar_path = os.path.join(os.path.dirname(__file__), "assets", "avatar_idle.png")
        if os.path.exists(avatar_path):
            pixmap = QPixmap(avatar_path)
            self.avatar_image.setPixmap(pixmap.scaled(100, 100, Qt.AspectRatioMode.KeepAspectRatio))
        else:
            self.avatar_image.setText("Avatar")
        
        layout.addWidget(self.avatar_image)
        
        # Zone de message
        self.message_label = QLabel("Je suis votre assistant Angel.")
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setWordWrap(True)
        self.message_label.setFont(QFont('Arial', 10))
        layout.addWidget(self.message_label)
        
        # Boutons d'action
        button_layout = QVBoxLayout()
        
        self.accept_button = QPushButton("Accepter")
        self.accept_button.clicked.connect(self._on_accept_clicked)
        button_layout.addWidget(self.accept_button)
        
        self.decline_button = QPushButton("Plus tard")
        self.decline_button.clicked.connect(self._on_decline_clicked)
        button_layout.addWidget(self.decline_button)
        
        layout.addLayout(button_layout)
        
        # Configurer les marges et espacement
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        self.setLayout(layout)
    
    def show_message(self, message: str, metadata: Dict[str, Any], recommendation_id: str):
        """
        Affiche un message avec des métadonnées et un ID de recommandation
        
        Args:
            message (str): Message à afficher
            metadata (Dict[str, Any]): Métadonnées associées
            recommendation_id (str): ID de la recommandation
        """
        self.message_label.setText(message)
        self.current_metadata = metadata
        self.current_recommendation_id = recommendation_id
        
        # Afficher ou masquer les boutons selon le contexte
        if recommendation_id:
            self.accept_button.show()
            self.decline_button.show()
        else:
            self.accept_button.hide()
            self.decline_button.hide()
    
    def update_message(self, message: str):
        """
        Met à jour le message affiché
        
        Args:
            message (str): Nouveau message
        """
        self.message_label.setText(message)
    
    def update_speaking_animation(self):
        """
        Met à jour l'animation de parole
        """
        self.animation_frame = (self.animation_frame + 1) % 3
        avatar_path = os.path.join(os.path.dirname(__file__), "assets", f"avatar_speaking_{self.animation_frame}.png")
        
        if os.path.exists(avatar_path):
            pixmap = QPixmap(avatar_path)
            self.avatar_image.setPixmap(pixmap.scaled(100, 100, Qt.AspectRatioMode.KeepAspectRatio))
    
    def update_alert_animation(self):
        """
        Met à jour l'animation d'alerte
        """
        self.animation_frame = (self.animation_frame + 1) % 2
        avatar_path = os.path.join(os.path.dirname(__file__), "assets", f"avatar_alert_{self.animation_frame}.png")
        
        if os.path.exists(avatar_path):
            pixmap = QPixmap(avatar_path)
            self.avatar_image.setPixmap(pixmap.scaled(100, 100, Qt.AspectRatioMode.KeepAspectRatio))
    
    def update_active_animation(self):
        """
        Met à jour l'animation d'activité
        """
        self.animation_frame = (self.animation_frame + 1) % 2
        avatar_path = os.path.join(os.path.dirname(__file__), "assets", f"avatar_active_{self.animation_frame}.png")
        
        if os.path.exists(avatar_path):
            pixmap = QPixmap(avatar_path)
            self.avatar_image.setPixmap(pixmap.scaled(100, 100, Qt.AspectRatioMode.KeepAspectRatio))
    
    def _on_accept_clicked(self):
        """
        Appelé lorsque l'utilisateur clique sur le bouton Accepter
        """
        if self.current_recommendation_id:
            self.recommendation_accepted.emit(self.current_recommendation_id)
    
    def _on_decline_clicked(self):
        """
        Appelé lorsque l'utilisateur clique sur le bouton Décliner
        """
        if self.current_recommendation_id:
            self.recommendation_declined.emit(self.current_recommendation_id)
    
    def closeEvent(self, event: QCloseEvent):
        """
        Appelé lorsque la fenêtre est fermée
        
        Args:
            event (QCloseEvent): Événement de fermeture
        """
        self.avatar_closed.emit()
        event.accept()
