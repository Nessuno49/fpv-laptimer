"""Messages the Pi shows to users (errors), in English and German.

Code raises UserError("key", param=value). The web server renders it in the language of the
device that sent the request. Everything else the user reads is built by the browser (web/i18n.js).
"""
LANGUAGES = ("en", "de")
DEFAULT = "en"

MESSAGES = {
    # names
    "name_empty": {"en": "The name must not be empty.", "de": "Der Name darf nicht leer sein."},
    "name_exists": {"en": "“{name}” already exists.", "de": "„{name}“ gibt es schon."},
    "name_exists_archived": {"en": "“{name}” already exists but is archived – tick “Show archived” and reactivate it.",
                             "de": "„{name}“ gibt es schon, ist aber archiviert – „Archivierte anzeigen“ anhaken und "
                                   "reaktivieren."},
    "quad_name_exists": {"en": "This pilot already has a quad called “{name}”.",
                         "de": "Diesen Quad-Namen gibt es bei dem Piloten schon: „{name}“"},
    "pilot_not_found": {"en": "Pilot not found.", "de": "Pilot nicht gefunden."},
    # races
    "race_running": {"en": "A race is already running.", "de": "Es läuft schon ein Rennen."},
    "no_race_running": {"en": "No race is running.", "de": "Es läuft kein Rennen."},
    "finish_race_first": {"en": "Finish the race first.", "de": "Erst das Rennen beenden."},
    "no_participants": {"en": "Please select at least one pilot.", "de": "Bitte mindestens einen Piloten auswählen."},
    "too_many_participants": {"en": "At most {n} participants.", "de": "Höchstens {n} Teilnehmer."},
    "pilot_twice": {"en": "Each pilot can only race once.", "de": "Jeder Pilot kann nur einmal mitfliegen."},
    "quad_not_of_pilot": {"en": "The quad does not belong to the pilot.", "de": "Der Quad passt nicht zum Piloten."},
    "invalid_staging": {"en": "Invalid staging time.", "de": "Ungültige Vorbereitungszeit."},
    "pilot_not_in_race": {"en": "This pilot is not in this race.", "de": "Dieser Pilot fliegt in diesem Lauf nicht mit."},
    "crossing_too_close": {
        "en": "This crossing is only {gap} s away from another one of this pilot – probably detected twice "
              "(e.g. a shadow).",
        "de": "Diese Durchfahrt liegt nur {gap} s neben einer anderen dieses Piloten – vermutlich doppelt "
              "erkannt (z. B. Schatten)."},
    "unassigned_not_found": {"en": "This crossing is no longer open.",
                             "de": "Diese Durchfahrt ist nicht mehr offen."},
    "race_over_assign_in_history": {"en": "The race is already over – please assign it in the race history.",
                                    "de": "Der Lauf ist schon vorbei – bitte im Archiv zuordnen."},
    # sign-in
    "sign_in": {"en": "Please sign in.", "de": "Bitte anmelden."},
    "race_director_only": {"en": "Race director only.", "de": "Nur für den Rennleiter."},
    "pin_format": {"en": "The PIN must have {min} to {max} digits.",
                   "de": "Die PIN muss aus {min} bis {max} Ziffern bestehen."},
    "pin_wrong": {"en": "Wrong PIN.", "de": "Falsche PIN."},
    "pin_locked": {"en": "Too many failed attempts – please wait {s} s.",
                   "de": "Zu viele Fehlversuche – bitte {s} s warten."},
    "pin_not_set": {"en": "The race director PIN has not been set yet. Set it on the Pi: python3 ~/laptimer/pin.py",
                    "de": "Die Rennleiter-PIN ist noch nicht festgelegt. Auf dem Pi einrichten: "
                          "python3 ~/laptimer/pin.py"},
    # camera
    "csi_only": {"en": "This only works with the Camera Module 3.",
                 "de": "Das geht nur mit dem Camera Module 3."},
    "preset_name_empty": {"en": "Please enter a name for the preset.",
                          "de": "Bitte einen Namen für das Profil eingeben."},
    "preset_name_long": {"en": "The name is too long (at most {max} characters).",
                         "de": "Der Name ist zu lang (höchstens {max} Zeichen)."},
    "preset_not_found": {"en": "There is no preset “{name}”.", "de": "Profil „{name}“ gibt es nicht."},
    "photo_not_found": {"en": "Photo not found.", "de": "Foto nicht gefunden."},
    "photo_expired": {"en": "Photo expired.", "de": "Foto abgelaufen."},
    # sounds
    "sound_type": {"en": "Only MP3, WAV or OGG files are allowed.",
                   "de": "Nur MP3-, WAV- oder OGG-Dateien sind erlaubt."},
    "sound_empty": {"en": "The file is empty.", "de": "Die Datei ist leer."},
    "sound_too_big": {"en": "The file is too big (at most {mb} MB).",
                      "de": "Die Datei ist zu groß (höchstens {mb} MB)."},
    "sound_not_found": {"en": "Sound not found.", "de": "Sound nicht gefunden."},
    "unknown_event": {"en": "Unknown event.", "de": "Unbekanntes Ereignis."},
    # voice
    "no_pi_voices": {"en": "No Pi voices set up.", "de": "Keine Pi-Stimmen eingerichtet."},
    "unknown_voice": {"en": "Unknown voice: {voice}", "de": "Unbekannte Stimme: {voice}"},
    "voice_too_slow": {"en": "The voice is taking too long.", "de": "Die Stimme braucht zu lange."},
    # system
    "no_permission_shutdown": {
        "en": "No permission to shut down – set up the permission in /etc/sudoers.d/laptimer on the Pi once.",
        "de": "Keine Berechtigung zum Ausschalten – auf dem Pi einmal die Freigabe in /etc/sudoers.d/laptimer "
              "einrichten."},
    "hotspot_password_format": {"en": "The password needs 8 to 63 characters (letters, digits, spaces and "
                                      "normal symbols, no umlauts).",
                                "de": "Das Passwort braucht 8 bis 63 Zeichen (Buchstaben, Ziffern, Leerzeichen und "
                                      "normale Sonderzeichen, keine Umlaute)."},
    "no_permission_hotspot": {
        "en": "The lap timer may not change the hotspot password yet – install the helper on the Pi once (see README).",
        "de": "Der Laptimer darf das Hotspot-Passwort noch nicht ändern – auf dem Pi einmal das Hilfsskript "
              "einrichten (siehe README)."},
    "hotspot_not_set_up": {"en": "There is no hotspot on this Pi yet (see README).",
                           "de": "Auf diesem Pi ist noch kein Hotspot eingerichtet (siehe README)."},
    "hotspot_password_failed": {"en": "Could not change the hotspot password.",
                                "de": "Das Hotspot-Passwort ließ sich nicht ändern."},
    "not_found": {"en": "Not found.", "de": "Nicht gefunden."},
}


def language(value):
    """Pick a supported language from e.g. "de", "de-DE" or an Accept-Language header."""
    for part in str(value or "").replace(";", ",").split(","):
        code = part.strip()[:2].lower()
        if code in LANGUAGES:
            return code
    return DEFAULT


def text(key, lang=DEFAULT, **params):
    """Message in the given language. Floats get a decimal comma in German."""
    template = MESSAGES.get(key, {}).get(lang) or MESSAGES.get(key, {}).get(DEFAULT) or key
    shown = {}
    for name, value in params.items():
        if isinstance(value, float):
            value = f"{value:.2f}"
            if lang == "de":
                value = value.replace(".", ",")
        shown[name] = value
    return template.format(**shown)


class UserError(ValueError):
    """An error the user should read (in their language). Also a ValueError for older callers."""

    def __init__(self, key, **params):
        self.key, self.params = key, params
        super().__init__(text(key, DEFAULT, **params))

    def text(self, lang):
        return text(self.key, lang, **self.params)
