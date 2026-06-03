import numpy as np
import cv2
import sys
import time
import argparse

try:
    from ai_edge_litert.interpreter import Interpreter
except ImportError:
    try:
        import tflite_runtime.interpreter as tflite
        Interpreter = tflite.Interpreter
    except ImportError:
        import tensorflow as tf
        Interpreter = tf.lite.Interpreter


def letterbox(img, new_shape=640, color=(114, 114, 114)):
    """Redimensiona com letterbox (igual ao YOLO)"""
    shape = img.shape[:2]  # h, w
    if isinstance(new_shape, int):
        new_shape = (new_shape, new_shape)

    # Ratio
    r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])
    new_unpad = (int(round(shape[1] * r)), int(round(shape[0] * r)))  # w, h

    # Padding
    dw = new_shape[1] - new_unpad[0]
    dh = new_shape[0] - new_unpad[1]
    dw /= 2
    dh /= 2

    img_resized = cv2.resize(img, new_unpad, interpolation=cv2.INTER_LINEAR)

    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    img_padded = cv2.copyMakeBorder(img_resized, top, bottom, left, right,
                                     cv2.BORDER_CONSTANT, value=color)

    return img_padded, r, (dw, dh)


def nms(boxes, scores, iou_threshold=0.45):
    """Non-Maximum Suppression"""
    if len(boxes) == 0:
        return []

    x1 = boxes[:, 0]
    y1 = boxes[:, 1]
    x2 = boxes[:, 2]
    y2 = boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)

    order = scores.argsort()[::-1]
    keep = []

    while order.size > 0:
        i = order[0]
        keep.append(i)

        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])

        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        iou = inter / (areas[i] + areas[order[1:]] - inter)

        inds = np.where(iou <= iou_threshold)[0]
        order = order[inds + 1]

    return keep


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', type=str, required=True)
    parser.add_argument('--image', type=str, required=True)
    parser.add_argument('--conf', type=float, default=0.15)
    parser.add_argument('--iou', type=float, default=0.45)
    args = parser.parse_args()

    CLASS_NAMES = {
        0: 'car', 1: 'motorcycle', 2: 'bicycle', 3: 'truck',
        4: 'ambulance', 5: 'traffic-light-green', 6: 'traffic-light-red',
        7: 'traffic-light-yellow', 8: 'crosswalk'
    }

    # Carregar modelo
    interpreter = Interpreter(model_path=args.model)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    input_shape = input_details[0]['shape']
    input_size = int(input_shape[1]) # 640
    print(f"📐 Input size: {input_size}x{input_size}")

    # Carregar imagem
    img_orig = cv2.imread(args.image)
    if img_orig is None:
        print(f"❌ Não conseguiu abrir: {args.image}")
        return

    h_orig, w_orig = img_orig.shape[:2]
    print(f"🖼️  Imagem original: {w_orig}x{h_orig}")

    # Letterbox (igual ao YOLO)
    img_letterbox, ratio, (pad_w, pad_h) = letterbox(img_orig, input_size)
    print(f"📦 Letterbox: ratio={ratio:.4f}, pad=({pad_w:.1f}, {pad_h:.1f})")

    # Preparar input
    img_rgb = cv2.cvtColor(img_letterbox, cv2.COLOR_BGR2RGB)
    input_data = np.expand_dims(img_rgb.astype(np.float32) / 255.0, axis=0)

    # Inferência
    interpreter.set_tensor(input_details[0]['index'], input_data)
    t0 = time.time()
    interpreter.invoke()
    t1 = time.time()
    output = interpreter.get_tensor(output_details[0]['index'])

    print(f"⏱️  Inferência: {(t1-t0)*1000:.1f}ms")
    print(f"📤 Output shape: {output.shape}")

    # Transpor se necessário: [1, 13, 8400] -> [1, 8400, 13]
    if output.shape[1] < output.shape[2]:
        output = np.transpose(output, (0, 2, 1))
        print("🔄 Transposto para [1, 8400, 13]")

    predictions = output[0]  # [8400, 13]
    num_classes = predictions.shape[1] - 4

    # Extrair boxes e scores
    boxes_raw = predictions[:, :4]      # cx, cy, w, h
    class_scores = predictions[:, 4:]   # [8400, 9]

    # Verificar se coordenadas são normalizadas ou em pixels
    max_coord = boxes_raw[:, :2].max()
    if max_coord <= 1.0:
        print(f"📏 Coordenadas normalizadas (max={max_coord:.4f})")
        # Converter para pixels no espaço letterbox (640x640)
        boxes_raw[:, 0] *= input_size   # cx
        boxes_raw[:, 1] *= input_size   # cy
        boxes_raw[:, 2] *= input_size   # w
        boxes_raw[:, 3] *= input_size   # h
    else:
        print(f"📏 Coordenadas em pixels (max={max_coord:.1f})")

    # Converter cxcywh -> xyxy
    boxes_xyxy = np.zeros_like(boxes_raw)
    boxes_xyxy[:, 0] = boxes_raw[:, 0] - boxes_raw[:, 2] / 2  # x1
    boxes_xyxy[:, 1] = boxes_raw[:, 1] - boxes_raw[:, 3] / 2  # y1
    boxes_xyxy[:, 2] = boxes_raw[:, 0] + boxes_raw[:, 2] / 2  # x2
    boxes_xyxy[:, 3] = boxes_raw[:, 1] + boxes_raw[:, 3] / 2  # y2

    # Filtrar por confiança
    max_scores = np.max(class_scores, axis=1)
    class_ids = np.argmax(class_scores, axis=1)

    mask = max_scores > args.conf
    filtered_boxes = boxes_xyxy[mask]
    filtered_scores = max_scores[mask]
    filtered_classes = class_ids[mask]

    print(f"\n🔍 Após filtro conf>{args.conf}: {len(filtered_boxes)} candidatos")

    # NMS
    if len(filtered_boxes) > 0:
        keep = nms(filtered_boxes, filtered_scores, args.iou)
        final_boxes = filtered_boxes[keep]
        final_scores = filtered_scores[keep]
        final_classes = filtered_classes[keep]
    else:
        final_boxes = np.array([])
        final_scores = np.array([])
        final_classes = np.array([])

    print(f"🎯 Após NMS: {len(final_boxes)} detecções\n")

    # Desenhar resultados
    img_draw = img_orig.copy()
    colors = [
        (0, 255, 0), (255, 0, 0), (0, 0, 255), (255, 255, 0),
        (255, 0, 255), (0, 255, 128), (0, 0, 200), (0, 200, 255), (128, 128, 0)
    ]

    for i in range(len(final_boxes)):
        x1, y1, x2, y2 = final_boxes[i]
        cls = int(final_classes[i])
        conf = final_scores[i]

        # Converter de espaço letterbox para espaço original
        x1 = (x1 - pad_w) / ratio
        y1 = (y1 - pad_h) / ratio
        x2 = (x2 - pad_w) / ratio
        y2 = (y2 - pad_h) / ratio

        # Clip
        x1 = max(0, int(x1))
        y1 = max(0, int(y1))
        x2 = min(w_orig, int(x2))
        y2 = min(h_orig, int(y2))

        color = colors[cls % len(colors)]
        name = CLASS_NAMES.get(cls, f'cls{cls}')
        label = f"{name} {conf:.2f}"

        cv2.rectangle(img_draw, (x1, y1), (x2, y2), color, 2)
        cv2.putText(img_draw, label, (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        print(f"  [{i}] {name}: {conf:.4f} | ({x1},{y1})-({x2},{y2})")

    if len(final_boxes) == 0:
        print("  ❌ Nenhuma detecção!")

        # Diagnóstico: top 5 scores
        top5 = np.argsort(max_scores)[::-1][:5]
        print("\n  📊 Top 5 scores (para diagnóstico):")
        for idx in top5:
            cls = class_ids[idx]
            conf = max_scores[idx]
            name = CLASS_NAMES.get(cls, f'cls{cls}')
            print(f"     {name}: {conf:.4f}")

    output_path = "resultado_v2.jpg"
    cv2.imwrite(output_path, img_draw)
    print(f"\n💾 Salvo em: {output_path}")

    # Comparação com PyTorch
    print("\n" + "="*60)
    print("📊 RESUMO PARA COMPARAÇÃO COM PYTORCH:")
    print(f"   PyTorch detectou: 1 car com conf 0.2354")
    print(f"   TFLite max car (cls 0): {class_scores[:, 0].max():.4f}")
    print(f"   TFLite max geral: classe {class_ids[np.argmax(max_scores)]} "
          f"({CLASS_NAMES.get(class_ids[np.argmax(max_scores)], '?')}) "
          f"com conf {max_scores.max():.4f}")
    print("="*60)


if __name__ == '__main__':
    main()