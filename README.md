Description

Ce projet est une application de gestion de stationnement intelligente basée sur Raspberry Pi, un capteur ultrason (HC-SR04) et un servomoteur.
L’objectif est de détecter automatiquement la présence d’un véhicule et de contrôler l’ouverture/fermeture d’une barrière via une interface web.

Technologies utilisées

Python 3

Flask (serveur web et interface)

RPi.GPIO (gestion des GPIO du Raspberry Pi)

adafruit_servokit (contrôle du servomoteur)

HTML/CSS (interface utilisateur)

📂 Structure du projet
Projet-Stationnement/
│── app.py                # Application Flask principale
│── hardware.py           # Classes pour le capteur ultrason et le servomoteur
│── templates/
│    └── index.html       # Page web pour contrôler le stationnement

⚙️ Installation et exécution

Cloner le projet

git clone https://github.com/AlHassaneDiarra/Gestion-Stationnement)
cd Projet-Stationnement


Installer les dépendances

pip install flask adafruit-circuitpython-servokit RPi.GPIO


Lancer l’application

python app.py


Accéder à l’interface
Ouvre ton navigateur et va sur :
👉 http://localhost:5000
 (ou l’adresse IP du Raspberry Pi).

🎯 Fonctionnalités

Détection automatique de la présence d’un véhicule via capteur ultrason.

Contrôle d’une barrière (servomoteur).

Interface web simple et intuitive.

Journalisation (logs) pour le suivi du système.

🚀 Améliorations possibles

Ajout d’un système de réservation de places.

Intégration d’une base de données pour sauvegarder l’historique.

Support multi-capteurs pour plusieurs places de stationnement.

Sécurisation de l’accès web (login/mot de passe).
