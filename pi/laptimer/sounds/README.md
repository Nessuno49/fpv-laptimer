# Sound library

Your own sounds go here (`.mp3`, `.wav`, `.ogg`, at most 5 MB per file).

**Easiest:** in the browser under *Settings → Sound & voice* click a tile and choose
"Upload file". The file then lands here automatically and is assigned to the event.

**Or with scp from the PC**, then reload the page:

    scp mysound.mp3 pi@laptimer.local:~/laptimer/sounds/

Which sound plays for which event is stored in `config.json` under `sound_mapping`
and applies to all devices. Without a mapping the built-in tone plays.
