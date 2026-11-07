# FER+ model

Source: https://github.com/onnx/models/tree/main/validated/vision/body_analysis/emotion_ferplus

Model: emotion-ferplus-8.onnx, 35,040,571 bytes, MIT license.
The original FERPlus MIT license is in LICENSE.txt (source:
https://github.com/ebarsoum/FERPlus/blob/master/LICENSE.md). The ONNX Model Zoo
repository's Apache-2.0 license is retained in MODEL_ZOO_LICENSE.txt.
SHA256: a2a2ba6a335a3b29c21acb6272f962bd3d47f84952aaffa03b60986e04efa61c

Run `scripts/prepare_ai.py` from the project environment to download and verify it.
Weights are excluded from version control. Downloading uses TLS verification.

Input: float32 grayscale faces, 1×1×64×64, pixels 0–255. Output: eight
logits, converted to probabilities with stable softmax. Labels in model order:
neutral, happiness, surprise, sadness, anger, disgust, fear, contempt.
The application excludes contempt rather than assigning it to a different class.
Haar frontal face detection is supplied by OpenCV. At most 12 faces per frame
are evaluated, largest faces first. Detection/classification can miss faces,
especially profiles, occlusions, or small faces. No identity recognition.
