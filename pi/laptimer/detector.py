"""Object detection in the detection zone.

Per camera image:
  1. Compare with the learned background -> changed pixels. The comparison is
     in colour: even a quad exactly as bright as the background stands out.
  2. Join pixels lying close together into blobs (frame + props = one quad),
     drop blobs below the minimum size
  3. Link blobs over several images into tracks. Each track = one crossing.
  4. When a track ends (not seen for 0.3 s), the image with the largest
     blob is saved as a photo and on_crossing(Crossing) is called.
     The time of the crossing is the first image of the track.
"""
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import cv2
import numpy as np

import fingerprint
from race import Crossing

TRACK_END_S = 0.3        # invisible this long -> track (crossing) is over
TRACK_MAX_S = 3.0        # visible longer -> something is lying there, not a crossing
WARM_UP_S = 2.0          # after the start the camera settles
MAX_JUMP = 0.6           # share of the zone diagonal a quad may jump per image
# Shadow: same colour as the background, only darker -> not an object.
# (brightness ratio, allowed deviation of saturation and hue)
SHADOW_BRIGHT_MIN, SHADOW_BRIGHT_MAX = 0.4, 0.95
SHADOW_SATURATION = 80   # measured: a shadow on a beige wall gets up to +45 more saturated
SHADOW_HUE = 15
COLOURLESS = 30          # below this the background has no reliable hue (grey/white)
JOIN_PX = 20             # blobs this close together are ONE quad (frame + props)
PHOTO_MARGIN = 0.2
PHOTO_MIN = 48           # minimum edge length of the photo in pixels (in the detection image)
# Follow the background: this much per 1/30 s – equally fast regardless of the frame rate
FOLLOW_30 = 0.05
KERNEL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
QUEUE_SIZE = 2           # this many prepared images may wait for processing


def clamp_zone(zone, width, height):
    x, y, w, h = (int(v) for v in zone)
    x = max(0, min(x, width - 10))
    y = max(0, min(y, height - 10))
    w = max(10, min(w, width - x))
    h = max(10, min(h, height - y))
    return x, y, w, h


@dataclass
class ObjectTrack:
    nr: int
    t_start: float
    t_last: float
    cx: float
    cy: float
    area: int = 0
    photo: np.ndarray | None = None
    fingerprint: dict | None = None
    box: tuple = (0, 0, 0, 0)   # x, y, w, h in the whole image


class Detector:
    def __init__(self, config, on_crossing, photos=None, net=None, to_card=None):
        self.config = config
        self.on_crossing = on_crossing
        self.photos = photos
        self.net = net
        # Is a race/practice running right now? Only then photos go to the SD card and the net runs.
        self.to_card = to_card or (lambda: True)
        # The net needs some tens of milliseconds per crossing: compute in the background
        # so the camera processing doesn't stall. One worker = the order is kept.
        self._worker = ThreadPoolExecutor(max_workers=1) if net is not None else None
        self.lock = threading.Lock()
        # for preview and display
        self.image = None
        self.mask = None
        self.zone = None
        self.share = 0.0
        self.fps = 0.0
        self.lost = 0.0          # share of images lost in the last second
        self.time_source = "–"   # where the timestamps come from: "camera" or "system"
        # internal
        self._background = None         # float32, followed slowly
        self._bg_u8 = None              # the same as uint8 (for the comparison)
        self._bg_hsv = None             # the same as HSV (for the shadow check, only when needed)
        self._t_before = None
        self._warm_up_until = None
        self._relearn = False
        self._tracks = []
        self._track_nr = 0

    def relearn(self):
        """Learn the background again, e.g. after changing the zone or the exposure."""
        self._relearn = True

    def preview(self):
        """(image, mask, zone, boxes) for the live stream, or None."""
        with self.lock:
            if self.image is None:
                return None
            boxes = [(t.nr, t.box) for t in self._tracks]
            return self.image.copy(), self.mask, self.zone, boxes

    # ------------------------------------------------------------ one image

    def process(self, image, t, photo_image=None):
        """Process one camera image. photo_image: the same image in higher resolution (for the photos)."""
        with self.config.lock:
            cfg = self.config.data
            zone = clamp_zone(cfg["zone"], image.shape[1], image.shape[0])
            pixel_threshold = cfg["pixel_threshold"]
            min_size = cfg.get("min_size", 60)
        if self._warm_up_until is None:
            self._warm_up_until = t + WARM_UP_S
        if self._relearn:
            self._relearn = False
            self._warm_up_until = max(self._warm_up_until, t + 1.0)

        dt = min(max(t - self._t_before, 0.0), 0.5) if self._t_before is not None else 0.0
        self._t_before = t
        x, y, w, h = zone
        crop = image[y:y + h, x:x + w]
        smooth = cv2.GaussianBlur(crop, (5, 5), 0)  # smooths image noise

        if self._background is None or self._background.shape != smooth.shape or t < self._warm_up_until:
            # learn the background (again), don't evaluate anything yet
            self._set_background(smooth)
            self._tracks = []
            with self.lock:
                self.image, self.mask, self.zone, self.share = image, None, zone, 0.0
            return

        # largest change over the three colour channels
        d = cv2.absdiff(smooth, self._bg_u8)
        changed = cv2.max(cv2.max(d[..., 0], d[..., 1]), d[..., 2]) > pixel_threshold  # faster than max(axis=2)
        if np.count_nonzero(changed) < min_size:
            # fast path for most images: too little changed, there can't be a quad
            mask, blobs = changed, []
        else:
            mask = (changed & ~self._shadow(smooth)).astype(np.uint8)  # without shadows
            joined = cv2.dilate(mask, KERNEL)
            count, labels, stats, centres = cv2.connectedComponentsWithStats(joined, connectivity=8)
            # size = actually changed pixels per blob (not the dilated area)
            sizes = np.bincount(labels[mask > 0], minlength=count)
            blobs = [i for i in range(1, count) if sizes[i] >= min_size]

        if not blobs:
            self._follow_background(smooth, dt)  # e.g. when the light changes
        else:
            self._assign_blobs(self._group(blobs, stats), sizes, stats, centres,
                               labels, mask, image, zone, t, photo_image)

        self._check_tracks(t, smooth)
        with self.lock:
            self.image, self.mask, self.zone = image, mask.astype(bool), zone
            self.share = float(np.count_nonzero(mask)) / mask.size

    def _set_background(self, smooth):
        self._background = smooth.astype(np.float32)
        self._bg_u8 = smooth.copy()
        self._bg_hsv = None

    def _follow_background(self, smooth, dt):
        # the same amount per second, whether 30 or 120 images/s
        share = 1.0 - (1.0 - FOLLOW_30) ** (dt * 30)
        if share <= 0:
            return
        cv2.accumulateWeighted(smooth, self._background, share)
        self._bg_u8 = cv2.convertScaleAbs(self._background)
        self._bg_hsv = None

    def _shadow(self, smooth):
        """Pixels that are only darker than the background but have the same colour."""
        if self._bg_hsv is None:  # only convert when needed, then remember
            self._bg_hsv = cv2.cvtColor(self._bg_u8, cv2.COLOR_BGR2HSV).astype(np.int16)
        hsv = cv2.cvtColor(smooth, cv2.COLOR_BGR2HSV).astype(np.int16)
        hsv_bg = self._bg_hsv
        ratio = hsv[..., 2] / np.maximum(hsv_bg[..., 2], 1)
        hue = np.abs(hsv[..., 0] - hsv_bg[..., 0])
        hue = np.minimum(hue, 180 - hue)  # hue is a circle (0 = 180)
        return ((ratio >= SHADOW_BRIGHT_MIN) & (ratio <= SHADOW_BRIGHT_MAX)
                & (np.abs(hsv[..., 1] - hsv_bg[..., 1]) <= SHADOW_SATURATION)
                & ((hsv_bg[..., 1] < COLOURLESS) | (hue <= SHADOW_HUE)))

    @staticmethod
    def _group(blobs, stats):
        """Join blobs whose boxes (enlarged by JOIN_PX) touch into groups."""
        group = {i: i for i in blobs}

        def root(i):
            while group[i] != i:
                i = group[i]
            return i

        for a in blobs:
            ax, ay, aw, ah = stats[a][:4]
            for b in blobs:
                if b <= a:
                    continue
                bx, by, bw, bh = stats[b][:4]
                if (ax - JOIN_PX < bx + bw and bx - JOIN_PX < ax + aw and
                        ay - JOIN_PX < by + bh and by - JOIN_PX < ay + ah):
                    group[root(a)] = root(b)
        result = {}
        for i in blobs:
            result.setdefault(root(i), []).append(i)
        return list(result.values())

    def _assign_blobs(self, groups, sizes, stats, centres, labels, mask, image, zone, t,
                      photo_image=None):
        x0, y0, w, h = zone
        crop = image[y0:y0 + h, x0:x0 + w]
        max_jump = MAX_JUMP * (w * w + h * h) ** 0.5
        taken = set()
        for parts in sorted(groups, key=lambda g: -sum(sizes[i] for i in g)):
            weights = np.array([sizes[i] for i in parts], dtype=float)
            cx, cy = (centres[parts] * weights[:, None]).sum(axis=0) / weights.sum()
            free = [tr for tr in self._tracks if tr.nr not in taken]
            nearest = min(free, key=lambda tr: (tr.cx - cx) ** 2 + (tr.cy - cy) ** 2, default=None)
            if nearest and ((nearest.cx - cx) ** 2 + (nearest.cy - cy) ** 2) ** 0.5 < max_jump:
                track = nearest
            else:
                self._track_nr += 1
                track = ObjectTrack(self._track_nr, t, t, cx, cy)
                self._tracks.append(track)
            taken.add(track.nr)
            track.cx, track.cy, track.t_last = cx, cy, t
            fx = int(min(stats[i][0] for i in parts))
            fy = int(min(stats[i][1] for i in parts))
            fw = int(max(stats[i][0] + stats[i][2] for i in parts)) - fx
            fh = int(max(stats[i][1] + stats[i][3] for i in parts)) - fy
            area = int(weights.sum())
            track.box = (x0 + fx, y0 + fy, fw, fh)
            if area > track.area:
                # best image of this quad so far: remember photo + fingerprint
                track.area = area
                # photo from the whole image, so the quad is not cut off at the edge of the zone –
                # from the high-resolution image if there is one
                if photo_image is not None:
                    sx, sy = photo_image.shape[1] / image.shape[1], photo_image.shape[0] / image.shape[0]
                    track.photo = self._photo_crop(
                        photo_image, round((x0 + fx) * sx), round((y0 + fy) * sy), round(fw * sx), round(fh * sy),
                        minimum=round(PHOTO_MIN * sx))
                else:
                    track.photo = self._photo_crop(image, x0 + fx, y0 + fy, fw, fh)
                track.fingerprint = self._fingerprint(crop, labels, mask, parts, fx, fy, fw, fh, area)

    @staticmethod
    def _photo_crop(image, fx, fy, fw, fh, minimum=PHOTO_MIN):
        margin_x = max(int(fw * PHOTO_MARGIN), (minimum - fw) // 2, 0)
        margin_y = max(int(fh * PHOTO_MARGIN), (minimum - fh) // 2, 0)
        height, width = image.shape[:2]
        return image[max(0, fy - margin_y):min(height, fy + fh + margin_y),
                     max(0, fx - margin_x):min(width, fx + fw + margin_x)].copy()

    @staticmethod
    def _fingerprint(crop, labels, mask, parts, fx, fy, fw, fh, area):
        # only the pixels of the quad: in its blobs AND actually changed
        in_quad = np.isin(labels[fy:fy + fh, fx:fx + fw], parts)
        part = in_quad & (mask[fy:fy + fh, fx:fx + fw] > 0)
        if part.sum() < 5:
            part = in_quad
        hsv = cv2.cvtColor(crop[fy:fy + fh, fx:fx + fw], cv2.COLOR_BGR2HSV)
        pixels = hsv[part]
        return fingerprint.fingerprint(pixels[:, 0], pixels[:, 1], area, fw / max(fh, 1), v=pixels[:, 2])

    def _check_tracks(self, t, smooth):
        for track in list(self._tracks):
            if t - track.t_start > TRACK_MAX_S:
                # something is lying in the zone: learn the background again instead of triggering all the time
                self._set_background(smooth)
                self._tracks = []
                return
            if t - track.t_last > TRACK_END_S:
                self._tracks.remove(track)
                self._report(track)

    def _report(self, track):
        if self._worker is not None:
            self._worker.submit(self._complete, track)
        else:
            self._complete(track)

    def _complete(self, track):
        """Save the photo, add the net fingerprint, report the crossing."""
        name, net_ms = None, None
        try:
            in_race = self.to_card()
            if self.photos is not None and track.photo is not None and track.photo.size:
                name = self.photos.save(track.photo, to_card=in_race)
                if in_race and self.net is not None and track.fingerprint is not None:
                    start = time.perf_counter()
                    track.fingerprint["embedding"] = self.net.embed(track.photo)
                    net_ms = (time.perf_counter() - start) * 1000
        except Exception as e:  # photo/net broken: report the crossing anyway
            print(f"Error with photo/net: {e!r}", flush=True)
        print(f"CROSSING  (area {track.area} px"
              + (f", net {net_ms:.0f} ms" if net_ms is not None else "") + ")", flush=True)
        self.on_crossing(Crossing(track.t_start, photo=name, fingerprint=track.fingerprint))

    # ------------------------------------------------------------ camera loop

    def run(self, camera):
        """Processes the camera's images (see camera.py) until the camera delivers nothing more.

        Two threads work at the same time (the Pi has 4 cores): one fetches the images and prepares
        them (convert, rotate), this one evaluates them. In between a short queue.
        If processing can't keep up, fetching waits – the camera then skips images,
        which is counted as "lost".
        """
        waiting = queue.Queue(maxsize=QUEUE_SIZE)

        def fetch():
            try:
                for capture in camera.captures():
                    waiting.put(capture)
            except Exception as e:
                print(f"Error fetching camera images: {e!r}", flush=True)
            finally:
                waiting.put(None)  # end

        threading.Thread(target=fetch, name="fetch-images", daemon=True).start()
        counter, counter_start = 0, time.monotonic()
        delivered0, lost0 = camera.delivered, camera.lost
        while (capture := waiting.get()) is not None:
            self.time_source = camera.time_source
            try:
                self.process(capture.image, capture.t, capture.photo_image)
            except Exception as e:  # one broken image must not end the detection
                print(f"Error in the detector: {e!r}", flush=True)
            finally:
                capture.release()
            counter += 1
            now = time.monotonic()
            if now - counter_start >= 1.0:
                self.fps = counter / (now - counter_start)
                # share of the images lost on the way (Pi too slow)
                lost = camera.lost - lost0
                total = camera.delivered - delivered0 + lost
                self.lost = lost / total if total else 0.0
                counter, counter_start = 0, now
                delivered0, lost0 = camera.delivered, camera.lost
