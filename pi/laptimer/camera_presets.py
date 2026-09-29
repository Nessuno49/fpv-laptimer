"""Camera presets: save all location-dependent settings under a name and load them again.

Example: "Garage", "Club hall – evening light". Stored in config.json under "camera_presets".
A preset contains the detection zone and thresholds as well as the camera values (exposure, gain,
with the Camera Module 3 also focus, white balance and rotation).
"""
import copy
import datetime

from i18n import UserError

MAX_NAME = 40
DETECTION = ("zone", "pixel_threshold", "min_size")
CSI = ("exposure_ms", "gain", "focus_m", "white_balance", "rotation")


def check_name(name):
    name = " ".join(str(name or "").split())
    if not name:
        raise UserError("preset_name_empty")
    if len(name) > MAX_NAME:
        raise UserError("preset_name_long", max=MAX_NAME)
    return name


def from_config(cfg, now=None):
    """The current settings as a preset."""
    preset = {k: copy.deepcopy(cfg[k]) for k in DETECTION}
    if cfg.get("camera") == "csi":
        preset.update({k: copy.deepcopy(cfg["csi"].get(k)) for k in CSI})
    else:
        preset["exposure_ms"] = cfg["webcam"]["v4l2"]["exposure_time_absolute"] / 10
        preset["gain"] = cfg["webcam"]["v4l2"]["gain"]
    preset["camera"] = cfg.get("camera", "webcam")
    preset["saved"] = (now or datetime.datetime.now()).isoformat(timespec="minutes")
    return preset


def save(cfg, name, now=None):
    name = check_name(name)
    cfg.setdefault("camera_presets", {})[name] = from_config(cfg, now)
    return name


def load(cfg, name):
    """Take a preset into the config. Returns the values for camera.adjust(...)."""
    preset = cfg.get("camera_presets", {}).get(name)
    if preset is None:
        raise UserError("preset_not_found", name=name)
    for k in DETECTION:
        cfg[k] = copy.deepcopy(preset[k])
    camera_values = {"exposure_ms": preset["exposure_ms"], "gain": preset["gain"]}
    if cfg.get("camera") == "csi":
        for k in CSI:
            value = preset.get(k)
            if value is not None or k == "white_balance":  # white balance None = automatic
                cfg["csi"][k] = copy.deepcopy(value)
        camera_values["focus_m"] = cfg["csi"]["focus_m"]
        camera_values["white_balance"] = cfg["csi"]["white_balance"]
        camera_values["rotation"] = cfg["csi"].get("rotation", 0)
    else:
        cfg["webcam"]["v4l2"]["exposure_time_absolute"] = max(1, round(preset["exposure_ms"] * 10))
        cfg["webcam"]["v4l2"]["gain"] = int(preset["gain"])
    return camera_values


def delete(cfg, name):
    if cfg.get("camera_presets", {}).pop(name, None) is None:
        raise UserError("preset_not_found", name=name)


def list_presets(cfg):
    """All presets, newest first."""
    presets = cfg.get("camera_presets", {})
    return sorted(({"name": n, **p} for n, p in presets.items()), key=lambda p: p["saved"], reverse=True)
