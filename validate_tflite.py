"""
Script para validar o modelo YOLOv8 TFLite ANTES de colocar no Android.
Roda no PC. Mostra shapes, tipos, valores brutos e detecções.

Uso:
    pip install numpy opencv-python tensorflow
    python validate_tflite.py --model model.tflite --image test.jpg
"""

import argparse
import numpy as np
import cv2
import time

def carregar_modelo(model_path):
    """Carrega o modelo TFLite e mostra informações detalhadas."""
    try:
        import tensorflow as tf
        interpreter = tf.lite.Interpreter(model_path=model_path)
    except ImportError:
        # Fallback para tflite_runtime
        import tflite_runtime.interpreter as tflite
        interpreter = tflite.Interpreter(model_path=model_path)

    interpreter.allocate_tensors()

    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    print("=" * 60)
    print("📥 INPUT:")
    for i, inp in enumerate(input_details):
        print(f"  [{i}] name: {inp['name']}")
        print(f"      shape: {inp['shape']}")
        print(f"      dtype: {inp['dtype']}")
        print(f"      quantization: {inp.get('quantization', 'N/A')}")
        print(f"      quantization_parameters: {inp.get('quantization_parameters', 'N/A')}")

    print("\n📤 OUTPUT:")
    for i, out in enumerate(output_details):
        print(f"  [{i}] name: {out['name']}")
        print(f"      shape: {out['shape']}")
        print(f"      dtype: {out['dtype']}")
        print(f"      quantization: {out.get('quantization', 'N/A')}")
        print(f"      quantization_parameters: {out.get('quantization_parameters', 'N/A')}")

    print("=" * 60)

    return interpreter, input_details, output_details


def preparar_imagem(image_path, input_size):
    """Prepara a imagem exatamente como o Android faz."""
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"Imagem não encontrada: {image_path}")

    print(f"\n🖼️  Imagem original: {img.shape[1]}x{img.shape[0]}")

    # Redimensionar (stretch, igual ao Bitmap.createScaledBitmap no Android)
    img_resized = cv2.resize(img, (input_size, input_size))

    # BGR → RGB (OpenCV usa BGR, Android usa RGB)
    img_rgb = cv2.cvtColor(img_resized, cv2.COLOR_BGR2RGB)

    # Normalizar para [0, 1] float32 — padrão YOLOv8
    img_norm = img_rgb.astype(np.float32) / 255.0

    # Adicionar dimensão batch: [1, H, W, 3]
    img_batch = np.expand_dims(img_norm, axis=0)

    print(f"   Input preparado: shape={img_batch.shape}, "
          f"dtype={img_batch.dtype}, "
          f"min={img_batch.min():.3f}, max={img_batch.max():.3f}")

    return img_batch, img


def analisar_output(output, num_classes=9):
    """Analisa o output bruto para determinar o formato."""
    print(f"\n🔍 ANÁLISE DO OUTPUT:")
    print(f"   Shape: {output.shape}")
    print(f"   Dtype: {output.dtype}")
    print(f"   Min: {output.min():.6f}")
    print(f"   Max: {output.max():.6f}")
    print(f"   Mean: {output.mean():.6f}")

    # Remover dimensão batch
    if output.ndim == 3:
        data = output[0]
    else:
        data = output

    num_features = 4 + num_classes  # 4 bbox + N classes

    # Detectar formato: [features, predictions] ou [predictions, features]
    if data.shape[0] == num_features:
        formato = "TRANSPOSED [features, predictions]"
        n_preds = data.shape[1]
        # data[feature][prediction]
        get_val = lambda f, p: data[f][p]
    elif data.shape[1] == num_features:
        formato = "STANDARD [predictions, features]"
        n_preds = data.shape[0]
        get_val = lambda f, p: data[p][f]
    else:
        print(f"   ⚠️  FORMATO DESCONHECIDO! Dimensões: {data.shape}")
        print(f"       Esperado: [{num_features}, N] ou [N, {num_features}]")
        print(f"       Onde num_features = 4 bbox + {num_classes} classes = {num_features}")
        return None, None, None

    print(f"   Formato: {formato}")
    print(f"   Predições: {n_preds}")

    # Analisar coordenadas (primeiros 4 features)
    print(f"\n📐 COORDENADAS (cx, cy, w, h):")
    for f in range(4):
        vals = [get_val(f, p) for p in range(n_preds)]
        vals_np = np.array(vals)
        names = ["cx", "cy", "w", "h"]
        print(f"   {names[f]}: min={vals_np.min():.4f}, "
              f"max={vals_np.max():.4f}, "
              f"mean={vals_np.mean():.4f}")

    # Determinar se normalizado ou pixel space
    max_coord = max(
        max(abs(get_val(0, p)) for p in range(n_preds)),
        max(abs(get_val(1, p)) for p in range(n_preds))
    )

    if max_coord > 2.0:
        coord_space = "PIXEL SPACE (0 a ~640)"
        is_normalized = False
    else:
        coord_space = "NORMALIZADO (0 a 1)"
        is_normalized = True

    print(f"\n   → Espaço de coordenadas: {coord_space}")
    print(f"     (valor máximo de cx/cy: {max_coord:.4f})")

    # Analisar scores das classes
    print(f"\n📊 SCORES DAS CLASSES:")
    for c in range(num_classes):
        f = 4 + c
        vals = [get_val(f, p) for p in range(n_preds)]
        vals_np = np.array(vals)
        n_above_05 = np.sum(vals_np > 0.5)
        n_above_025 = np.sum(vals_np > 0.25)
        print(f"   Classe {c}: max={vals_np.max():.4f}, "
              f">0.5: {n_above_05}, >0.25: {n_above_025}")

    return formato, is_normalized, n_preds


def detectar(output, num_classes, class_names, conf_threshold,
             input_size, orig_w, orig_h, is_normalized):
    """Parseia as detecções do output."""
    data = output[0] if output.ndim == 3 else output
    num_features = 4 + num_classes

    # Detectar formato
    if data.shape[0] == num_features:
        get_val = lambda f, p: data[f][p]
        n_preds = data.shape[1]
    else:
        get_val = lambda f, p: data[p][f]
        n_preds = data.shape[0]

    detections = []

    for i in range(n_preds):
        # Encontrar classe com maior score
        max_conf = 0
        max_class = 0
        for c in range(num_classes):
            score = get_val(4 + c, i)
            if score > max_conf:
                max_conf = score
                max_class = c

        if max_conf < conf_threshold:
            continue

        cx = get_val(0, i)
        cy = get_val(1, i)
        w = get_val(2, i)
        h = get_val(3, i)

        if is_normalized:
            # Normalizado [0,1] → escalar para imagem original
            x1 = (cx - w / 2) * orig_w
            y1 = (cy - h / 2) * orig_h
            x2 = (cx + w / 2) * orig_w
            y2 = (cy + h / 2) * orig_h
        else:
            # Pixel space [0, input_size] → escalar para imagem original
            scale_x = orig_w / input_size
            scale_y = orig_h / input_size
            x1 = (cx - w / 2) * scale_x
            y1 = (cy - h / 2) * scale_y
            x2 = (cx + w / 2) * scale_x
            y2 = (cy + h / 2) * scale_y

        # Clampar
        x1 = max(0, min(x1, orig_w))
        y1 = max(0, min(y1, orig_h))
        x2 = max(0, min(x2, orig_w))
        y2 = max(0, min(y2, orig_h))

        if x2 - x1 < 3 or y2 - y1 < 3:
            continue

        name = class_names[max_class] if max_class < len(class_names) else f"class_{max_class}"
        detections.append({
            'class': name,
            'class_id': max_class,
            'confidence': float(max_conf),
            'bbox': [int(x1), int(y1), int(x2), int(y2)]
        })

    # NMS simples
    detections.sort(key=lambda d: d['confidence'], reverse=True)
    final = []
    for det in detections:
        keep = True
        for kept in final:
            if kept['class_id'] == det['class_id']:
                iou = compute_iou(det['bbox'], kept['bbox'])
                if iou > 0.45:
                    keep = False
                    break
        if keep:
            final.append(det)

    return final


def compute_iou(box1, box2):
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    union = area1 + area2 - inter
    return inter / union if union > 0 else 0


def desenhar(img, detections):
    """Desenha as detecções na imagem."""
    colors = {
        'car': (0, 255, 0),
        'motorcycle': (0, 200, 0),
        'bicycle': (0, 150, 0),
        'truck': (0, 100, 0),
        'ambulance': (0, 0, 255),
        'traffic-light-green': (0, 255, 0),
        'traffic-light-red': (0, 0, 255),
        'traffic-light-yellow': (0, 255, 255),
        'crosswalk': (255, 0, 0),
    }

    for det in detections:
        x1, y1, x2, y2 = det['bbox']
        color = colors.get(det['class'], (255, 255, 255))
        conf = det['confidence']

        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        label = f"{det['class']} {conf:.2f}"
        cv2.putText(img, label, (x1, y1 - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

    return img


def main():
    parser = argparse.ArgumentParser(description='Validar modelo YOLOv8 TFLite')
    parser.add_argument('--model', required=True, help='Caminho do modelo .tflite')
    parser.add_argument('--image', required=True, help='Imagem de teste')
    parser.add_argument('--conf', type=float, default=0.25, help='Confiança mínima')
    parser.add_argument('--size', type=int, default=0, help='Input size (0=auto)')
    parser.add_argument('--output', default='resultado.jpg', help='Imagem de saída')
    args = parser.parse_args()

    # Classes do modelo (AJUSTE conforme necessário)
    CLASS_NAMES = [
        "car",                      # 0
        "motorcycle",               # 1
        "bicycle",                  # 2
        "truck",                    # 3
        "ambulance",                # 4
        "traffic-light-green",      # 5
        "traffic-light-red",        # 6
        "traffic-light-yellow",     # 7
        "crosswalk"                 # 8
    ]
    NUM_CLASSES = len(CLASS_NAMES)

    # Carregar modelo
    interpreter, input_details, output_details = carregar_modelo(args.model)

    # Determinar input size
    input_shape = input_details[0]['shape']
    input_size = args.size if args.size > 0 else input_shape[1]
    print(f"\n📏 Input size: {input_size}x{input_size}")

    # Preparar imagem
    img_batch, img_orig = preparar_imagem(args.image, input_size)
    orig_h, orig_w = img_orig.shape[:2]

    # Verificar se precisa quantização
    input_dtype = input_details[0]['dtype']
    if input_dtype == np.uint8:
        print("\n⚠️  Modelo QUANTIZADO (uint8)!")
        quant_params = input_details[0].get('quantization_parameters', {})
        scales = quant_params.get('scales', [1.0])
        zero_points = quant_params.get('zero_points', [0])
        if len(scales) > 0 and scales[0] != 0:
            img_batch = (img_batch / scales[0] + zero_points[0]).astype(np.uint8)
        else:
            img_batch = (img_batch * 255).astype(np.uint8)
        print(f"   Input convertido para uint8: min={img_batch.min()}, max={img_batch.max()}")

    # Inferência
    interpreter.set_tensor(input_details[0]['index'], img_batch)

    start = time.time()
    interpreter.invoke()
    elapsed = (time.time() - start) * 1000
    print(f"\n⏱️  Tempo de inferência: {elapsed:.1f}ms")

    # Obter output
    output = interpreter.get_tensor(output_details[0]['index'])

    # Dequantizar se necessário
    output_dtype = output_details[0]['dtype']
    if output_dtype == np.uint8 or output_dtype == np.int8:
        quant_params = output_details[0].get('quantization_parameters', {})
        scales = quant_params.get('scales', [1.0])
        zero_points = quant_params.get('zero_points', [0])
        if len(scales) > 0 and scales[0] != 0:
            output = (output.astype(np.float32) - zero_points[0]) * scales[0]
            print(f"   Output dequantizado: min={output.min():.4f}, max={output.max():.4f}")

    # Analisar output
    formato, is_normalized, n_preds = analisar_output(output, NUM_CLASSES)

    if formato is None:
        print("\n❌ Não foi possível determinar o formato do output!")
        print("   Verifique se o número de classes está correto.")
        return

    # Detectar
    detections = detectar(
        output, NUM_CLASSES, CLASS_NAMES, args.conf,
        input_size, orig_w, orig_h, is_normalized
    )

    print(f"\n🎯 DETECÇÕES ({len(detections)}):")
    if detections:
        for i, det in enumerate(detections):
            print(f"   [{i}] {det['class']} "
                  f"conf={det['confidence']:.3f} "
                  f"bbox={det['bbox']}")
    else:
        print("   Nenhuma detecção! Possíveis causas:")
        print("   1. Confiança mínima muito alta (tente --conf 0.10)")
        print("   2. Modelo mal convertido")
        print("   3. Imagem sem os objetos treinados")
        print("   4. Ordem das classes incorreta")

    # Desenhar e salvar
    img_result = desenhar(img_orig.copy(), detections)
    cv2.imwrite(args.output, img_result)
    print(f"\n💾 Resultado salvo em: {args.output}")

    # ═══════════════════════════════════════
    # RESUMO PARA CONFIGURAR O ANDROID
    # ═══════════════════════════════════════
    print("\n" + "=" * 60)
    print("📱 CONFIGURAÇÃO PARA O ANDROID:")
    print(f"   inputSize = {input_size}")
    print(f"   isTransposed = {formato.startswith('TRANSPOSED')}")
    print(f"   isNormalized = {is_normalized}")
    print(f"   numClasses = {NUM_CLASSES}")
    print(f"   numPredictions = {n_preds}")
    print(f"   inputDtype = {input_dtype}")
    print(f"   outputDtype = {output_dtype}")
    print("=" * 60)


if __name__ == '__main__':
    main()