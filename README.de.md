# FPV Laptimer

**Rundenzeitmessung per Kamera für FPV-Rennen – bis zu 8 Piloten, nichts muss an die Copter.**

[English version](README.md) · Stand: **experimentell**

## Warum dieses Projekt

Dieses Projekt ist weit davon entfernt, perfekt zu sein. Ich habe es angefangen, weil der
RX5808-Empfängerchip – mit dem klassische FPV-Laptimer wie RotorHazard das Videosignal der Piloten
messen – sehr teuer geworden ist. Also habe ich etwas anderes ausprobiert: eine Kamera am Gate.

Ich habe zu Hause viele Tests gemacht und bisher einen Live-Test mit drei Piloten gleichzeitig.
Die Ergebnisse waren vielversprechend, aber ich erhebe keinen Anspruch darauf, ein fertiges Tool
entwickelt zu haben.

**Jeder ist eingeladen, an diesem Projekt mitzuarbeiten und es weiterzuentwickeln.** Besonders
willkommen ist Hilfe bei:

- Tests mit schnelleren Coptern (5 Zoll) und draußen (Sonne, Schatten, Wind),
- anderer Hardware (z. B. Raspberry Pi 5, andere Kameras),
- Coptern, die sich sehr ähnlich sehen,
- weiteren Sprachen für Oberfläche und Ansagen,
- allem anderen, was euch auffällt – Fehler, Ideen, bessere Erklärungen.

Probleme und Ideen bitte als [Issue](../../issues) melden, Verbesserungen als Pull Request schicken.

## Was es kann

Ein Raspberry Pi mit Kamera beobachtet das Gate mit 100 Bildern pro Sekunde. Jeder Copter, der
durchfliegt, wird erkannt, an seinem Aussehen wiedererkannt (Farb-Fingerabdruck + ein kleines
vortrainiertes neuronales Netz) und seinem Piloten zugeordnet. Rennleiter, Piloten und Zuschauer
verfolgen alles live im Browser auf dem Handy – mit Sprachansagen, Statistik und Archiv. Das klappt mit
jedem Copter, auch mit digitalen DJI-Coptern, weil das Videosignal gar nicht gebraucht wird.

- **Rennformate:** Training, X Runden, Zeitrennen, beste N Runden in Folge, schnellste Runde.
  Holeshot, Mindest-Rundenzeit, Nachspielzeit, Vorbereitungszeit (15–60 s zum Brille-Aufsetzen).
- **Bis zu 8 Piloten pro Lauf**, automatisch erkannt. Durchfahrten, die nicht sicher zuzuordnen sind,
  ordnet man von Hand zu – live oder später im Archiv.
- **Sprachansagen** auf Deutsch oder Englisch auf jedem Handy: vom Browser des Handys oder mit natürlichen
  Piper-Stimmen, die der Pi erzeugt. Piloten können nur ihre eigenen Zeiten hören. Eigene Soundeffekte lassen
  sich hochladen.
- **Statistik** pro Track und für Spontane Kurse: Ranglisten, persönliche Bestzeiten, Rekorde, Fortschrittskurven.
- **Rennleiter und Zuschauer:** Der Rennleiter meldet sich mit PIN an, Zuschauer sehen nur zu.
- **Überall einsetzbar:** Mit Netzwerkkabel hängt der Pi im Heimnetz, ohne Kabel macht er ein eigenes
  WLAN auf, dessen Anmeldeseite sich auf den Handys von selbst öffnet.
- **Willkommensseite, Schnellstart und ⓘ-Erklärungen** in der Oberfläche; Sprache pro Gerät (Deutsch oder Englisch).

## Hardware

Gebaut und getestet mit einem **Raspberry Pi 4 B (2 GB)** und dem **Raspberry Pi Camera Module 3**.
Andere Modelle (z. B. Pi 5) sollten gehen, sind aber nicht getestet.

## Installation auf dem Pi

Raspberry Pi OS Lite (64 Bit, Bookworm oder neuer), Benutzer mit SSH-Zugang. Jeder Befehl ist eine Zeile.

**1. Pakete**

```
sudo apt update
```
```
sudo apt install -y python3-opencv python3-numpy nftables v4l-utils ffmpeg
```
```
sudo apt install -y python3-picamera2 --no-install-recommends
```

**2. Programm kopieren** – vom PC aus, im Ordner dieses Projekts:

```
scp -r pi/laptimer pi/network pi/laptimer.service pi@laptimer.local:~/
```

(`pi` durch deinen Benutzernamen auf dem Pi ersetzen.)

**3. Autostart** – auf dem Pi:

```
mkdir -p ~/.config/systemd/user
```
```
cp ~/laptimer.service ~/.config/systemd/user/
```
```
systemctl --user enable --now laptimer
```
```
loginctl enable-linger $USER
```

Der letzte Befehl sorgt dafür, dass der Laptimer beim Booten startet, ohne dass sich jemand anmeldet.

**4. Rennleiter-PIN** (am besten 6 Ziffern oder mehr)

```
python3 ~/laptimer/pin.py
```

Dann im Browser **http://laptimer.local:8080** öffnen.

**5. Port 80 (optional):** damit die Adresse ohne `:8080` geht:

```
sudo install -m 644 ~/network/99-laptimer-port80.conf /etc/sysctl.d/99-laptimer-port80.conf
```
```
sudo sysctl --system
```

**6. Ausschalt-Knopf:** Die Knöpfe in den Einstellungen dürfen den Pi ausschalten. Fragt `sudo` auf deinem
Pi nach einem Passwort, gib nur diese zwei Befehle frei (`pi` durch deinen Benutzernamen ersetzen):

```
echo "pi ALL=(root) NOPASSWD: /usr/bin/systemctl poweroff, /usr/bin/systemctl reboot" | sudo tee /etc/sudoers.d/laptimer
```
```
sudo chmod 440 /etc/sudoers.d/laptimer
```

### Stimmen auf dem Pi (optional)

Ohne diesen Schritt sprechen die Browser-Stimmen der Handys. Für natürliche Stimmen Piper in einer eigenen Umgebung installieren:

```
python3 -m venv ~/piper-venv
```
```
~/piper-venv/bin/pip install piper-tts
```
```
mkdir -p ~/voices && cd ~/voices
```
```
~/piper-venv/bin/python -m piper.download_voices de_DE-thorsten-high de_DE-thorsten_emotional-medium en_US-lessac-medium
```

Die Stimme wählt man in den Einstellungen (die Liste zeigt die Stimmen zur Sprache der Oberfläche).
Eine Stimme vorzubereiten dauert einmalig ein paar Minuten, danach kommen die Ansagen sofort. Alle Stimmen
auf einmal vorbereiten: `python3 ~/laptimer/prepare_voices.py`.

### Hotspot, wenn das Kabel fehlt (optional)

Hotspot anlegen – **mit einem eigenen Passwort**:

```
sudo nmcli connection add type wifi ifname wlan0 con-name Laptimer-Hotspot autoconnect no ssid Laptimer 802-11-wireless.mode ap 802-11-wireless.band bg 802-11-wireless.channel 1 ipv4.method shared wifi-sec.key-mgmt wpa-psk wifi-sec.proto rsn wifi-sec.pairwise ccmp wifi-sec.group ccmp wifi-sec.psk choose-your-own-password
```

Die Skripte installieren, die ihn mit dem Kabel ein- und ausschalten und dafür sorgen, dass die Handys den Laptimer von selbst öffnen:

```
sudo install -m 755 ~/network/laptimer-hotspot /usr/local/bin/laptimer-hotspot
```
```
sudo install -m 755 ~/network/90-laptimer-hotspot /etc/NetworkManager/dispatcher.d/90-laptimer-hotspot
```
```
sudo install -m 644 ~/network/laptimer-dns.conf /etc/NetworkManager/dnsmasq-shared.d/laptimer.conf
```
```
sudo install -m 644 ~/network/laptimer-portal.nft /etc/laptimer-portal.nft
```
```
sudo install -m 644 ~/network/laptimer-hotspot.service /etc/systemd/system/laptimer-hotspot.service
```
```
sudo systemctl enable laptimer-hotspot
```

Damit sich das Passwort später auch in den Einstellungen ändern lässt (⚙ → Hotspot), das kleine Hilfsskript
installieren und freigeben (`pi` durch deinen Benutzernamen ersetzen):

```
sudo install -m 755 ~/network/laptimer-hotspot-password /usr/local/bin/laptimer-hotspot-password
```
```
echo "pi ALL=(root) NOPASSWD: /usr/local/bin/laptimer-hotspot-password" | sudo tee -a /etc/sudoers.d/laptimer
```
```
sudo chmod 440 /etc/sudoers.d/laptimer
```

Im Hotspot ist der Laptimer unter **http://10.42.0.1** erreichbar – die meisten Handys öffnen ihn von selbst („Im Netzwerk anmelden“).
Auch SSH geht dort: `ssh pi@10.42.0.1` (Internet hat der Pi im Hotspot allerdings nicht).
Ein Schild mit WLAN-QR-Code zum 3D-Drucken erzeugt [tools/qr_stl.py](tools/qr_stl.py)
(vorher das eigene Hotspot-Passwort im Skript eintragen).

## Erste Schritte

Die Willkommensseite in der Oberfläche (Klick auf „🏁 Laptimer“) führt durch:

1. **Kamera:** *Kamera einmessen* drücken, den Erkennungsbereich knapp hinter die Gate-Öffnung ziehen
   (dort kommt jeder Copter durch, und Banner oder Fahnen am Gate bleiben draußen – so breit, dass kein
   Copter daran vorbeifliegt, und kein anderer Teil der Strecke darf hindurchführen), Abstand zum Gate einstellen.
2. **Piloten & Tracks:** Piloten, Copter und – für einen festen Kurs – einen Track anlegen.
3. **Mit jedem Copter ein paar Runden allein fliegen** (Training) – daraus lernt die Erkennung die Copter.
   Copter, die zusammen fliegen, müssen unterschiedlich aussehen (Canopy- oder Prop-Farbe).
4. **Rennen:** Format, Track und Teilnehmer wählen, starten.

## Aktualisieren

Das neue `pi/laptimer` erst in einen eigenen Ordner kopieren, dann über das alte – Datenbank, Einstellungen
und Fotos bleiben erhalten:

```
scp -r pi/laptimer pi@laptimer.local:~/laptimer-new
```
```
cp -r ~/laptimer-new/. ~/laptimer/ && rm -rf ~/laptimer-new
```
```
systemctl --user restart laptimer
```

## Entwicklung

Die Logik läuft auch ohne Pi. Tests (Python 3.11+, NumPy; OpenCV optional):

```
cd pi/laptimer && python -m unittest discover -s tests
```

| Ordner | Inhalt |
|---|---|
| `pi/laptimer/` | das Programm: `laptimer.py` (Start), `race.py`, `detector.py`, `camera.py`, `database.py`, `webserver.py`, … |
| `pi/laptimer/web/` | die Browser-Oberfläche (`app.js`, Texte in `i18n.js`) |
| `pi/network/` | Hotspot und Anmeldeseite |
| `tools/` | Hilfsskripte für den PC |

## Lizenz

Dieses Projekt steht unter der **GNU General Public License v3.0** – siehe [LICENSE](LICENSE).
Du darfst es nutzen, ändern und weitergeben; gibst du eine veränderte Version weiter, muss deren Quellcode
ebenfalls unter der GPL offen sein.

Bestandteile von anderen:

- **MobileNetV2** (`pi/laptimer/models/mobilenetv2-12.onnx`) aus dem ONNX Model Zoo – Apache License 2.0,
  siehe [pi/laptimer/models/README.md](pi/laptimer/models/README.md).
- **Zahnrad-Symbol** von [Lucide](https://lucide.dev) – ISC-Lizenz.
- Genutzt, aber nicht enthalten: OpenCV (Apache 2.0), NumPy (BSD), picamera2 (BSD), Piper (GPL-3.0) und
  seine Stimmen (jede Stimme hat ihre eigene Lizenz, siehe ihre Modellkarte).
