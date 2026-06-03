import numpy as np
import sys

try:
    from ai_edge_litert.interpreter import Interpreter
except ImportError:
    try:
        import tflite_runtime.interpreter as tflite
        Interpreter = tflite.Interpreter
    except ImportError:
        import tensorflow as tf
        Interpreter = tf.lite.Interpreter

import cv2

# Carregar modelo
model_path = sys.argv[1] if len(sys.argv) > 1 else "runs/detect/autopilot_nvidia/nano_final_estavel/weights/best_saved_model/assets/best_float32.tflite"
image_path = sys.argv[2] if len(sys.argv) > 2 else "teste.jpg"

interpreter = Interpreter(model_path=model_path)
interpreter.allocate_tensors()

input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()

# Preparar imagem
img = cv2.imread(image_path)
h, w = img.shape[:2]
img_resized = cv2.resize(img, (640, 640))
img_rgb = cv2.cvtColor(img_resized, cv2.COLOR_BGR2RGB)
input_data = np.expand_dims(img_rgb.astype(np.float32) / 255.0, axis=0)

# Inferência
interpreter.set_tensor(input_details[0]['index'], input_data)
interpreter.invoke()
output = interpreter.get_tensor(output_details[0]['index'])

print(f"Output shape: {output.shape}")

# Transpor se necessário: [1, 13, 8400] -> [1, 8400, 13]
if output.shape[1] < output.shape[2]:
    output = np.transpose(output, (0, 2, 1))

predictions = output[0]  # [8400, 13]
boxes = predictions[:, :4]     # cx, cy, w, h
scores_raw = predictions[:, 4:]  # 9 classes

print("\n" + "="*60)
print("📊 SCORES SEM SIGMOID:")
print(f"   Min: {scores_raw.min():.6f}")
print(f"   Max: {scores_raw.max():.6f}")
print(f"   Contém negativos: {(scores_raw < 0).any()}")

# Aplicar sigmoid
def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -50, 50)))

scores_sigmoid = sigmoid(scores_raw)

print("\n📊 SCORES COM SIGMOID:")
print(f"   Min: {scores_sigmoid.min():.6f}")
print(f"   Max: {scores_sigmoid.max():.6f}")

print("\n📊 COMPARAÇÃO POR CLASSE:")
print(f"   {'Classe':<10} {'Raw Max':>10} {'Sigmoid Max':>12} {'Raw>0.1':>8} {'Sig>0.25':>9} {'Sig>0.5':>8}")
print(f"   {'-'*58}")

for i in range(scores_raw.shape[1]):
    raw_max = scores_raw[:, i].max()
    sig_max = scores_sigmoid[:, i].max()
    raw_count = (scores_raw[:, i] > 0.1).sum()
    sig_count_25 = (scores_sigmoid[:, i] > 0.25).sum()
    sig_count_50 = (scores_sigmoid[:, i] > 0.5).sum()
    print(f"   {i:<10} {raw_max:>10.4f} {sig_max:>12.4f} {raw_count:>8} {sig_count_25:>9} {sig_count_50:>8}")

# Teste com threshold baixo
conf_threshold = 0.10
class_ids = np.argmax(scores_raw, axis=1)
class_scores_raw = np.max(scores_raw, axis=1)
class_scores_sig = np.max(scores_sigmoid, axis=1)

print(f"\n🎯 DETECÇÕES (conf > {conf_threshold}):")
print(f"\n   Sem sigmoid:")
mask_raw = class_scores_raw > conf_threshold
print(f"   Total: {mask_raw.sum()} detecções")

print(f"\n   Com sigmoid:")
class_ids_sig = np.argmax(scores_sigmoid, axis=1)
class_scores_sig_max = np.max(scores_sigmoid, axis=1)
mask_sig = class_scores_sig_max > conf_threshold
print(f"   Total: {mask_sig.sum()} detecções")

# Top 10 melhores detecções (com sigmoid)
top_indices = np.argsort(class_scores_sig_max)[::-1][:10]
print(f"\n🏆 TOP 10 DETECÇÕES (com sigmoid):")
for idx in top_indices:
    cls = class_ids_sig[idx]
    conf = class_scores_sig_max[idx]
    cx, cy, cw, ch = boxes[idx]
    print(f"   Classe {cls}: conf={conf:.4f} | cx={cx:.3f} cy={cy:.3f} w={cw:.3f} h={ch:.3f}")

print(f"\n🏆 TOP 10 DETECÇÕES (sem sigmoid):")
top_indices_raw = np.argsort(class_scores_raw)[::-1][:10]
for idx in top_indices_raw:
    cls = class_ids[idx]
    conf = class_scores_raw[idx]
    cx, cy, cw, ch = boxes[idx]
    print(f"   Classe {cls}: conf={conf:.4f} | cx={cx:.3f} cy={cy:.3f} w={cw:.3f} h={ch:.3f}")