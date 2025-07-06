import logging
import threading
import time

from flask import Flask, render_template, request
from hardware import UltrasonicSensor, ServoController

app = Flask(__name__)

# === Configuration du logger ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# === Constantes ===
SEUIL_DISTANCE = 10         # cm : seuil de détection
DELAI_DEBOUNCE = 0.05       # 50 ms entre lectures pour “debounce”
LECTURES_DEBOUNCE = 3       # faire 3 lectures consécutives
DELAI_SECONDE_CAPTEUR = 3   # 3 s pour attendre le deuxième capteur
DELAI_FERMETURE_MANUELLE = 5 # 5 s après ouverture manuelle

# === Objets matériels (globaux) ===
sensor_in = UltrasonicSensor(21, 20)   # capteur intérieur (GPIO 21=TRIG, 20=ECHO)
sensor_out = UltrasonicSensor(19, 16)  # capteur extérieur (GPIO 19=TRIG, 16=ECHO)
servo = ServoController(channel=0)      # servo sur canal 0 du PCA9685

# === Machine à états avec locks ===
class ParkingManager:
    """
    Gère les séquences “Entrée” et “Sortie” en utilisant des timers, avec :
      - délai 3 s pour déclencher le second capteur (entrée/sortie),
      - délai 5 s pour auto-fermer après ouverture manuelle.
    Tous les accès aux états partagés sont protégés par self.lock.
    """
    def __init__(self):
        # Compteur et état de la barrière
        self.nombre_voitures = 0
        self.etat_barriere = "Fermée"      # “Ouverte” ou “Fermée”
        self.transition = None             # None, "entry_pending" ou "exit_pending"
        # Verrou réentrant pour protéger tous ces accès
        self.lock = threading.RLock()
        # Timers pour les délais
        self.entry_timer = None            # Timer 3 s pour entrée
        self.exit_timer = None             # Timer 3 s pour sortie
        self.manual_timer = None           # Timer 5 s après ouverture manuelle

    def _log_state(self):
        logging.info(f"[État] barrière={self.etat_barriere}, voitures={self.nombre_voitures}, transition={self.transition}")

    def open_barriere(self):
        """Ouvre la barrière si elle est fermée."""
        with self.lock:
            if self.etat_barriere == "Fermée":
                servo.ouvrir_barriere()
                self.etat_barriere = "Ouverte"
                logging.info("Barrière ouverte → commande servo.")
                self._log_state()

    def close_barriere(self):
        """Ferme la barrière si elle est ouverte."""
        with self.lock:
            if self.etat_barriere == "Ouverte":
                servo.fermer_barriere()
                self.etat_barriere = "Fermée"
                logging.info("Barrière fermée → commande servo.")
                self._log_state()

    def _cancel_entry_timer(self):
        """Annule le timer d’entrée s’il est actif."""
        with self.lock:
            if self.entry_timer is not None and self.entry_timer.is_alive():
                self.entry_timer.cancel()
                logging.info("[Timer ENTREE] annulé.")
            self.entry_timer = None

    def _cancel_exit_timer(self):
        """Annule le timer de sortie s’il est actif."""
        with self.lock:
            if self.exit_timer is not None and self.exit_timer.is_alive():
                self.exit_timer.cancel()
                logging.info("[Timer SORTIE] annulé.")
            self.exit_timer = None

    def _cancel_manual_timer(self):
        """Annule le timer de fermeture manuelle s’il est actif."""
        with self.lock:
            if self.manual_timer is not None and self.manual_timer.is_alive():
                self.manual_timer.cancel()
                logging.info("[Timer MANUEL] annulé.")
            self.manual_timer = None

    def _timeout_entry(self):
        """
        Si le capteur intérieur n’est pas déclenché dans les 3 s
        suite à la détection extérieure → on ferme sans incrémenter.
        """
        with self.lock:
            if self.transition == "entry_pending":
                logging.info("Timeout 3 s pour ENTREE → fermeture automatique, pas d’incrément.")
                self.close_barriere()
                self.transition = None
                self._log_state()

    def _timeout_exit(self):
        """
        Si le capteur extérieur n’est pas déclenché dans les 3 s
        suite à la détection intérieure → on ferme sans décrémenter.
        """
        with self.lock:
            if self.transition == "exit_pending":
                logging.info("Timeout 3 s pour SORTIE → fermeture automatique, pas de décrément.")
                self.close_barriere()
                self.transition = None
                self._log_state()

    def _timeout_manual_close(self):
        """
        5 s après ouverture manuelle, si rien d’autre n’a bougé → on ferme automatiquement.
        """
        with self.lock:
            if self.etat_barriere == "Ouverte" and self.transition is None:
                logging.info("Timeout 5 s après ouverture manuelle → fermeture auto.")
                self.close_barriere()
                self._log_state()
            self.manual_timer = None

    def notify_outside_front(self):
        """
        Appelé sur front montant capteur extérieur :
         - Si on était en "exit_pending", on appelle _complete_exit().
         - Sinon, si barrière fermée et pas de transition, on démarre ENTREE.
        """
        with self.lock:
            logging.info("Front montant détecté par capteur EXTÉRIEUR.")
            # Fin de cycle sortie ?
            if self.transition == "exit_pending":
                self._cancel_exit_timer()
                self._complete_exit()
                return

            # Début de cycle entrée ?
            if self.etat_barriere == "Fermée" and self.transition is None:
                logging.info("Démarrage séquence ENTREE → ouverture barrière.")
                self._cancel_manual_timer()
                self.open_barriere()
                self.transition = "entry_pending"
                # Lance Timer 3 s pour attendre capteur intérieur
                self.entry_timer = threading.Timer(DELAI_SECONDE_CAPTEUR, self._timeout_entry)
                self.entry_timer.daemon = True
                self.entry_timer.start()
                logging.info(f"[Timer ENTREE] lancé pour {DELAI_SECONDE_CAPTEUR}s.")
                self._log_state()

    def notify_inside_front(self):
        """
        Appelé sur front montant capteur intérieur :
         - Si transition=="entry_pending", on complète entrée.
         - Sinon, si barrière fermée, pas de transition, et >0 voitures, on démarre sortie.
        """
        with self.lock:
            logging.info("Front montant détecté par capteur INTÉRIEUR.")
            # Fin de cycle entrée ?
            if self.transition == "entry_pending":
                self._cancel_entry_timer()
                self._complete_entry()
                return

            # Début de cycle sortie ?
            if self.etat_barriere == "Fermée" and self.transition is None and self.nombre_voitures > 0:
                logging.info("Démarrage séquence SORTIE → ouverture barrière.")
                self._cancel_manual_timer()
                self.open_barriere()
                self.transition = "exit_pending"
                # Lance Timer 3 s pour attendre capteur extérieur
                self.exit_timer = threading.Timer(DELAI_SECONDE_CAPTEUR, self._timeout_exit)
                self.exit_timer.daemon = True
                self.exit_timer.start()
                logging.info(f"[Timer SORTIE] lancé pour {DELAI_SECONDE_CAPTEUR}s.")
                self._log_state()

    def notify_outside_front_for_exit(self):
        """
        Appelé sur front montant capteur extérieur en mode sortie :
        on termine sortie (fermeture + décrémentation).
        """
        with self.lock:
            logging.info("Second front montant (extérieur) en mode SORTIE détecté.")
            if self.transition == "exit_pending":
                self._cancel_exit_timer()
                self._complete_exit()

    def _complete_entry(self):
        """Termine la séquence entrée → fermeture + incrémentation."""
        self.close_barriere()
        self.nombre_voitures += 1
        logging.info("Séquence ENTREE terminée → +1 voiture.")
        self.transition = None
        self._log_state()

    def _complete_exit(self):
        """Termine la séquence sortie → fermeture + décrémentation."""
        self.close_barriere()
        self.nombre_voitures -= 1
        logging.info("Séquence SORTIE terminée → -1 voiture.")
        self.transition = None
        self._log_state()

    def can_force_close(self, in_detected: bool, out_detected: bool) -> bool:
        """
        Teste si on peut fermer manuellement : pas de transition et aucun véhicule sous capteur.
        """
        with self.lock:
            logging.info(f"Vérification forçage fermeture → in_detected={in_detected}, "
                         f"out_detected={out_detected}, transition={self.transition}")
            return (self.transition is None) and (not in_detected) and (not out_detected)

    def force_close(self):
        """
        Ferme la barrière manuellement :
         - annule tous les timers,
         - ferme barrière,
         - réinitialise transition.
        """
        with self.lock:
            logging.info("Demande manuelle → fermeture barrière.")
            self._cancel_entry_timer()
            self._cancel_exit_timer()
            self._cancel_manual_timer()
            self.close_barriere()
            self.transition = None
            self._log_state()

    def force_open(self):
        """
        Ouvre la barrière manuellement :
         - annule tous les timers,
         - ouvre barrière,
         - réinitialise transition,
         - lance Timer 5 s pour auto-fermer.
        """
        with self.lock:
            logging.info("Demande manuelle → ouverture barrière.")
            self._cancel_entry_timer()
            self._cancel_exit_timer()
            self._cancel_manual_timer()
            self.open_barriere()
            self.transition = None
            # Timer 5 s pour fermeture auto après ouverture manuelle
            self.manual_timer = threading.Timer(DELAI_FERMETURE_MANUELLE, self._timeout_manual_close)
            self.manual_timer.daemon = True
            self.manual_timer.start()
            logging.info(f"[Timer MANUEL] lancé pour {DELAI_FERMETURE_MANUELLE}s.")
            self._log_state()

    def get_state(self):
        """Renvoie (etat_barriere, nombre_voitures) sous verrou."""
        with self.lock:
            return self.etat_barriere, self.nombre_voitures


# Instancier le manager
manager = ParkingManager()


# === Débounce pour HC-SR04 ===
def is_car_present(sensor: UltrasonicSensor) -> bool:
    """
    Retourne True si, sur LECTURES_DEBOUNCE mesures successives
    espacées de DELAI_DEBOUNCE, au moins 2 mesurent < SEUIL_DISTANCE.
    """
    count = 0
    for _ in range(LECTURES_DEBOUNCE):
        d = sensor.get_distance()
        if d < SEUIL_DISTANCE:
            count += 1
        time.sleep(DELAI_DEBOUNCE)
    presence = (count >= 2)
    logging.debug(f"Debounce → {count}/{LECTURES_DEBOUNCE} mesures < {SEUIL_DISTANCE} cm → presence={presence}")
    return presence


# === Thread capteur EXTÉRIEUR ===
class OutsideSensorThread(threading.Thread):
    """
    Lit en boucle le capteur EXTÉRIEUR. À chaque front montant (False→True),
    il appelle manager.notify_outside_front() ou manager.notify_outside_front_for_exit().
    """
    def __init__(self):
        super().__init__()
        self.daemon = True
        self.prev_detected = False

    def run(self):
        while True:
            curr_detected = is_car_present(sensor_out)
            if not self.prev_detected and curr_detected:
                # Front montant
                if manager.transition == "exit_pending":
                    manager.notify_outside_front_for_exit()
                else:
                    manager.notify_outside_front()
            self.prev_detected = curr_detected
            time.sleep(0.05)


# === Thread capteur INTÉRIEUR ===
class InsideSensorThread(threading.Thread):
    """
    Lit en boucle le capteur INTÉRIEUR. À chaque front montant (False→True),
    il appelle manager.notify_inside_front().
    """
    def __init__(self):
        super().__init__()
        self.daemon = True
        self.prev_detected = False

    def run(self):
        while True:
            curr_detected = is_car_present(sensor_in)
            if not self.prev_detected and curr_detected:
                manager.notify_inside_front()
            self.prev_detected = curr_detected
            time.sleep(0.05)


# === Démarrage des threads AVANT Flask ===
outside_thread = OutsideSensorThread()
inside_thread = InsideSensorThread()
outside_thread.start()
inside_thread.start()


# === Routes Flask ===
@app.route('/')
def index():
    etat, nb = manager.get_state()
    return render_template('index.html',
                           time=time.strftime("%Y-%m-%d %H:%M"),
                           etat=etat,
                           items=nb)


@app.route('/control', methods=['POST'])
def control():
    # Relire capteurs avant action manuelle
    in_detected = is_car_present(sensor_in)
    out_detected = is_car_present(sensor_out)

    # Bouton “Fermer Barrière” ?
    if 'fermer' in request.form:
        if manager.can_force_close(in_detected, out_detected):
            manager.force_close()
        else:
            logging.info("Fermeture manuelle refusée (voiture présente ou séquence en cours).")
        return index()

    # Bouton “Ouvrir Barrière” ?
    if 'ouvrir' in request.form:
        manager.force_open()
        return index()

    return index()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
