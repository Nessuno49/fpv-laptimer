# FPV Laptimer

**Camera-based lap timer for FPV races – up to 8 pilots, nothing to mount on the quads.**

[Deutsche Version](README.de.md) · Status: **experimental**

## Why this project

This project is far from perfect. I started it because the RX5808 receiver chip – which classic FPV
lap timers such as RotorHazard use to pick up the pilots' video signal – has become very expensive.
So I tried something different: a camera at the gate.

I have run many tests at home and so far one live test with three pilots flying at the same time.
The results were promising, but I don't claim to have built a finished tool.

**Everybody is invited to work on this project and develop it further.** Help is especially welcome with:

- tests with faster quads (5 inch) and outdoors (sun, shadows, wind),
- other hardware (e.g. Raspberry Pi 5, other cameras),
- telling apart quads that look very much alike,
- more languages for the interface and the callouts,
- anything else you notice – bugs, ideas, better explanations.

Report problems and ideas as an [issue](../../issues), send improvements as a pull request.

## What it does

A Raspberry Pi with a camera watches the gate at 100 images per second. Every quad flying through is
detected, recognised by its look (colour fingerprint + a small pre-trained neural network) and assigned
to its pilot. Race director, pilots and spectators follow everything live in the browser on their
phones – with voice callouts, statistics and a race history. It works with any quad, including DJI
digital ones, because it doesn't use the video signal at all.

- **Race formats:** practice, first to X laps, most laps in X minutes, fastest N consecutive laps,
  fastest lap. Holeshot, minimum lap time, grace period, staging time (15–60 s to put on the goggles).
- **Up to 8 pilots per race**, recognised automatically. Crossings that can't be assigned safely can be
  assigned by hand – live or later in the race history.
- **Voice callouts** in English or German on every phone: from the phone's browser, or with natural Piper
  voices generated on the Pi. Pilots can choose to hear only their own times. Own sound effects can be uploaded.
- **Statistics** per track and for pop-up courses: leaderboards, personal bests, track records, progress charts.
- **Race director and spectators:** the race director signs in with a PIN; spectators only watch.
- **Works anywhere:** with a network cable the Pi joins your home network; without it, it opens its own
  Wi-Fi hotspot with a sign-in page that opens by itself on the phones.
- **Welcome page, quick start and ⓘ explanations** in the interface; language per device (English or German).

## Hardware

Built and tested with a **Raspberry Pi 4 B (2 GB)** and the **Raspberry Pi Camera Module 3**.
Other models (e.g. Pi 5) should work but are untested.

## Installation on the Pi

Raspberry Pi OS Lite (64-bit, Bookworm or later), user with SSH access. Each command is one line.

**1. Packages**

```
sudo apt update
```
```
sudo apt install -y python3-opencv python3-numpy nftables v4l-utils ffmpeg
```
```
sudo apt install -y python3-picamera2 --no-install-recommends
```

**2. Copy the program** – from your computer, in the folder of this project:

```
scp -r pi/laptimer pi/network pi/laptimer.service pi@laptimer.local:~/
```

(Replace `pi` with your user name on the Pi.)

**3. Autostart** – on the Pi:

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

The last command lets the lap timer start at boot without anyone logging in.

**4. Race director PIN** (6 or more digits recommended)

```
python3 ~/laptimer/pin.py
```

Then open **http://laptimer.local:8080** in the browser.

**5. Port 80 (optional):** so the address works without `:8080`:

```
sudo install -m 644 ~/network/99-laptimer-port80.conf /etc/sysctl.d/99-laptimer-port80.conf
```
```
sudo sysctl --system
```

**6. Shutdown button:** the buttons in the settings may switch off the Pi. If `sudo` asks for a password
on your Pi, allow just these two commands (replace `pi` with your user name):

```
echo "pi ALL=(root) NOPASSWD: /usr/bin/systemctl poweroff, /usr/bin/systemctl reboot" | sudo tee /etc/sudoers.d/laptimer
```
```
sudo chmod 440 /etc/sudoers.d/laptimer
```

### Voices on the Pi (optional)

Without this the phones' own browser voices speak. For natural voices install Piper in its own environment:

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
~/piper-venv/bin/python -m piper.download_voices en_US-lessac-medium en_GB-alan-medium de_DE-thorsten-high
```

Choose the voice in the settings (the list shows the voices for the interface language). Preparing a voice
takes a few minutes once; afterwards callouts come instantly. To prepare all voices at once:
`python3 ~/laptimer/prepare_voices.py`.

### Hotspot when the cable is unplugged (optional)

Create the hotspot – **with a password of your own**:

```
sudo nmcli connection add type wifi ifname wlan0 con-name Laptimer-Hotspot autoconnect no ssid Laptimer 802-11-wireless.mode ap 802-11-wireless.band bg 802-11-wireless.channel 1 ipv4.method shared wifi-sec.key-mgmt wpa-psk wifi-sec.proto rsn wifi-sec.pairwise ccmp wifi-sec.group ccmp wifi-sec.psk choose-your-own-password
```

Install the scripts that switch it on and off with the cable and make the phones open the lap timer by themselves:

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

So the password can also be changed later in the settings (⚙ → Hotspot), install the small helper and allow it
(replace `pi` with your user name):

```
sudo install -m 755 ~/network/laptimer-hotspot-password /usr/local/bin/laptimer-hotspot-password
```
```
echo "pi ALL=(root) NOPASSWD: /usr/local/bin/laptimer-hotspot-password" | sudo tee -a /etc/sudoers.d/laptimer
```
```
sudo chmod 440 /etc/sudoers.d/laptimer
```

In the hotspot the lap timer is at **http://10.42.0.1** – most phones open it by themselves ("Sign in to network").
SSH works there too: `ssh pi@10.42.0.1` (the Pi has no internet in the hotspot, though).
A sign with a Wi-Fi QR code for 3D printing can be made with [tools/qr_stl.py](tools/qr_stl.py)
(enter your hotspot password in the script first).

## First steps

The welcome page in the interface (click on "🏁 Laptimer") walks you through it:

1. **Camera:** press *Calibrate camera*, drag the detection zone just behind the gate opening
   (every quad passes there, and banners or flags fluttering on the gate stay outside – wide enough that
   no quad flies past it, and no other part of the course may cross it), set the distance to the gate.
2. **Pilots & Tracks:** add pilots, quads and – for a fixed course – a track.
3. **Fly alone a few laps per quad** in practice – the recognition learns the quads from these flights.
   Quads racing together must look different (canopy or prop colour).
4. **Race:** choose format, track and participants, start.

## Updating

Copy the new `pi/laptimer` into a separate folder first, then over the old one – database, settings and
photos stay:

```
scp -r pi/laptimer pi@laptimer.local:~/laptimer-new
```
```
cp -r ~/laptimer-new/. ~/laptimer/ && rm -rf ~/laptimer-new
```
```
systemctl --user restart laptimer
```

## Development

The logic runs without the Pi. Tests (Python 3.11+, NumPy; OpenCV optional):

```
cd pi/laptimer && python -m unittest discover -s tests
```

| Folder | Contents |
|---|---|
| `pi/laptimer/` | the program: `laptimer.py` (start), `race.py`, `detector.py`, `camera.py`, `database.py`, `webserver.py`, … |
| `pi/laptimer/web/` | the browser interface (`app.js`, texts in `i18n.js`) |
| `pi/network/` | hotspot and captive portal |
| `tools/` | helper scripts for the PC |

## License

This project is licensed under the **GNU General Public License v3.0** – see [LICENSE](LICENSE).
You may use, change and share it; if you pass on a changed version, its source code has to be open
under the GPL as well.

Parts by others:

- **MobileNetV2** (`pi/laptimer/models/mobilenetv2-12.onnx`) from the ONNX Model Zoo – Apache License 2.0,
  see [pi/laptimer/models/README.md](pi/laptimer/models/README.md).
- **Gear icon** from [Lucide](https://lucide.dev) – ISC License.
- Used but not included: OpenCV (Apache 2.0), NumPy (BSD), picamera2 (BSD), Piper (GPL-3.0) and its voices
  (each voice has its own license, see its model card).
