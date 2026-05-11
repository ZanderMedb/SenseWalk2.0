package com.travessia.segura.alert

import android.speech.tts.TextToSpeech
import android.util.Log

/**
 * Gerencia alertas por voz com:
 * - Debounce por frames (estabilidade antes de mudar estado)
 * - Cooldowns distintos para cada tipo de alerta
 * - Evita repetição excessiva de "via livre"
 */
class AlertManager(private val tts: TextToSpeech) {

    companion object {
        private const val TAG = "AlertManager"

        // Cooldowns em milissegundos
        private const val COOLDOWN_VIA_LIVRE_MS = 10000L       // 10s para repetir "via livre"
        private const val COOLDOWN_ALERTA_NOVO_MS = 2500L      // 2.5s para novo alerta de veículo
        private const val COOLDOWN_ALERTA_MESMO_MS = 5000L     // 5s para repetir mesmo alerta
        private const val COOLDOWN_TRANSICAO_MS = 800L         // 0.8s ao mudar de estado

        // Frames necessários para confirmar mudança de estado
        private const val FRAMES_CONFIRMAR_LIVRE = 20    // ~0.7s @30fps - precisa ter certeza
        private const val FRAMES_CONFIRMAR_VEICULO = 3   // Reagir rápido ao perigo
    }

    enum class Estado {
        DESCONHECIDO,
        VIA_LIVRE,
        VEICULO_DETECTADO
    }

    // Estado atual confirmado
    var estadoAtual: Estado = Estado.DESCONHECIDO
        private set

    // Contadores de frames para debounce
    private var framesSemVeiculo = 0
    private var framesComVeiculo = 0

    // Controle de tempo
    private var ultimaFalaTimestamp = 0L
    private var ultimaMensagem = ""
    private var ultimoVeiculoFalado = ""

    // Callback para atualizar UI
    var onEstadoChanged: ((Estado, String) -> Unit)? = null

    /**
     * Chamado a cada frame com as detecções de veículos.
     * @param veiculos Lista de detecções que são veículos
     * @param frameWidth Largura do frame para estimar proximidade
     * @param frameHeight Altura do frame para estimar proximidade
     */
    fun processarFrame(
        veiculos: List<com.travessia.segura.detection.RawDetection>,
        frameWidth: Int = 640,
        frameHeight: Int = 480
    ) {
        if (veiculos.isEmpty()) {
            framesSemVeiculo++
            framesComVeiculo = 0

            // Confirmar via livre após N frames consecutivos sem veículos
            if (framesSemVeiculo >= FRAMES_CONFIRMAR_LIVRE) {
                confirmarViaLivre()
            }
        } else {
            framesComVeiculo++
            framesSemVeiculo = 0

            // Reagir rápido a veículos
            if (framesComVeiculo >= FRAMES_CONFIRMAR_VEICULO) {
                confirmarVeiculo(veiculos, frameWidth, frameHeight)
            }
        }
    }

    private fun confirmarViaLivre() {
        val agora = System.currentTimeMillis()

        // Se já estava em via livre, respeitar cooldown longo
        if (estadoAtual == Estado.VIA_LIVRE) {
            if (agora - ultimaFalaTimestamp < COOLDOWN_VIA_LIVRE_MS) {
                return // Ainda dentro do cooldown, não repetir
            }
        }

        // Se acabou de sair de VEICULO_DETECTADO, esperar transição
        if (estadoAtual == Estado.VEICULO_DETECTADO) {
            if (agora - ultimaFalaTimestamp < COOLDOWN_TRANSICAO_MS) {
                return
            }
        }

        val mudouEstado = estadoAtual != Estado.VIA_LIVRE
        estadoAtual = Estado.VIA_LIVRE

        falar("Via livre")

        if (mudouEstado) {
            onEstadoChanged?.invoke(Estado.VIA_LIVRE, "Via livre")
            Log.i(TAG, "🟢 Estado → VIA_LIVRE")
        }
    }

    private fun confirmarVeiculo(
        veiculos: List<com.travessia.segura.detection.RawDetection>,
        frameWidth: Int,
        frameHeight: Int
    ) {
        val agora = System.currentTimeMillis()

        // Encontrar o veículo mais relevante (mais próximo/confiante)
        val principal = veiculos.maxByOrNull {
            // Priorizar: confiança + tamanho relativo (proxy para proximidade)
            val areaRelativa = it.area / (frameWidth * frameHeight).toFloat()
            it.confidence * 0.6f + areaRelativa * 100f * 0.4f
        } ?: return

        val nomeVeiculo = traduzirClasse(principal.className)
        val proximidade = estimarProximidade(principal, frameWidth, frameHeight)
        val mensagem = construirMensagem(nomeVeiculo, proximidade, veiculos.size)

        // Cooldown: diferente se é o mesmo veículo ou um novo
        val cooldown = if (nomeVeiculo == ultimoVeiculoFalado) {
            COOLDOWN_ALERTA_MESMO_MS
        } else {
            COOLDOWN_ALERTA_NOVO_MS
        }

        // Se mudou de estado (era via livre), falar imediatamente
        val mudouEstado = estadoAtual != Estado.VEICULO_DETECTADO

        if (mudouEstado || (agora - ultimaFalaTimestamp >= cooldown)) {
            estadoAtual = Estado.VEICULO_DETECTADO
            ultimoVeiculoFalado = nomeVeiculo
            falar(mensagem)
            onEstadoChanged?.invoke(Estado.VEICULO_DETECTADO, mensagem)

            if (mudouEstado) {
                Log.i(TAG, "🔴 Estado → VEICULO_DETECTADO: $mensagem")
            }
        }
    }

    private fun construirMensagem(
        nomeVeiculo: String,
        proximidade: Proximidade,
        totalVeiculos: Int
    ): String {
        val prefixo = when (proximidade) {
            Proximidade.MUITO_PROXIMO -> "Cuidado!"
            Proximidade.PROXIMO -> "Atenção!"
            Proximidade.DISTANTE -> "Atenção,"
        }

        val distancia = when (proximidade) {
            Proximidade.MUITO_PROXIMO -> "muito próximo"
            Proximidade.PROXIMO -> "próximo"
            Proximidade.DISTANTE -> "detectado"
        }

        val complemento = if (totalVeiculos > 1) {
            " $totalVeiculos veículos na via."
        } else {
            ""
        }

        return "$prefixo $nomeVeiculo $distancia.$complemento"
    }

    private fun traduzirClasse(className: String): String {
        return when (className.lowercase()) {
            "car" -> "carro"
            "truck" -> "caminhão"
            "bus" -> "ônibus"
            "motorcycle", "motorbike" -> "moto"
            "bicycle", "bike" -> "bicicleta"
            "person" -> "pessoa"
            "train" -> "trem"
            else -> className
        }
    }

    enum class Proximidade {
        MUITO_PROXIMO,
        PROXIMO,
        DISTANTE
    }

    private fun estimarProximidade(
        detection: com.travessia.segura.detection.RawDetection,
        frameWidth: Int,
        frameHeight: Int
    ): Proximidade {
        val areaFrame = frameWidth.toFloat() * frameHeight.toFloat()
        val areaRelativa = detection.area / areaFrame

        return when {
            areaRelativa > 0.25f -> Proximidade.MUITO_PROXIMO  // >25% do frame
            areaRelativa > 0.08f -> Proximidade.PROXIMO        // >8% do frame
            else -> Proximidade.DISTANTE
        }
    }

    private fun falar(mensagem: String) {
        // Interromper fala anterior se houver
        tts.stop()
        tts.speak(mensagem, TextToSpeech.QUEUE_FLUSH, null, "alert_${System.nanoTime()}")
        ultimaFalaTimestamp = System.currentTimeMillis()
        ultimaMensagem = mensagem
        Log.d(TAG, "🔊 Falou: \"$mensagem\"")
    }

    /**
     * Resetar estado (ex: ao pausar/parar análise)
     */
    fun reset() {
        estadoAtual = Estado.DESCONHECIDO
        framesSemVeiculo = 0
        framesComVeiculo = 0
        ultimaFalaTimestamp = 0L
        ultimaMensagem = ""
        ultimoVeiculoFalado = ""
        tts.stop()
        Log.i(TAG, "♻️ AlertManager resetado")
    }

    /**
     * Retorna informação textual do estado atual para a UI
     */
    fun getStatusText(): String {
        return when (estadoAtual) {
            Estado.DESCONHECIDO -> "Aguardando..."
            Estado.VIA_LIVRE -> "✅ Via livre"
            Estado.VEICULO_DETECTADO -> "⚠️ $ultimaMensagem"
        }
    }
}