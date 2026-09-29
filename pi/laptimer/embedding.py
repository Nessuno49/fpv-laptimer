"""Pre-trained neural network (MobileNetV2) as the fingerprint of a quad.

The network describes a photo with 1280 numbers (shape, structure, colour). Two photos
of the same quad lie close together in it. It is not trained – the matching only
compares with the stored samples (see fingerprint.py).
Runs with OpenCV (cv2.dnn), needs no further packages.
"""
import numpy as np

SIZE = 224
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)   # ImageNet normalisation
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
FEATURES = 1280  # size of the output right before the classification
# Known names of this output (OpenCV 4 and 5). The names differ between OpenCV versions,
# so we also search automatically (see _find_layer).
KNOWN_LAYERS = ("Reshape_103", "472", "464")


class EmbeddingNet:
    def __init__(self, path):
        import cv2
        self._cv2 = cv2
        self._net = cv2.dnn.readNetFromONNX(str(path))
        self._layer = None

    def embed(self, image):
        """BGR image -> list of 1280 numbers, length 1."""
        cv2 = self._cv2
        x = cv2.resize(image, (SIZE, SIZE))[:, :, ::-1].astype(np.float32) / 255.0
        x = ((x - MEAN) / STD).transpose(2, 0, 1)[None]
        self._net.setInput(np.ascontiguousarray(x, dtype=np.float32))
        if self._layer is None:
            self._layer = self._find_layer()
        e = self._net.forward(self._layer).ravel()
        length = float(np.linalg.norm(e))
        return [round(float(v), 4) for v in (e / length if length else e)]

    def _find_layer(self):
        """Search the layer that delivers exactly FEATURES values (the input is already set)."""
        names = list(self._net.getLayerNames())
        candidates = list(KNOWN_LAYERS) + [n for n in reversed(names[-30:])]
        for name in candidates:
            try:
                if self._net.forward(name).size == FEATURES:
                    return name
            except self._cv2.error:
                continue
        raise RuntimeError(f"No layer with {FEATURES} values found (last: {names[-8:]})")


def load(path):
    """Load the network, or None if the file or OpenCV is missing (the lap timer then runs without it)."""
    try:
        net = EmbeddingNet(path)
        net.embed(np.zeros((64, 64, 3), np.uint8))  # trial run
        return net
    except Exception as e:
        print(f"Neural network not available ({e!r}) – colour fingerprint only.", flush=True)
        return None
