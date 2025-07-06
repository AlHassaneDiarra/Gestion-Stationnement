import RPi.GPIO as GPIO
import time
from adafruit_servokit import ServoKit

# --- Configuration GPIO globales ---
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)


class UltrasonicSensor:
    """
    Classe pour piloter un capteur HC-SR04 (ultrasons).
    get_distance() renvoie une mesure ponctuelle (en cm).
    """
    def __init__(self, trig_pin: int, echo_pin: int):
        self.trig = trig_pin
        self.echo = echo_pin
        GPIO.setup(self.trig, GPIO.OUT)
        GPIO.setup(self.echo, GPIO.IN)
        GPIO.output(self.trig, False)
        time.sleep(0.05)  # petite pause pour stabiliser

    def get_distance(self) -> float:
        """
        Envoie une impulsion TRIG de 10 µs, puis mesure la durée
        d’écho sur ECHO. Retourne la distance en cm.
        """
        # Génère le pulse TRIG
        GPIO.output(self.trig, True)
        time.sleep(0.00001)  # 10 µs
        GPIO.output(self.trig, False)

        # Attend la montée de ECHO
        start_time = time.time()
        timeout = start_time + 0.02  # timeout 20 ms
        while GPIO.input(self.echo) == 0 and time.time() < timeout:
            start_time = time.time()

        # Attend la descente de ECHO
        stop_time = time.time()
        timeout = stop_time + 0.02
        while GPIO.input(self.echo) == 1 and time.time() < timeout:
            stop_time = time.time()

        # Calcul de la distance (vitesse du son ≈ 34300 cm/s)
        delta = stop_time - start_time
        distance_cm = (delta * 34300) / 2
        return distance_cm


class ServoController:
    """
    Classe pour commander un servo-moteur via PCA9685 (Adafruit ServoKit).
    Canal utilisé : 0 (par défaut). Barrière fermée = 0°, ouverte = 180°.
    """
    def __init__(self, channel: int = 0):
        self.kit = ServoKit(channels=16)
        self.channel = channel
        # Initialise la barrière fermée
        self.kit.servo[self.channel].angle = 0
        self.barriere_fermee = True

    def ouvrir_barriere(self) -> None:
        """Passe l’angle à 180° si la barrière était fermée."""
        if self.barriere_fermee:
            self.kit.servo[self.channel].angle = 180
            self.barriere_fermee = False

    def fermer_barriere(self) -> None:
        """Passe l’angle à 0° si la barrière était ouverte."""
        if not self.barriere_fermee:
            self.kit.servo[self.channel].angle = 0
            self.barriere_fermee = True
