"""Open the camera, adjust it and deliver images.

Two kinds (config.json "camera"):
  "csi"     Raspberry Pi Camera Module 3 on the ribbon cable (picamera2). Delivers two images
            at once: a small one for detection (fast) and a large one for the photos.
  "webcam"  USB webcam via V4L2 (OpenCV).

Both have the same interface:
  captures()      endless sequence of Capture(image, t, photo_image): image for detection (BGR),
                  t = capture time in seconds (time.monotonic), photo_image = large image for photos
                  or None. Whoever gets a capture must hand it back with .release() –
                  also from another thread (so fetching and processing can run in parallel).
  frames()        the same as (image, t, photo_image) – the capture is released at the next image
  adjust(...)     change exposure (ms), gain and (Camera Module 3 only) focus
  calibrate()     (Camera Module 3 only) find exposure and white balance automatically, then freeze them
  actual()        values the camera is really using right now
  limits          value ranges for the sliders in the UI
  delivered, lost counters: images from the camera / images lost on the way
  time_source     where the timestamps come from ("camera" or "system")
"""
import subprocess
import time
from dataclasses import dataclass

SENSOR_CSI = (1536, 864)  # sensor mode of the Camera Module 3 that can do up to 120 images/s
MAX_GAIN_CSI = 16.0
CALIBRATE_S = 2.0          # the automatic may search this long
CALIBRATE_MAX_MS = 4.0     # longer exposure blurs fast quads -> rather more gain


def open_camera(cfg):
    """Opens the camera as configured."""
    if cfg.get("camera", "webcam") == "csi":
        return Csi(cfg["csi"])
    return Webcam(cfg["webcam"])


def rotate(image, degrees):
    """Rotate an image clockwise (0, 90, 180, 270 degrees)."""
    if not degrees:
        return image
    import cv2
    code = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}[degrees]
    return cv2.rotate(image, code)


def rotate_zone(zone, width, height, steps):
    """Rotate the detection zone [x, y, w, h] along – 90° clockwise per step.

    width/height: size of the image the zone currently lies in.
    """
    x, y, w, h = zone
    for _ in range(steps % 4):
        x, y, w, h = height - (y + h), x, h, w
        width, height = height, width
    return [x, y, w, h]


@dataclass
class Capture:
    image: object
    t: float
    photo_image: object = None
    _request: object = None

    def release(self):
        """Give the buffer back to the camera. After this, photo_image is no longer valid."""
        if self._request is not None:
            self._request.release()
            self._request = None


def _frames(camera):
    """captures() as (image, t, photo_image) – each capture is released at the next image."""
    for c in camera.captures():
        try:
            yield c.image, c.t, c.photo_image
        finally:
            c.release()


def _time(ts):
    """Timestamp of the camera if it matches the system clock (otherwise the system clock)."""
    now = time.monotonic()
    return (ts, "camera") if 0 <= now - ts < 1.0 else (now, "system")


_UNCHANGED = object()  # placeholder: value was not passed


# ---------------------------------------------------------------- Camera Module 3

class Csi:
    limits = {"exposure_ms": (0.1, 10.0, 0.1), "gain": (1.0, MAX_GAIN_CSI, 0.1), "focus_m": (0.3, 5.0, 0.1)}

    def __init__(self, cfg, picamera2_module=None):
        if picamera2_module is None:
            import picamera2 as picamera2_module
        self.cfg = cfg
        self.delivered = self.lost = 0
        self.time_source = "–"
        self._metadata = {}   # of the newest image
        self.picam2 = picamera2_module.Picamera2()
        self.fps = float(cfg["fps"])
        self.rotation = int(cfg.get("rotation", 0))  # rotate the image this many degrees clockwise
        config = self.picam2.create_video_configuration(
            main={"size": tuple(cfg["photo_size"]), "format": "RGB888"},  # RGB888 = BGR order like OpenCV
            lores={"size": tuple(cfg["detection_size"]), "format": "YUV420"},
            sensor={"output_size": SENSOR_CSI, "bit_depth": 10},
            buffer_count=8, controls=self._controls())  # fetching and processing each hold a few buffers
        self.picam2.configure(config)
        self.picam2.start()

    def _controls(self):
        cfg, available = self.cfg, self.picam2.camera_controls
        duration_us = round(1e6 / self.fps)
        c = {"FrameDurationLimits": (duration_us, duration_us)}
        c.update(self._manual(cfg["exposure_ms"], cfg["gain"], cfg.get("white_balance")))
        if "NoiseReductionMode" in available:
            # colour noise filter off: the Pi 4's ISP can't keep up with it at high frame rates
            from libcamera import controls
            c["NoiseReductionMode"] = controls.draft.NoiseReductionModeEnum.Minimal
        c.update(self._focus(cfg.get("focus_m")))
        return c

    def _manual(self, exposure_ms, gain, white_balance=None):
        """Controls for fixed exposure, fixed gain and (if known) fixed white balance."""
        available = self.picam2.camera_controls
        c = {"ExposureTime": min(round(float(exposure_ms) * 1000), round(1e6 / self.fps)),
             "AnalogueGain": float(gain)}
        if "ExposureTimeMode" in available:  # newer libcamera: switch off the automatic per value
            from libcamera import controls
            c["ExposureTimeMode"] = controls.ExposureTimeModeEnum.Manual
            c["AnalogueGainMode"] = controls.AnalogueGainModeEnum.Manual
        else:
            c["AeEnable"] = False
        if white_balance:
            c["AwbEnable"] = False
            c["ColourGains"] = (float(white_balance[0]), float(white_balance[1]))
        return c

    def _focus(self, focus_m):
        if not focus_m or "AfMode" not in self.picam2.camera_controls:
            return {}
        # focus fixed at the distance to the gate (LensPosition in dioptres = 1 / metres)
        from libcamera import controls
        return {"AfMode": controls.AfModeEnum.Manual, "LensPosition": 1.0 / float(focus_m)}

    def set_rotation(self, degrees):
        """Rotate this many degrees from the next image on (in software, takes effect at once)."""
        self.cfg["rotation"] = self.rotation = int(degrees) % 360

    def adjust(self, exposure_ms=None, gain=None, focus_m=None, white_balance=_UNCHANGED, rotation=None):
        """white_balance: [red, blue] = fixed, None = automatic, left out = as before."""
        c = {}
        if exposure_ms is not None:
            self.cfg["exposure_ms"] = exposure_ms
        if gain is not None:
            self.cfg["gain"] = gain
        if white_balance is not _UNCHANGED:
            self.cfg["white_balance"] = white_balance
            if white_balance is None:
                c["AwbEnable"] = True
        if exposure_ms is not None or gain is not None or white_balance is not _UNCHANGED:
            c.update(self._manual(self.cfg["exposure_ms"], self.cfg["gain"], self.cfg.get("white_balance")))
        if focus_m is not None:
            self.cfg["focus_m"] = focus_m
            c.update(self._focus(focus_m))
        if rotation is not None:
            self.set_rotation(rotation)
        if c:
            self.picam2.set_controls(c)

    def calibrate(self, duration_s=CALIBRATE_S, max_ms=CALIBRATE_MAX_MS):
        """Automatic on briefly, freeze the values found. Returns {exposure_ms, gain, white_balance}."""
        available = self.picam2.camera_controls
        auto = {"AwbEnable": True}
        if "ExposureTimeMode" in available:
            from libcamera import controls
            auto["ExposureTimeMode"] = controls.ExposureTimeModeEnum.Auto
            auto["AnalogueGainMode"] = controls.AnalogueGainModeEnum.Auto
        else:
            auto["AeEnable"] = True
        if "AeExposureMode" in available:  # prefer short exposure times
            from libcamera import controls
            auto["AeExposureMode"] = controls.AeExposureModeEnum.Short
        self.picam2.set_controls(auto)
        time.sleep(duration_s)
        md = dict(self._metadata)
        exposure_ms = md.get("ExposureTime", self.cfg["exposure_ms"] * 1000) / 1000
        gain = md.get("AnalogueGain", self.cfg["gain"])
        white_balance = md.get("ColourGains")
        if exposure_ms > max_ms:  # same brightness with shorter exposure and more gain
            gain = gain * exposure_ms / max_ms
            exposure_ms = max_ms
        gain = min(max(gain, 1.0), MAX_GAIN_CSI)
        values = {"exposure_ms": round(exposure_ms, 2), "gain": round(gain, 2),
                  "white_balance": [round(float(v), 3) for v in white_balance] if white_balance else None}
        self.cfg.update(values)
        self.picam2.set_controls(self._manual(values["exposure_ms"], values["gain"], values["white_balance"]))
        return values

    def actual(self):
        md = self._metadata
        lens = md.get("LensPosition")
        return {"exposure_ms": round(md["ExposureTime"] / 1000, 2) if "ExposureTime" in md else None,
                "gain": round(md["AnalogueGain"], 2) if "AnalogueGain" in md else None,
                "white_balance": [round(v, 2) for v in md["ColourGains"]] if "ColourGains" in md else None,
                "focus_m": round(1 / lens, 2) if lens else None}

    def captures(self):
        import cv2
        pw, ph = self.cfg["photo_size"]
        frame_ns = 1e9 / self.fps
        previous = None
        while True:
            request = self.picam2.capture_request()
            try:
                self._metadata = request.get_metadata()
                ts_ns = self._metadata["SensorTimestamp"]
                if previous is not None:
                    self.lost += max(0, round((ts_ns - previous) / frame_ns) - 1)
                previous = ts_ns
                self.delivered += 1
                t, self.time_source = _time(ts_ns / 1e9)
                # make_array (not MappedArray): only this way the colours are right – checked on the Pi
                image = cv2.cvtColor(request.make_array("lores"), cv2.COLOR_YUV2BGR_I420)
                rotation = self.rotation
                capture = Capture(rotate(image, rotation), t, _LargeImage(request, pw, ph, rotation), request)
            except BaseException:
                request.release()
                raise
            yield capture  # from here on the receiver hands the buffer back with capture.release()

    def frames(self):
        return _frames(self)

    def close(self):
        try:
            self.picam2.stop()
        finally:
            self.picam2.close()


class _LargeImage:
    """The large image is only copied when someone looks into it (only at crossings).

    Behaves like an array for the detector: .shape and cropping with [y0:y1, x0:x1].
    """

    def __init__(self, request, width, height, rotation=0):
        self._request, self._array = request, None
        self._size, self._rotation = (width, height), rotation
        self.shape = (width, height, 3) if rotation in (90, 270) else (height, width, 3)

    def __getitem__(self, index):
        if self._array is None:
            width, height = self._size
            self._array = rotate(self._request.make_array("main")[:height, :width], self._rotation)
        return self._array[index]


# ---------------------------------------------------------------- USB webcam

def v4l2_set(device, name, value):
    result = subprocess.run(
        ["v4l2-ctl", "-d", f"/dev/video{device}", "-c", f"{name}={value}"],
        capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Warning: {name}={value} not set: {result.stderr.strip()}", flush=True)


class Webcam:
    limits = {"exposure_ms": (1.0, 30.0, 0.5), "gain": (0, 255, 1)}

    def __init__(self, cfg):
        """Opens the webcam (uncompressed YUYV) and sets the v4l2 values."""
        import cv2  # only load here: v4l2_set also works without OpenCV
        self.device = cfg["device"]
        self.delivered = self.lost = 0
        self.time_source = "–"
        self.cap = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
        if not self.cap.isOpened():
            raise SystemExit(f"Cannot open camera /dev/video{self.device}.")
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"YUYV"))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg["width"])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg["height"])
        self.cap.set(cv2.CAP_PROP_FPS, cfg["fps"])
        for name, value in cfg["v4l2"].items():
            v4l2_set(self.device, name, value)

    def adjust(self, exposure_ms=None, gain=None, **_):  # the webcam can't do focus/white balance
        if exposure_ms is not None:
            v4l2_set(self.device, "exposure_time_absolute", max(1, round(exposure_ms * 10)))
        if gain is not None:
            v4l2_set(self.device, "gain", int(gain))

    def captures(self):
        import cv2
        while True:
            ok, image = self.cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            self.delivered += 1
            # timestamp from the camera driver (time of capture); it must match the race controller's
            # clock (time.monotonic), otherwise the driver uses a different time base.
            t, self.time_source = _time(self.cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0)
            yield Capture(image, t)

    def frames(self):
        return _frames(self)

    def close(self):
        self.cap.release()
