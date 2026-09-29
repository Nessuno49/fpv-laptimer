# Models

| File | Source | License | Purpose |
|---|---|---|---|
| `mobilenetv2-12.onnx` | [ONNX Model Zoo](https://github.com/onnx/models/tree/main/validated/vision/classification/mobilenet) (MobileNetV2, opset 12), downloaded on 2026-09-24 | Apache 2.0 | Pre-trained network used as a "fingerprint" for recognising quads (runs with OpenCV `cv2.dnn`, nothing else to install) |

Loaded by `embedding.py`. If the file is missing, the lap timer keeps working, just without the neural
network (colour fingerprint only).
