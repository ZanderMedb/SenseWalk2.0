package com.travessia.segura.camera

import android.graphics.Bitmap
import android.util.Log
import com.travessia.segura.config.AppConfig
import com.travessia.segura.detection.*
import com.travessia.segura.logic.StateMachine
import com.travessia.segura.tracking.Rastreador
import com.travessia.segura.ui.OverlayView

/**
 * Processa frames vindos do ESP32 (Bitmap direto, sem ImageProxy).
 * Equivalente ao FrameAnalyzer mas para fonte HTTP.
 */
class EspFrameProcessor(
    private val config: AppConfig,
    private val detector: YoloDetector,
    private val iouTracker: SimpleIoUTracker,
    private val tracker: Rastreador,
    private val stateMachine: StateMachine,
    private val onStatusUpdate: (String, String, Int, String) -> Unit,
    private val onOverlayUpdate: (List<OverlayView.BoxInfo>, Int, Int, Int) -> Unit
) {
    companion object {
        private const val TAG = "EspFrameProcessor"
    }

    private var frameCount = 0L

    /**
     * Processa um frame Bitmap vindo do ESP32.
     * Chamado na thread principal - o processamento pesado (detecção) é síncrono aqui,
     * então idealmente chame de uma thread/coroutine de background.
     */
    fun processarFrame(bitmap: Bitmap) {
        if (stateMachine.estado == AppConfig.EST_INATIVO) return
        if (!detector.isReady) return

        try {
            processarInterno(bitmap)
        } catch (e: Exception) {
            Log.e(TAG, "Erro ao processar frame ESP: ${e.message}")
        }
    }

    private fun processarInterno(bitmap: Bitmap) {
        frameCount++
        val agora = System.currentTimeMillis() / 1000.0

        val wf = bitmap.width
        val hf = bitmap.height

        // 1. Detecção YOLO (sem rotação pois o ESP já envia na orientação correta)
        val rawDetections = detector.detectar(bitmap, config.confMinima, 0)

        // 2. Tracking IoU
        val tracked = iouTracker.update(rawDetections)

        // 3. Separar categorias
        val veiculos = mutableMapOf<Int, VeiculoInfo>()
        var faixaDet = false
        var faixaCentroX = -1f
        var semCorFrame = "NENHUM"
        var nSemId = 0

        val overlayBoxes = mutableListOf<OverlayView.BoxInfo>()

        for (det in tracked) {
            val cx = det.cx
            val cy = det.cy

            if (!config.dentroRoi(cx, cy, wf, hf)) continue

            when (config.categorizarClasse(det.className)) {
                "faixa" -> {
                    faixaDet = true
                    faixaCentroX = cx
                    overlayBoxes.add(OverlayView.BoxInfo(
                        x1 = det.x1, y1 = det.y1, x2 = det.x2, y2 = det.y2,
                        label = config.tr("object_crosswalk"),
                        confidence = det.confidence,
                        color = OverlayView.COLOR_FAIXA
                    ))
                }

                "semaforo" -> {
                    val cor = config.inferirCorSemaforo(det.className)
                    if (cor != "DESCONHECIDO") semCorFrame = cor
                    val semColor = when (cor) {
                        "VERMELHO" -> OverlayView.COLOR_SEM_VERMELHO
                        "VERDE" -> OverlayView.COLOR_SEM_VERDE
                        "AMARELO" -> OverlayView.COLOR_SEM_AMARELO
                        else -> OverlayView.COLOR_SEM_OUTRO
                    }
                    overlayBoxes.add(OverlayView.BoxInfo(
                        x1 = det.x1, y1 = det.y1, x2 = det.x2, y2 = det.y2,
                        label = config.nomeCorSemaforo(cor).replaceFirstChar { it.uppercase() },
                        confidence = det.confidence,
                        color = semColor
                    ))
                }

                "veiculo" -> {
                    val tid = det.trackId
                    if (tid < 0) { nSemId++; continue }

                    tracker.atualizar(tid, cx, cy, agora, det.bboxW.toInt())
                    val (classif, vel) = tracker.classificar(tid, wf, hf)

                    veiculos[tid] = VeiculoInfo(
                        nome = det.className,
                        conf = det.confidence,
                        cx = cx, cy = cy,
                        classif = classif,
                        vel = vel,
                        bbox = floatArrayOf(det.x1, det.y1, det.x2, det.y2),
                        bboxW = det.bboxW,
                        tid = tid
                    )

                    val boxColor = when (classif) {
                        "APROXIMANDO" -> OverlayView.COLOR_APROXIMANDO
                        "EM_MOVIMENTO" -> OverlayView.COLOR_EM_MOVIMENTO
                        else -> OverlayView.COLOR_PARADO
                    }
                    val sufixo = config.sufixoMovimento(classif)
                    overlayBoxes.add(OverlayView.BoxInfo(
                        x1 = det.x1, y1 = det.y1, x2 = det.x2, y2 = det.y2,
                        label = "${config.nomeVeiculo(det.className)} $sufixo",
                        confidence = det.confidence,
                        color = boxColor
                    ))
                }
            }
        }

        tracker.limpar(agora)

        // 4. Atualizar overlay usando apenas a rotação visual configurada.
        // A inferência da IA continua igual, sem alterar a lógica do modelo.
        onOverlayUpdate(overlayBoxes, wf, hf, config.espPreviewRotation)

        // 5. Atualizar StateMachine
        stateMachine.processar(
            veiculosReais = veiculos,
            nSemId = nSemId,
            semCorFrame = semCorFrame,
            faixaDet = faixaDet,
            faixaCx = faixaCentroX,
            wf = wf,
            hf = hf
        )

        // 6. Notificar UI
        onStatusUpdate(
            stateMachine.estado,
            stateMachine.situacaoAtual,
            veiculos.size,
            stateMachine.semCorAtual
        )
    }

    fun resetar() {
        iouTracker.reset()
        tracker.resetar()
    }
}