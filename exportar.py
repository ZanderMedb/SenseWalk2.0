from ultralytics import YOLO

model = YOLO('runs/detect/autopilot_nvidia/nano_final_estavel/weights/best.pt')

# Exportar diretamente para TFLite (conversão limpa)
model.export(
    format='tflite',
    imgsz=640,
    int8=False,
    half=False,
)

print("✅ Exportação concluída!")
print("Procure o ficheiro .tflite na pasta de weights")