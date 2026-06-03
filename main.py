from ultralytics import YOLO
import cv2
import pyttsx3
import time
import queue
import threading
import math
import numpy as np
import os
import sys
from collections import defaultdict, deque


# ============================================================
# 1. CONFIGURAÇÃO
# ============================================================
FONTE_VIDEO = "http://192.168.100.4:8080/video"
RESOLUCAO = (640, 480)
MODELO_PATH = "runs/detect/autopilot_nvidia/nano_final_estavel/weights/best.pt"

if not os.path.isfile(MODELO_PATH):
    print(f"[ERRO FATAL] Modelo nao encontrado: {MODELO_PATH}")
    sys.exit(1)

# ── Classes ──
KEYWORDS_VEICULOS = {"car", "motorcycle", "bicycle", "truck", "ambulance"}
KEYWORDS_FAIXA = {"crosswalk"}
KEYWORDS_SEMAFORO_PREFIXO = "traffic-light"
KW_VERMELHO = {"red"}
KW_VERDE = {"green"}
KW_AMARELO = {"yellow"}

NOMES_PT = {
    "car": "carro", "motorcycle": "moto", "bicycle": "bicicleta",
    "truck": "caminhão", "ambulance": "ambulância",
}

# ── Detecção ──
CONF_MINIMA = 0.40
INFERENCIA_TAMANHO = 640
HISTORICO_MAX = 30

VEL_PARADO_PXS = 18.0
VEL_APROXIMANDO_PXS = 30.0
VEL_ALTA_PXS = 120.0

LIMIAR_PROXIMO_PCT = 0.30
LIMIAR_EMERGENCIA_PCT = 0.45

# ── Lógica ──
TEMPO_RECON = 3.5
TEMPO_PARADO_SEGURO = 3.0
RECON_THRESHOLD = 0.25
RECON_EARLY_THRESHOLD = 0.50
RECON_EARLY_MIN_FRAMES = 20
UPGRADE_FRAMES = 10

GHOST_FRAMES_MAX = 15
GHOST_DECAY_CONF = 0.02

ROI_ATIVO = True
ROI_TOP = 0.05
ROI_BOTTOM = 0.95
ROI_LEFT = 0.02
ROI_RIGHT = 0.98

# ── NOVO: Suavização e Compensação ──
EMA_ALPHA = 0.45
CAMERA_COMP_MIN_OBJETOS = 2

# ── NOVO: Alinhamento faixa ──
FAIXA_MARGEM_ALINHAMENTO = 0.10

# ── NOVO: Heartbeat (nunca silenciar) ──
HEARTBEAT_INTERVAL = 5.0

# ── Estados ──
EST_INATIVO = "INATIVO"
EST_RECONHECENDO = "RECONHECENDO"
EST_SEMAFORO = "SEMAFORO"
EST_FAIXA = "FAIXA"
EST_VIA_LIVRE = "VIA_LIVRE"


# ============================================================
# 2. CÂMERA (thread)
# ============================================================
class CameraStream:
    def __init__(self, fonte):
        self.fonte = fonte
        self.cap = cv2.VideoCapture(fonte)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, RESOLUCAO[0])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, RESOLUCAO[1])
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.frame = None
        self.rodando = True
        self.lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self.rodando:
            ok, f = self.cap.read()
            if ok:
                with self.lock:
                    self.frame = f
            else:
                time.sleep(2)
                self.cap.open(self.fonte)

    def ler(self):
        with self.lock:
            return self.frame.copy() if self.frame is not None else None

    def parar(self):
        self.rodando = False
        self.cap.release()


# ============================================================
# 3. VOZ (thread) — COM RASTREIO DE SILÊNCIO
# ============================================================
class SistemaVoz:
    def __init__(self):
        self.fila = queue.Queue()
        self._ultimos = defaultdict(float)
        self._cooldowns = {
            "inicio": 0.0,
            "cancelado": 0.0,
            "recon_resultado": 0.0,
            "recon_progresso": 3.0,
            "semaforo_cor": 0.5,
            "semaforo_pode": 5.0,
            "semaforo_aguarde": 6.0,
            "semaforo_veiculo": 5.0,
            "semaforo_perdido": 8.0,
            "faixa_acene": 10.0,
            "faixa_livre": 5.0,
            "faixa_parados": 5.0,
            "faixa_parando": 4.0,
            "faixa_movimento": 5.0,
            "faixa_alinhamento": 3.5,
            "via_livre": 5.0,
            "via_parados": 5.0,
            "via_parando": 4.0,
            "via_movimento": 5.0,
            "emergencia": 2.5,
            "aproximando": 3.0,
            "perigo_velocidade": 2.0,
            "upgrade": 0.0,
            "sistema": 3.0,
            "veiculo_novo": 2.5,
            "agr_mudanca": 2.0,
            "heartbeat": 4.0,
        }
        self._engine_ok = False
        self._falhas = 0
        self._t_ultima_fala = time.time()
        t = threading.Thread(target=self._worker, daemon=True)
        t.start()
        t_espera = time.time()
        while not self._engine_ok and (time.time() - t_espera) < 5.0:
            time.sleep(0.1)
        if self._engine_ok:
            print("[VOZ] Pronto!")
        else:
            print("[VOZ] AVISO: motor de voz pode nao funcionar")

    def _worker(self):
        try:
            import pythoncom
            pythoncom.CoInitialize()
            print("[VOZ] COM inicializado (Windows)")
        except ImportError:
            pass
        except Exception:
            pass

        engine = None
        try:
            engine = pyttsx3.init()
            engine.setProperty('rate', 155)
            voices = engine.getProperty('voices')
            for v in voices:
                nl = v.name.lower()
                if any(k in nl for k in ('brazil', 'portug', 'portuguese')):
                    engine.setProperty('voice', v.id)
                    print(f"[VOZ] Voz PT-BR: {v.name}")
                    break
            self._engine_ok = True
        except Exception as e:
            print(f"[VOZ] ERRO init: {e}")
            return

        while True:
            try:
                txt = self.fila.get(timeout=1)
            except queue.Empty:
                continue
            try:
                engine.say(txt)
                engine.runAndWait()
                self._falhas = 0
            except Exception as e:
                self._falhas += 1
                print(f"[VOZ] ERRO falar: {e}")
                if self._falhas >= 3:
                    try:
                        try:
                            engine.stop()
                        except Exception:
                            pass
                        try:
                            import pythoncom
                            pythoncom.CoInitialize()
                        except Exception:
                            pass
                        engine = pyttsx3.init()
                        engine.setProperty('rate', 155)
                        self._falhas = 0
                        self._engine_ok = True
                    except Exception:
                        self._engine_ok = False
                        time.sleep(2)

    def falar(self, chave, texto, urgente=False):
        if not self._engine_ok:
            print(f"  [VOZ OFF] {texto}")
            return
        agora = time.time()
        cd = self._cooldowns.get(chave, 3.0)
        if (agora - self._ultimos[chave]) < cd:
            return
        if urgente:
            self._limpar()
        if self.fila.qsize() < 5:
            self.fila.put(texto)
            self._ultimos[chave] = agora
            self._t_ultima_fala = agora
            print(f"  [VOZ] {texto}")

    def forcar(self, chave, texto):
        self._limpar()
        self.fila.put(texto)
        agora = time.time()
        self._ultimos[chave] = agora
        self._t_ultima_fala = agora
        print(f"  [VOZ!] {texto}")

    def _limpar(self):
        while not self.fila.empty():
            try:
                self.fila.get_nowait()
            except queue.Empty:
                break

    def tempo_silencio(self):
        return time.time() - self._t_ultima_fala

    @property
    def funcionando(self):
        return self._engine_ok


# ============================================================
# 4. RASTREADOR — COM EMA + COMPENSAÇÃO DE CÂMERA
# ============================================================
class Rastreador:
    def __init__(self):
        self.historicos = defaultdict(lambda: deque(maxlen=HISTORICO_MAX))
        self.ultimo_visto = {}
        self.bbox_largura = {}
        self.ghosts = {}
        self._ema = {}
        self.cam_vx = 0.0
        self.cam_vy = 0.0

    def atualizar(self, tid, cx, cy, t, bbox_w=0):
        if tid in self._ema:
            ox, oy = self._ema[tid]
            sx = EMA_ALPHA * cx + (1 - EMA_ALPHA) * ox
            sy = EMA_ALPHA * cy + (1 - EMA_ALPHA) * oy
        else:
            sx, sy = float(cx), float(cy)
        self._ema[tid] = (sx, sy)

        self.historicos[tid].append((sx, sy, t))
        self.ultimo_visto[tid] = t
        if bbox_w > 0:
            self.bbox_largura[tid] = bbox_w
        if tid in self.ghosts:
            del self.ghosts[tid]

    def estimar_movimento_camera(self):
        vels = []
        for tid, hist in self.historicos.items():
            if len(hist) < 2:
                continue
            p0 = hist[-2]
            p1 = hist[-1]
            dt = p1[2] - p0[2]
            if dt < 0.01:
                continue
            vx = (p1[0] - p0[0]) / dt
            vy = (p1[1] - p0[1]) / dt
            vels.append((vx, vy))

        if len(vels) < CAMERA_COMP_MIN_OBJETOS:
            self.cam_vx = 0.0
            self.cam_vy = 0.0
            return

        vxs = sorted([v[0] for v in vels])
        vys = sorted([v[1] for v in vels])
        self.cam_vx = vxs[len(vxs) // 2]
        self.cam_vy = vys[len(vys) // 2]

    def criar_fantasma(self, tid, dados):
        self.ghosts[tid] = {
            "cx": dados["cx"], "cy": dados["cy"],
            "conf": dados["conf"],
            "frames": GHOST_FRAMES_MAX,
            "bbox": dados["bbox"],
            "nome": dados["nome"],
            "classif": dados.get("classif", "PARADO"),
            "vel": dados.get("vel", 0),
        }

    def atualizar_fantasmas(self):
        mortos = []
        for tid, g in self.ghosts.items():
            g["frames"] -= 1
            g["conf"] = max(0.05, g["conf"] - GHOST_DECAY_CONF)
            if g["frames"] <= 0:
                mortos.append(tid)
        for tid in mortos:
            del self.ghosts[tid]

    def limpar(self, agora, timeout=3.0):
        mortos = [k for k, v in self.ultimo_visto.items()
                  if agora - v > timeout]
        for k in mortos:
            self.historicos.pop(k, None)
            self.ultimo_visto.pop(k, None)
            self.bbox_largura.pop(k, None)
            self._ema.pop(k, None)

    def cinematica(self, tid, w_frame=640, h_frame=480):
        h = self.historicos.get(tid)
        if not h or len(h) < 3:
            return 0, 0, 0, False, False
        pts = list(h)
        n = min(8, len(pts))
        p = pts[-n:]
        dt = p[-1][2] - p[0][2]
        if dt < 0.05:
            return 0, 0, 0, False, False

        vxs, vys, pesos = [], [], []
        for i in range(1, len(p)):
            dt_par = p[i][2] - p[i - 1][2]
            if dt_par < 0.001:
                continue
            vx = (p[i][0] - p[i - 1][0]) / dt_par - self.cam_vx
            vy = (p[i][1] - p[i - 1][1]) / dt_par - self.cam_vy
            vxs.append(vx * i)
            vys.append(vy * i)
            pesos.append(i)

        if not pesos:
            return 0, 0, 0, False, False
        sp = sum(pesos)
        vx = sum(vxs) / sp
        vy = sum(vys) / sp
        vel = math.sqrt(vx ** 2 + vy ** 2)
        em_mov = vel > VEL_PARADO_PXS

        centro_x = w_frame / 2
        no_esq = p[-1][0] < centro_x
        aprox_y = vy > VEL_APROXIMANDO_PXS
        aprox_x = ((no_esq and vx > VEL_APROXIMANDO_PXS) or
                    (not no_esq and vx < -VEL_APROXIMANDO_PXS))
        aproximando = aprox_y or aprox_x

        return vel, vx, vy, em_mov, aproximando

    def classificar(self, tid, w=640, h=480):
        vel, vx, vy, mov, aprox = self.cinematica(tid, w, h)
        if aprox:
            return "APROXIMANDO", vel
        if mov:
            return "EM_MOVIMENTO", vel
        return "PARADO", vel

    def eh_emergencia(self, tid, w_frame):
        bw = self.bbox_largura.get(tid, 0)
        return (bw / w_frame) >= LIMIAR_EMERGENCIA_PCT if bw > 0 else False

    def eh_proximo(self, tid, w_frame):
        bw = self.bbox_largura.get(tid, 0)
        return (bw / w_frame) >= LIMIAR_PROXIMO_PCT if bw > 0 else False

    def historico_ok(self, tid, minimo=5):
        h = self.historicos.get(tid)
        return h is not None and len(h) >= minimo

    def trilha(self, tid, n=12):
        h = self.historicos.get(tid)
        if not h:
            return []
        return [(int(p[0]), int(p[1])) for p in list(h)[-n:]]


# ============================================================
# 5. AUXILIARES
# ============================================================
def dentro_roi(cx, cy, w, h):
    if not ROI_ATIVO:
        return True
    return (ROI_LEFT * w <= cx <= ROI_RIGHT * w and
            ROI_TOP * h <= cy <= ROI_BOTTOM * h)


def inferir_cor_semaforo(nome):
    n = nome.lower()
    if any(kw in n for kw in KW_VERMELHO):
        return "VERMELHO"
    if any(kw in n for kw in KW_VERDE):
        return "VERDE"
    if any(kw in n for kw in KW_AMARELO):
        return "AMARELO"
    return "DESCONHECIDO"


def categorizar_classe(nome):
    n = nome.lower().strip()
    if n in CLASSES_VEICULOS:
        return "veiculo"
    if n in CLASSES_FAIXA:
        return "faixa"
    if n in CLASSES_SEMAFORO:
        return "semaforo"
    return None


def preprocessar_frame(frame):
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    lab = cv2.merge([l, a, b])
    melhorado = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    kernel = np.array([[0, -0.5, 0], [-0.5, 3, -0.5], [0, -0.5, 0]])
    return cv2.filter2D(melhorado, -1, kernel)


def nome_veiculo_pt(nome_classe):
    return NOMES_PT.get(nome_classe.lower().strip(), "veículo")


def calcular_alinhamento_faixa(faixa_cx, wf):
    centro = wf / 2
    margem = wf * FAIXA_MARGEM_ALINHAMENTO
    diff = faixa_cx - centro
    if diff < -margem:
        return "ESQUERDA", abs(diff) / centro
    elif diff > margem:
        return "DIREITA", abs(diff) / centro
    else:
        return "ALINHADO", abs(diff) / centro


# ============================================================
# 6. CORES
# ============================================================
COR_CLASSIF = {
    "APROXIMANDO": (0, 0, 255),
    "EM_MOVIMENTO": (0, 140, 255),
    "PARADO": (0, 220, 100),
}
COR_ESTADO = {
    EST_INATIVO: (150, 150, 150),
    EST_RECONHECENDO: (255, 200, 0),
    EST_SEMAFORO: (0, 255, 255),
    EST_FAIXA: (255, 255, 0),
    EST_VIA_LIVRE: (200, 200, 200),
}
COR_SITUACAO = {
    "SEGURO": (0, 255, 80),
    "AGUARDE": (0, 180, 255),
    "PERIGO": (0, 0, 255),
    "---": (150, 150, 150),
}


def desenhar_roi(frame):
    if not ROI_ATIVO:
        return
    h, w = frame.shape[:2]
    pts = np.array([
        [int(ROI_LEFT * w), int(ROI_TOP * h)],
        [int(ROI_RIGHT * w), int(ROI_TOP * h)],
        [int(ROI_RIGHT * w), int(ROI_BOTTOM * h)],
        [int(ROI_LEFT * w), int(ROI_BOTTOM * h)]
    ])
    ov = frame.copy()
    cv2.polylines(ov, [pts], True, (255, 255, 0), 2)
    cv2.addWeighted(ov, 0.4, frame, 0.6, 0, frame)


# ============================================================
# 7. INICIALIZAÇÃO
# ============================================================
print("=" * 60)
print("  SISTEMA DE ASSISTENCIA PARA TRAVESSIA")
print("  Controle total do usuario: [A] liga / [A] desliga")
print("=" * 60)

voz = SistemaVoz()

print("\n[INFO] Carregando modelo YOLO...")
model = YOLO(MODELO_PATH)
print("[OK] Modelo carregado!\n")

CLASSES_VEICULOS = set()
CLASSES_FAIXA = set()
CLASSES_SEMAFORO = set()

print("[CLASSES DO MODELO]")
for idx, nome in model.names.items():
    n = nome.lower().strip()
    if n in KEYWORDS_VEICULOS:
        CLASSES_VEICULOS.add(n)
        tag = "VEICULO"
    elif n in KEYWORDS_FAIXA:
        CLASSES_FAIXA.add(n)
        tag = "FAIXA"
    elif n.startswith(KEYWORDS_SEMAFORO_PREFIXO):
        CLASSES_SEMAFORO.add(n)
        tag = "SEMAFORO"
    else:
        tag = "???"
    print(f"  {idx}: {nome:25s} -> {tag}")

print(f"\n  Veiculos : {CLASSES_VEICULOS or 'NENHUMA'}")
print(f"  Faixa    : {CLASSES_FAIXA or 'NENHUMA'}")
print(f"  Semaforo : {CLASSES_SEMAFORO or 'NENHUMA'}")

print(f"\n[INFO] Conectando camera: {FONTE_VIDEO}")
cam = CameraStream(FONTE_VIDEO)
time.sleep(1.5)

teste = cam.ler()
if teste is None:
    print("[AVISO] Aguardando camera...")
    time.sleep(3)
    teste = cam.ler()
    if teste is None:
        print("[ERRO] Camera nao conectada!")

print("[OK] Camera conectada!")
tracker = Rastreador()

time.sleep(0.5)
voz.forcar("sistema",
           "Sistema pronto. Pressione o botão para iniciar a análise. "
           "Pressione novamente para parar.")

print("\n" + "=" * 60)
print("  TECLAS:")
print("    A     = Iniciar / Parar analise")
print("    +/-   = Ajustar confianca")
print("    P     = Pausar")
print("    D     = Debug ON/OFF")
print("    R     = ROI ON/OFF")
print("    S     = Reset")
print("    ESC   = Sair")
print("=" * 60 + "\n")


# ============================================================
# 8. VARIÁVEIS DE ESTADO
# ============================================================
estado = EST_INATIVO
t_estado = time.time()
situacao_atual = "---"

# Reconhecimento
recon_frames = 0
recon_semaforo = 0
recon_faixa = 0

# Timer carros parados
t_todos_parados = None

# Semáforo
sem_cor_atual = "NENHUM"
sem_cor_anterior_estado = "NENHUM"
t_sem_perdido = None

# Upgrade de modo
upgrade_sem_count = 0
upgrade_faixa_count = 0

# NOVO: Alinhamento faixa
faixa_alinhada = False
faixa_centro_x = -1

# NOVO: Anúncio de veículos
veiculos_sessao = {}
estado_agregado_ant = "NENHUM"

# Geral
faixa_det = False
emergencia_ativa = False
veiculos_anterior = {}

fps_val = 0.0
cnt_fps = 0
t_fps = time.time()

pausado = False
modo_debug = True
frame_show = None


# ============================================================
# 9. TRANSIÇÃO DE ESTADO
# ============================================================
def entrar_estado(novo):
    global estado, t_estado, situacao_atual
    global t_todos_parados
    global sem_cor_anterior_estado, t_sem_perdido
    global upgrade_sem_count, upgrade_faixa_count
    global recon_frames, recon_semaforo, recon_faixa
    global faixa_alinhada, faixa_centro_x
    global veiculos_sessao, estado_agregado_ant

    estado = novo
    t_estado = time.time()
    situacao_atual = "---"
    t_todos_parados = None
    sem_cor_anterior_estado = "NENHUM"
    t_sem_perdido = None
    upgrade_sem_count = 0
    upgrade_faixa_count = 0
    recon_frames = 0
    recon_semaforo = 0
    recon_faixa = 0
    faixa_alinhada = False
    faixa_centro_x = -1
    veiculos_sessao = {}
    estado_agregado_ant = "NENHUM"
    print(f"[ESTADO] -> {novo}")


# ============================================================
# 10. LOOP PRINCIPAL
# ============================================================
try:
    while True:

        # ── Teclas ──
        k = cv2.waitKey(1) & 0xFF

        if k == 27:
            break

        elif k == ord('a'):
            if estado == EST_INATIVO:
                entrar_estado(EST_RECONHECENDO)
                voz.forcar("inicio",
                           "Iniciando análise. Verificando a via. Aguarde.")
                print("\n[ANALISE] ===== INICIADA =====")
            else:
                entrar_estado(EST_INATIVO)
                voz.forcar("cancelado", "Análise encerrada.")
                print("[ANALISE] ===== ENCERRADA =====\n")

        elif k == ord('+'):
            CONF_MINIMA = min(CONF_MINIMA + 0.05, 0.95)
            print(f"[CONF] -> {CONF_MINIMA:.2f}")

        elif k == ord('-'):
            CONF_MINIMA = max(CONF_MINIMA - 0.05, 0.10)
            print(f"[CONF] -> {CONF_MINIMA:.2f}")

        elif k == ord('p'):
            pausado = not pausado

        elif k == ord('d'):
            modo_debug = not modo_debug

        elif k == ord('r'):
            ROI_ATIVO = not ROI_ATIVO

        elif k == ord('s'):
            entrar_estado(EST_INATIVO)
            veiculos_anterior = {}
            tracker.ghosts.clear()
            voz.forcar("sistema", "Sistema reiniciado.")

        if pausado:
            if frame_show is not None:
                tmp = frame_show.copy()
                cv2.putText(tmp, "PAUSADO", (30, 240),
                            cv2.FONT_HERSHEY_SIMPLEX, 2,
                            (0, 255, 255), 4)
                cv2.imshow("Assistente Travessia", tmp)
            continue

        # ── Frame ──
        frame = cam.ler()
        if frame is None:
            time.sleep(0.05)
            continue

        agora = time.time()
        hf, wf = frame.shape[:2]
        tempo_no_estado = agora - t_estado

        cnt_fps += 1
        if agora - t_fps >= 1.0:
            fps_val = cnt_fps / (agora - t_fps)
            cnt_fps = 0
            t_fps = agora

        # ── YOLO ──
        frame_proc = preprocessar_frame(frame)
        results = model.track(
            frame_proc, persist=True, conf=CONF_MINIMA,
            imgsz=INFERENCIA_TAMANHO, verbose=False,
        )

        # ── Processar detecções ──
        veiculos = {}
        faixa_det = False
        faixa_centro_x = -1
        sem_cor_frame = "NENHUM"
        emergencia_ativa = False
        ids_detectados = set()
        n_sem_id = 0

        for r in results:
            if r.boxes is None:
                continue
            for box in r.boxes:
                cls_id = int(box.cls[0])
                nome = model.names.get(cls_id, f"cls_{cls_id}")
                conf = float(box.conf[0])
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                cx = (x1 + x2) // 2
                cy = (y1 + y2) // 2
                bbox_w = x2 - x1

                if not dentro_roi(cx, cy, wf, hf):
                    continue

                cat = categorizar_classe(nome)

                # ── Faixa ──
                if cat == "faixa":
                    faixa_det = True
                    faixa_centro_x = cx
                    cv2.rectangle(frame, (x1, y1), (x2, y2),
                                  (255, 200, 0), 2)
                    cv2.putText(frame, f"FAIXA {conf:.0%}",
                                (x1, y1 - 8),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                                (255, 200, 0), 2)
                    # Marcador central da faixa
                    cv2.circle(frame, (cx, cy), 6, (255, 200, 0), 2)
                    continue

                # ── Semáforo ──
                if cat == "semaforo":
                    sc = inferir_cor_semaforo(nome)
                    if sc != "DESCONHECIDO":
                        sem_cor_frame = sc
                    cor_s = {"VERMELHO": (0, 0, 255),
                             "VERDE": (0, 255, 0),
                             "AMARELO": (0, 255, 255)
                             }.get(sc, (200, 200, 200))
                    cv2.rectangle(frame, (x1, y1), (x2, y2),
                                  cor_s, 2)
                    cv2.putText(frame, f"SEM {sc} {conf:.0%}",
                                (x1, y1 - 8),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                                cor_s, 2)
                    continue

                # ── Veículo ──
                if cat == "veiculo":
                    tid = (int(box.id[0])
                           if box.id is not None else -1)
                    if tid < 0:
                        n_sem_id += 1
                        cv2.rectangle(frame, (x1, y1), (x2, y2),
                                      (180, 180, 180), 1)
                        continue

                    ids_detectados.add(tid)
                    tracker.atualizar(tid, cx, cy, agora, bbox_w)
                    classif, vel = tracker.classificar(tid, wf, hf)

                    if tracker.eh_emergencia(tid, wf):
                        emergencia_ativa = True

                    veiculos[tid] = {
                        "nome": nome, "conf": conf,
                        "cx": cx, "cy": cy,
                        "classif": classif, "vel": vel,
                        "bbox": (x1, y1, x2, y2),
                        "bbox_w": bbox_w, "tid": tid,
                    }

                    cor = COR_CLASSIF.get(classif, (200, 200, 200))
                    esp = 4 if tracker.eh_emergencia(tid, wf) else 2
                    cv2.rectangle(frame, (x1, y1), (x2, y2),
                                  cor, esp)
                    label = (f"ID{tid} {nome} {conf:.0%}"
                             f" | {classif} {vel:.0f}px/s")
                    cv2.putText(frame, label, (x1, y1 - 8),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.40,
                                cor, 2)
                    cv2.circle(frame, (cx, cy), 4, cor, -1)

                    trilha = tracker.trilha(tid, 15)
                    for i in range(1, len(trilha)):
                        cv2.line(frame, trilha[i - 1],
                                 trilha[i], cor, 2)

        # ── Compensação de movimento de câmera ──
        tracker.estimar_movimento_camera()

        # ── Ghosts ──
        for tid, dados in veiculos_anterior.items():
            if (tid not in ids_detectados and
                    tid not in tracker.ghosts):
                tracker.criar_fantasma(tid, dados)
        tracker.atualizar_fantasmas()

        n_ghosts = 0
        for tid, g in tracker.ghosts.items():
            if tid not in veiculos:
                veiculos[tid] = {
                    "nome": g["nome"], "conf": g["conf"],
                    "cx": g["cx"], "cy": g["cy"],
                    "classif": g["classif"], "vel": g["vel"],
                    "bbox": g["bbox"],
                    "bbox_w": g["bbox"][2] - g["bbox"][0],
                    "is_ghost": True, "tid": tid,
                }
                n_ghosts += 1
                x1g, y1g, x2g, y2g = g["bbox"]
                for seg in range(x1g, x2g, 10):
                    cv2.line(frame, (seg, y1g),
                             (min(seg + 5, x2g), y1g),
                             (100, 100, 100), 1)
                cv2.putText(frame,
                            f"GHOST {g['conf']:.0%}",
                            (x1g, y1g - 8),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.35, (120, 120, 200), 1)

        veiculos_anterior = {tid: v for tid, v in veiculos.items()
                             if not v.get("is_ghost", False)}
        tracker.limpar(agora)

        # ── Veículos reais ──
        veiculos_reais = {tid: v for tid, v in veiculos.items()
                          if not v.get("is_ghost", False)}
        nv_reais = len(veiculos_reais)

        sem_cor_atual = sem_cor_frame

        # ── NOVO: Anúncio de veículos e mudanças de estado ──
        if estado != EST_INATIVO:

            # Anunciar veículos novos
            for tid, v in veiculos_reais.items():
                if tid not in veiculos_sessao:
                    veiculos_sessao[tid] = {
                        "nome": v["nome"],
                        "ultimo_estado": v["classif"],
                        "t_detect": agora,
                    }
                    np_ = nome_veiculo_pt(v["nome"])
                    voz.falar("veiculo_novo",
                              f"{np_} detectado")
                else:
                    veiculos_sessao[tid]["ultimo_estado"] = v["classif"]

            # Limpar veículos que sumiram da sessão
            tids_ativos = set(veiculos_reais.keys())
            tids_mortos = [t for t in veiculos_sessao
                           if t not in tids_ativos
                           and agora - veiculos_sessao[t]["t_detect"] > 5.0]
            for t_id in tids_mortos:
                del veiculos_sessao[t_id]

            # Detectar mudança de estado agregado
            if nv_reais == 0:
                estado_agr = "SEM_VEICULOS"
            elif all(v["classif"] == "PARADO"
                     for v in veiculos_reais.values()):
                estado_agr = "TODOS_PARADOS"
            elif any(v["classif"] == "APROXIMANDO"
                     for v in veiculos_reais.values()):
                estado_agr = "APROXIMANDO"
            else:
                estado_agr = "EM_MOVIMENTO"

            if (estado_agr != estado_agregado_ant and
                    estado_agregado_ant != "NENHUM" and
                    estado not in (EST_RECONHECENDO,)):

                if estado_agr == "TODOS_PARADOS" and nv_reais > 0:
                    voz.falar("agr_mudanca",
                              "Todos os veículos pararam.")
                elif (estado_agr == "EM_MOVIMENTO" and
                      estado_agregado_ant == "TODOS_PARADOS"):
                    voz.falar("agr_mudanca",
                              "Atenção! Veículo voltou a se mover.",
                              urgente=True)
                elif estado_agr == "APROXIMANDO":
                    voz.falar("agr_mudanca",
                              "Veículo se aproximando!",
                              urgente=True)

            estado_agregado_ant = estado_agr

            # NOVO: Alerta de alta velocidade
            for v in veiculos_reais.values():
                if v["vel"] > VEL_ALTA_PXS:
                    np_ = nome_veiculo_pt(v["nome"])
                    voz.falar("perigo_velocidade",
                              f"PERIGO! {np_} em alta velocidade "
                              f"se aproximando!",
                              urgente=True)
                    break

        # ==================================================
        #  MÁQUINA DE ESTADOS
        # ==================================================

        # ── INATIVO ──
        if estado == EST_INATIVO:
            situacao_atual = "---"
            if emergencia_ativa:
                voz.falar("emergencia",
                          "Cuidado! Veículo muito próximo!",
                          urgente=True)

        # ── RECONHECENDO ──
        elif estado == EST_RECONHECENDO:
            situacao_atual = "---"
            recon_frames += 1

            if sem_cor_frame != "NENHUM":
                recon_semaforo += 1
            if faixa_det:
                recon_faixa += 1

            # Feedback de progresso (nunca silenciar)
            if tempo_no_estado > 1.5 and recon_frames % 25 == 0:
                itens = []
                if recon_semaforo > 0:
                    itens.append("semáforo")
                if recon_faixa > 0:
                    itens.append("faixa")
                if nv_reais > 0:
                    itens.append(f"{nv_reais} veículos")
                if itens:
                    voz.falar("recon_progresso",
                              f"Detectando: {', '.join(itens)}...")
                else:
                    voz.falar("recon_progresso",
                              "Analisando a via...")

            # Saída antecipada com alta confiança
            encerrar = False
            if recon_frames >= RECON_EARLY_MIN_FRAMES:
                ps = recon_semaforo / recon_frames
                pf = recon_faixa / recon_frames
                if ps >= RECON_EARLY_THRESHOLD or \
                   pf >= RECON_EARLY_THRESHOLD:
                    encerrar = True

            if tempo_no_estado >= TEMPO_RECON or encerrar:
                if recon_frames > 0:
                    ps = recon_semaforo / recon_frames
                    pf = recon_faixa / recon_frames
                else:
                    ps = pf = 0

                print(f"[RECON] Frames:{recon_frames}"
                      f" Sem:{ps:.0%} Faixa:{pf:.0%}")

                # PRIORIDADE: SEMÁFORO > FAIXA > VIA_LIVRE
                if ps >= RECON_THRESHOLD:
                    if pf >= RECON_THRESHOLD:
                        voz.forcar("recon_resultado",
                                   "Semáforo e faixa detectados. "
                                   "Vou monitorar o semáforo "
                                   "para você.")
                    else:
                        voz.forcar("recon_resultado",
                                   "Semáforo detectado. "
                                   "Monitorando para você.")
                    entrar_estado(EST_SEMAFORO)

                elif pf >= RECON_THRESHOLD:
                    voz.forcar("recon_resultado",
                               "Faixa de pedestre detectada. "
                               "Sem semáforo. "
                               "Primeiro, alinhe-se com a faixa.")
                    entrar_estado(EST_FAIXA)

                else:
                    if nv_reais == 0:
                        voz.forcar("recon_resultado",
                                   "Nenhuma faixa, semáforo ou "
                                   "veículo. Via livre. "
                                   "Pode atravessar com cuidado.")
                    else:
                        voz.forcar("recon_resultado",
                                   "Nenhuma faixa ou semáforo. "
                                   "Vou monitorar os veículos "
                                   "para você.")
                    entrar_estado(EST_VIA_LIVRE)

            if emergencia_ativa:
                voz.falar("emergencia",
                          "Perigo! Veículo muito próximo!",
                          urgente=True)

        # ── SEMÁFORO ──
        elif estado == EST_SEMAFORO:

            if sem_cor_frame != "NENHUM":
                t_sem_perdido = None

                # Mudança de cor
                if (sem_cor_frame != sem_cor_anterior_estado and
                        sem_cor_anterior_estado != "NENHUM"):
                    if sem_cor_frame == "VERDE":
                        voz.forcar("semaforo_cor",
                                   "Semáforo mudou para verde!")
                    elif sem_cor_frame == "VERMELHO":
                        voz.forcar("semaforo_cor",
                                   "Semáforo mudou para vermelho."
                                   " Pare.")
                    elif sem_cor_frame == "AMARELO":
                        voz.forcar("semaforo_cor",
                                   "Atenção, semáforo amarelo.")
                sem_cor_anterior_estado = sem_cor_frame

                # Análise por cor
                if sem_cor_frame == "VERDE":
                    # Verificar se veículos estão parados por 3s
                    if nv_reais == 0 and n_sem_id == 0:
                        situacao_atual = "SEGURO"
                        voz.falar("semaforo_pode",
                                  "Semáforo verde. Via livre. "
                                  "Pode atravessar.")
                    else:
                        todos_parados = True
                        for v in veiculos_reais.values():
                            if not tracker.historico_ok(v["tid"]):
                                todos_parados = False
                                break
                            if v["classif"] != "PARADO":
                                todos_parados = False
                                break
                        if n_sem_id > 0:
                            todos_parados = False

                        if todos_parados and nv_reais > 0:
                            if t_todos_parados is None:
                                t_todos_parados = agora
                            tempo_parado = agora - t_todos_parados

                            if tempo_parado >= TEMPO_PARADO_SEGURO:
                                situacao_atual = "SEGURO"
                                voz.falar("semaforo_pode",
                                          "Semáforo verde. Todos os "
                                          "veículos parados. "
                                          "Seguro atravessar.")
                            else:
                                situacao_atual = "AGUARDE"
                                rest = TEMPO_PARADO_SEGURO - tempo_parado
                                voz.falar("semaforo_veiculo",
                                          f"Semáforo verde. Veículos "
                                          f"parando. Aguarde "
                                          f"mais {rest:.0f} segundos.")
                        else:
                            t_todos_parados = None
                            situacao_atual = "AGUARDE"

                            tem_aprox = any(
                                v["classif"] == "APROXIMANDO"
                                for v in veiculos_reais.values()
                            )
                            if tem_aprox:
                                voz.falar("semaforo_veiculo",
                                          "Semáforo verde, mas veículo "
                                          "se aproximando. Aguarde.")
                            else:
                                voz.falar("semaforo_veiculo",
                                          "Semáforo verde. Veículos "
                                          "ainda em movimento. Aguarde.")

                elif sem_cor_frame == "VERMELHO":
                    situacao_atual = "AGUARDE"
                    t_todos_parados = None
                    voz.falar("semaforo_aguarde",
                              "Semáforo vermelho. Aguarde.")

                elif sem_cor_frame == "AMARELO":
                    situacao_atual = "AGUARDE"
                    t_todos_parados = None
                    voz.falar("semaforo_aguarde",
                              "Atenção, semáforo amarelo. Aguarde.")

            else:
                # Semáforo sumiu
                if t_sem_perdido is None:
                    t_sem_perdido = agora
                elif agora - t_sem_perdido > 4.0:
                    voz.falar("semaforo_perdido",
                              "Semáforo não está mais visível.")
                    if faixa_det:
                        voz.forcar("upgrade",
                                   "Faixa detectada. Alinhe-se "
                                   "com a faixa.")
                        entrar_estado(EST_FAIXA)
                    else:
                        voz.forcar("upgrade",
                                   "Monitorando veículos.")
                        entrar_estado(EST_VIA_LIVRE)

            if emergencia_ativa:
                voz.falar("emergencia",
                          "Perigo! Veículo muito próximo!",
                          urgente=True)
                situacao_atual = "PERIGO"

            # Heartbeat semáforo
            if voz.tempo_silencio() >= HEARTBEAT_INTERVAL:
                if sem_cor_frame == "VERMELHO":
                    voz.falar("heartbeat",
                              "Semáforo vermelho. Continue aguardando.")
                elif sem_cor_frame == "VERDE":
                    voz.falar("heartbeat",
                              f"Semáforo verde. {nv_reais} veículos "
                              f"na via.")
                elif sem_cor_frame == "AMARELO":
                    voz.falar("heartbeat",
                              "Semáforo amarelo. Atenção.")
                else:
                    voz.falar("heartbeat",
                              "Monitorando semáforo.")

        # ── FAIXA ──
        elif estado == EST_FAIXA:

            # ── NOVO: Alinhamento com a faixa ──
            if faixa_det and faixa_centro_x > 0:
                direcao, intensidade = calcular_alinhamento_faixa(
                    faixa_centro_x, wf)

                if direcao == "ESQUERDA":
                    if intensidade > 0.35:
                        voz.falar("faixa_alinhamento",
                                  "Ajuste bastante para a esquerda.")
                    else:
                        voz.falar("faixa_alinhamento",
                                  "Ajuste levemente para a esquerda.")
                    faixa_alinhada = False
                elif direcao == "DIREITA":
                    if intensidade > 0.35:
                        voz.falar("faixa_alinhamento",
                                  "Ajuste bastante para a direita.")
                    else:
                        voz.falar("faixa_alinhamento",
                                  "Ajuste levemente para a direita.")
                    faixa_alinhada = False
                else:
                    if not faixa_alinhada:
                        voz.falar("faixa_alinhamento",
                                  "Você está alinhado com a faixa. "
                                  "Levante a mão esquerda para "
                                  "sinalizar travessia.")
                        faixa_alinhada = True

                # Guia visual de alinhamento
                centro_frame = wf // 2
                cv2.line(frame, (centro_frame, hf // 3),
                         (centro_frame, 2 * hf // 3),
                         (0, 255, 255), 1)
                cv2.line(frame, (faixa_centro_x, hf // 3),
                         (faixa_centro_x, 2 * hf // 3),
                         (255, 200, 0), 2)
                cor_ali = ((0, 255, 0) if direcao == "ALINHADO"
                           else (0, 0, 255))
                cv2.arrowedLine(frame,
                                (centro_frame, hf // 2),
                                (faixa_centro_x, hf // 2),
                                cor_ali, 2)

            elif not faixa_det:
                faixa_alinhada = False

            # Lembrete periódico para levantar a mão
            if faixa_alinhada and nv_reais > 0 and tempo_no_estado > 8.0:
                voz.falar("faixa_acene",
                          "Levante a mão esquerda para os carros "
                          "pararem.")

            # Análise de veículos
            if nv_reais == 0 and n_sem_id == 0:
                situacao_atual = "SEGURO"
                voz.falar("faixa_livre",
                          "Via livre. Pode atravessar "
                          "pela faixa.")
                t_todos_parados = None

            else:
                todos_parados = True
                for v in veiculos_reais.values():
                    if not tracker.historico_ok(v["tid"]):
                        todos_parados = False
                        break
                    if v["classif"] != "PARADO":
                        todos_parados = False
                        break
                if n_sem_id > 0:
                    todos_parados = False

                if todos_parados and nv_reais > 0:
                    if t_todos_parados is None:
                        t_todos_parados = agora

                    tempo_parado = agora - t_todos_parados

                    if tempo_parado >= TEMPO_PARADO_SEGURO:
                        situacao_atual = "SEGURO"
                        voz.falar("faixa_parados",
                                  "Todos os veículos parados. "
                                  "Seguro atravessar pela faixa.")
                    else:
                        situacao_atual = "AGUARDE"
                        rest = TEMPO_PARADO_SEGURO - tempo_parado
                        voz.falar("faixa_parando",
                                  f"Veículos parando. Aguarde "
                                  f"mais {rest:.0f} segundos.")
                else:
                    t_todos_parados = None
                    situacao_atual = "AGUARDE"

                    tem_aprox = any(
                        v["classif"] == "APROXIMANDO"
                        for v in veiculos_reais.values()
                    )
                    if tem_aprox:
                        voz.falar("aproximando",
                                  "Veículo se aproximando. "
                                  "Aguarde.", urgente=True)
                    else:
                        voz.falar("faixa_movimento",
                                  "Veículos em movimento. "
                                  "Aguarde.")

            # Upgrade para SEMÁFORO
            if sem_cor_frame != "NENHUM":
                upgrade_sem_count += 1
            else:
                upgrade_sem_count = max(0,
                                        upgrade_sem_count - 1)

            if upgrade_sem_count >= UPGRADE_FRAMES:
                voz.forcar("upgrade",
                           "Semáforo detectado! Mudando "
                           "para monitoramento de semáforo.")
                entrar_estado(EST_SEMAFORO)

            if emergencia_ativa:
                voz.falar("emergencia",
                          "Perigo! Veículo muito próximo!",
                          urgente=True)
                situacao_atual = "PERIGO"

            # Heartbeat faixa
            if voz.tempo_silencio() >= HEARTBEAT_INTERVAL:
                if nv_reais > 0:
                    n_mov = sum(1 for v in veiculos_reais.values()
                                if v["classif"] != "PARADO")
                    n_par = nv_reais - n_mov
                    voz.falar("heartbeat",
                              f"Monitorando faixa. "
                              f"{n_mov} veículos em movimento, "
                              f"{n_par} parados.")
                else:
                    voz.falar("heartbeat",
                              "Monitorando faixa. Nenhum veículo.")

        # ── VIA LIVRE ──
        elif estado == EST_VIA_LIVRE:

            if nv_reais == 0 and n_sem_id == 0:
                situacao_atual = "SEGURO"
                voz.falar("via_livre",
                          "Via livre. Nenhum veículo. "
                          "Pode atravessar com cuidado.")
                t_todos_parados = None

            else:
                todos_parados = True
                for v in veiculos_reais.values():
                    if not tracker.historico_ok(v["tid"]):
                        todos_parados = False
                        break
                    if v["classif"] != "PARADO":
                        todos_parados = False
                        break
                if n_sem_id > 0:
                    todos_parados = False

                if todos_parados and nv_reais > 0:
                    if t_todos_parados is None:
                        t_todos_parados = agora

                    tempo_parado = agora - t_todos_parados

                    if tempo_parado >= TEMPO_PARADO_SEGURO:
                        situacao_atual = "SEGURO"
                        voz.falar("via_parados",
                                  "Todos os veículos parados. "
                                  "Seguro atravessar com cuidado.")
                    else:
                        situacao_atual = "AGUARDE"
                        rest = TEMPO_PARADO_SEGURO - tempo_parado
                        voz.falar("via_parando",
                                  f"Veículos parando. Aguarde "
                                  f"mais {rest:.0f} segundos.")
                else:
                    t_todos_parados = None
                    situacao_atual = "AGUARDE"

                    tem_aprox = any(
                        v["classif"] == "APROXIMANDO"
                        for v in veiculos_reais.values()
                    )
                    if tem_aprox:
                        voz.falar("aproximando",
                                  "Veículo se aproximando. "
                                  "Aguarde.", urgente=True)
                    else:
                        voz.falar("via_movimento",
                                  "Veículos em movimento. "
                                  "Aguarde.")

            # Upgrade para SEMÁFORO
            if sem_cor_frame != "NENHUM":
                upgrade_sem_count += 1
            else:
                upgrade_sem_count = max(0,
                                        upgrade_sem_count - 1)
            if upgrade_sem_count >= UPGRADE_FRAMES:
                voz.forcar("upgrade",
                           "Semáforo detectado! "
                           "Monitorando semáforo.")
                entrar_estado(EST_SEMAFORO)

            # Upgrade para FAIXA
            if faixa_det:
                upgrade_faixa_count += 1
            else:
                upgrade_faixa_count = max(0,
                                          upgrade_faixa_count - 1)
            if upgrade_faixa_count >= UPGRADE_FRAMES:
                voz.forcar("upgrade",
                           "Faixa de pedestre detectada. "
                           "Alinhe-se com a faixa.")
                entrar_estado(EST_FAIXA)

            if emergencia_ativa:
                voz.falar("emergencia",
                          "Perigo! Veículo muito próximo!",
                          urgente=True)
                situacao_atual = "PERIGO"

            # Heartbeat via livre
            if voz.tempo_silencio() >= HEARTBEAT_INTERVAL:
                if nv_reais > 0:
                    n_mov = sum(1 for v in veiculos_reais.values()
                                if v["classif"] != "PARADO")
                    voz.falar("heartbeat",
                              f"Monitorando via. "
                              f"{nv_reais} veículos detectados, "
                              f"{n_mov} em movimento.")
                else:
                    voz.falar("heartbeat",
                              "Monitorando via. Nenhum veículo.")

        # ==================================================
        #  VISUALIZAÇÃO
        # ==================================================
        desenhar_roi(frame)

        # ── Guia central da câmera (para alinhamento) ──
        if estado == EST_FAIXA:
            centro_y = hf // 2
            centro_x = wf // 2
            tam = 15
            cv2.line(frame, (centro_x - tam, centro_y),
                     (centro_x + tam, centro_y),
                     (0, 255, 255), 1)
            cv2.line(frame, (centro_x, centro_y - tam),
                     (centro_x, centro_y + tam),
                     (0, 255, 255), 1)

        # ── Banner ──
        if estado == EST_INATIVO:
            txt_b = "INATIVO - Pressione [A] para analisar"
        elif estado == EST_RECONHECENDO:
            rest = max(0, TEMPO_RECON - tempo_no_estado)
            txt_b = f"RECONHECENDO A VIA... ({rest:.1f}s)"
        elif estado == EST_SEMAFORO:
            txt_b = (f"MODO SEMAFORO | {sem_cor_atual}"
                     f" | {situacao_atual}")
        elif estado == EST_FAIXA:
            ali_txt = ("ALINHADO" if faixa_alinhada
                       else "ALINHAR")
            txt_b = (f"MODO FAIXA | {ali_txt}"
                     f" | {situacao_atual}")
        elif estado == EST_VIA_LIVRE:
            txt_b = f"MODO VIA LIVRE | {situacao_atual}"
        else:
            txt_b = estado

        cor_b = COR_SITUACAO.get(situacao_atual,
                                 COR_ESTADO.get(estado,
                                                (200, 200, 200)))
        tw = cv2.getTextSize(txt_b, cv2.FONT_HERSHEY_SIMPLEX,
                             0.68, 2)[0][0]
        cv2.rectangle(frame, (15, 10), (tw + 35, 48),
                      (0, 0, 0), -1)
        cv2.putText(frame, txt_b, (22, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.68, cor_b, 2)

        # ── Barra de situação ──
        if situacao_atual != "---":
            cor_sit = COR_SITUACAO.get(situacao_atual,
                                       (200, 200, 200))
            cv2.rectangle(frame, (0, 0), (wf, 6), cor_sit, -1)
            cv2.rectangle(frame, (0, hf - 6), (wf, hf),
                          cor_sit, -1)

        # ── Barra progresso RECONHECENDO ──
        bx, by = 22, 58
        if estado == EST_RECONHECENDO:
            prog = min(tempo_no_estado / TEMPO_RECON, 1.0)
            cv2.rectangle(frame, (bx, by),
                          (bx + 250, by + 14),
                          (40, 40, 40), -1)
            cv2.rectangle(frame, (bx, by),
                          (bx + int(250 * prog), by + 14),
                          (255, 200, 0), -1)
            itens_det = []
            if recon_semaforo > 0:
                itens_det.append("SEM")
            if recon_faixa > 0:
                itens_det.append("FAIXA")
            if nv_reais > 0:
                itens_det.append(f"{nv_reais}V")
            det_txt = (" | " + "+".join(itens_det)) if itens_det else ""
            cv2.putText(frame,
                        f"Escaneando via...{det_txt}",
                        (bx, by + 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.40,
                        (255, 220, 100), 1)

        # ── Timer carros parados ──
        if (estado in (EST_FAIXA, EST_VIA_LIVRE, EST_SEMAFORO) and
                t_todos_parados is not None):
            tp = agora - t_todos_parados
            prog = min(tp / TEMPO_PARADO_SEGURO, 1.0)
            cv2.rectangle(frame, (bx, by),
                          (bx + 250, by + 14),
                          (40, 40, 40), -1)
            cor_pg = ((0, 255, 80) if prog >= 1.0
                      else (0, 200, 255))
            cv2.rectangle(frame, (bx, by),
                          (bx + int(250 * prog), by + 14),
                          cor_pg, -1)
            cv2.putText(frame,
                        f"Parados: {tp:.1f}s / "
                        f"{TEMPO_PARADO_SEGURO:.0f}s",
                        (bx, by + 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.40,
                        (180, 220, 255), 1)

        # ── Lista veículos ──
        if estado in (EST_FAIXA, EST_VIA_LIVRE, EST_SEMAFORO):
            y_v = by + 50 if t_todos_parados else by + 10
            for tid_v, vv in veiculos_reais.items():
                np_ = nome_veiculo_pt(vv["nome"])
                cl = vv["classif"]
                cor_v = COR_CLASSIF.get(cl, (200, 200, 200))
                cv2.putText(frame,
                            f"  {np_}: {cl} "
                            f"({vv['vel']:.0f}px/s)",
                            (bx, y_v),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.38,
                            cor_v, 1)
                y_v += 18
                if y_v > hf - 100:
                    break

        # ── Instrução para modo FAIXA ──
        if estado == EST_FAIXA and nv_reais > 0:
            if faixa_alinhada:
                txt_inst = ">> LEVANTE A MAO ESQUERDA <<"
                cor_inst = (0, 100, 200)
            else:
                txt_inst = ">> ALINHE-SE COM A FAIXA <<"
                cor_inst = (0, 0, 180)
            tw_i = cv2.getTextSize(txt_inst,
                                   cv2.FONT_HERSHEY_SIMPLEX,
                                   0.55, 2)[0][0]
            xi = (wf - tw_i) // 2
            cv2.rectangle(frame,
                          (xi - 8, hf - 70),
                          (xi + tw_i + 8, hf - 45),
                          cor_inst, -1)
            cv2.putText(frame, txt_inst,
                        (xi, hf - 52),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                        (255, 255, 255), 2)

        # ── Emergência visual ──
        if emergencia_ativa:
            cv2.rectangle(frame, (0, 0), (wf, hf),
                          (0, 0, 255), 8)

        # ── Compensação de câmera visual ──
        if modo_debug and (abs(tracker.cam_vx) > 2 or
                           abs(tracker.cam_vy) > 2):
            cv2.putText(frame,
                        f"CAM: vx={tracker.cam_vx:.0f} "
                        f"vy={tracker.cam_vy:.0f}",
                        (bx, hf - 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.33,
                        (0, 200, 255), 1)

        # ── Painel lateral ──
        px = wf - 310
        ov = frame.copy()
        cv2.rectangle(ov, (px, 0), (wf, 220),
                      (10, 10, 10), -1)
        cv2.addWeighted(ov, 0.7, frame, 0.3, 0, frame)

        linhas_p = [
            (f"Estado   : {estado}",
             COR_ESTADO.get(estado, (200, 200, 200))),
            (f"Situacao : {situacao_atual}",
             COR_SITUACAO.get(situacao_atual, (150, 150, 150))),
            (f"FPS      : {fps_val:.1f}",
             (200, 255, 200)),
            (f"Veiculos : {nv_reais} "
             f"(+{n_ghosts}g +{n_sem_id}?)",
             (200, 255, 200)),
            (f"Semaforo : {sem_cor_atual}",
             (200, 255, 200)),
            (f"Faixa    : {'Sim' if faixa_det else 'Nao'}"
             f"{'  ALINHADO' if faixa_alinhada else ''}",
             (200, 255, 200)),
            (f"Silencio : {voz.tempo_silencio():.1f}s",
             (255, 200, 150) if voz.tempo_silencio() > 3
             else (160, 160, 160)),
            (f"CamComp  : ({tracker.cam_vx:.0f},"
             f"{tracker.cam_vy:.0f})",
             (160, 160, 160)),
            (f"Conf     : {CONF_MINIMA:.2f}",
             (160, 160, 160)),
            (f"[A]On/Off [ESC]Sair",
             (120, 120, 120)),
        ]
        for i, (t, c) in enumerate(linhas_p):
            cv2.putText(frame, t, (px + 8, 20 + i * 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.34, c, 1)

        # ── Debug ──
        if modo_debug:
            cor_vz = ((0, 255, 0) if voz.funcionando
                      else (0, 0, 255))
            dbg = (f"[DBG] Reais:{nv_reais} Ghost:{n_ghosts}"
                   f" SemID:{n_sem_id}"
                   f" Voz:{'OK' if voz.funcionando else 'ERR'}"
                   f" Agr:{estado_agregado_ant}")
            cv2.putText(frame, dbg, (10, hf - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.33,
                        cor_vz, 1)

        frame_show = frame
        cv2.imshow("Assistente Travessia", frame)

except KeyboardInterrupt:
    print("\n[INFO] Ctrl+C detectado.")
except Exception as e:
    print(f"\n[ERRO] {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

# ============================================================
# ENCERRAR
# ============================================================
cam.parar()
cv2.destroyAllWindows()
print("\n[INFO] Sistema encerrado.")