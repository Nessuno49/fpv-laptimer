"""Helper process for speech output – runs in the Piper environment (~/piper-venv).

The lap timer itself runs with the system Python and does not have Piper installed.
So it starts this script with ~/piper-venv/bin/python and sends it jobs:

  one line of JSON per job on stdin, e.g.
    {"kind": "piper", "model": "/home/…/en_US-lessac-high.onnx", "speaker": null,
     "text": "Best lap!", "target": "/home/…/abc.wav"}
  answer: one line of JSON on stdout: {"ok": true} or {"error": "…"}

The models stay loaded so that every further job is quick.
"""
import importlib.util
import json
import os
import sys
import wave

if hasattr(os, "nice"):
    os.nice(10)  # low priority: detection always comes first

MAX_MODELS = 2  # this many Piper models stay in memory at the same time
models = {}


def piper_model(path):
    from piper import PiperVoice
    if path not in models:
        if len(models) >= MAX_MODELS:
            models.pop(next(iter(models)))  # release the oldest
        models[path] = PiperVoice.load(path)
    return models[path]


def piper(job):
    voice = piper_model(job["model"])
    speaker = job.get("speaker")
    with wave.open(job["target"], "wb") as w:
        if hasattr(voice, "synthesize_wav"):   # piper-tts 1.3 and later
            from piper import SynthesisConfig
            voice.synthesize_wav(job["text"], w, syn_config=SynthesisConfig(speaker_id=speaker))
        else:                                   # older versions
            voice.synthesize(job["text"], w, speaker_id=speaker)


def main():
    answers = sys.stdout
    sys.stdout = sys.stderr  # keep library output apart from the answers
    available = {"piper": importlib.util.find_spec("piper") is not None}
    answers.write(json.dumps({"ready": True, **available}) + "\n")
    answers.flush()
    for line in sys.stdin:
        try:
            job = json.loads(line)
            if job["kind"] != "piper":
                raise ValueError(f"Unknown kind: {job['kind']}")
            piper(job)
            answer = {"ok": True}
        except Exception as e:
            answer = {"error": str(e) or e.__class__.__name__}
        answers.write(json.dumps(answer) + "\n")
        answers.flush()


if __name__ == "__main__":
    main()
