package com.travessia.segura.config

import android.content.Context
import android.content.SharedPreferences

/**
 * Configuração centralizada.
 * Valores otimizados para Galaxy S21 FE.
 */
class AppConfig(context: Context) {

    private val prefs: SharedPreferences =
        context.getSharedPreferences("travessia_config", Context.MODE_PRIVATE)

    // ── Classes do modelo ──
    val keywordsVeiculos      = setOf("car", "motorcycle", "bicycle", "truck", "ambulance")
    val keywordsFaixa         = setOf("crosswalk")
    val keywordsSemaforoPrefixo = "traffic-light"
    val kwVermelho = setOf("red")
    val kwVerde    = setOf("green")
    val kwAmarelo  = setOf("yellow")

    val nomesPt = mapOf(
        "car"        to "carro",
        "motorcycle" to "moto",
        "bicycle"    to "bicicleta",
        "truck"      to "caminhão",
        "ambulance"  to "ambulância"
    )

    val classNames = listOf(
        "car",                 // 0
        "motorcycle",          // 1
        "bicycle",             // 2
        "truck",               // 3
        "ambulance",           // 4
        "traffic-light-green", // 5
        "traffic-light-red",   // 6
        "traffic-light-yellow",// 7
        "crosswalk"            // 8
    )

    // ── Detecção ──
    // confMinima mais alta = menos ruído no celular (0.35 é um bom começo)
    var confMinima: Float
        get()  = prefs.getFloat("conf_minima", 0.20f)
        set(v) = prefs.edit().putFloat("conf_minima", v).apply()

    var inferenciaTamanho: Int
        get()  = prefs.getInt("inferencia_tamanho", 640)
        set(v) = prefs.edit().putInt("inferencia_tamanho", v).apply()

    var historicoMax: Int
        get()  = prefs.getInt("historico_max", 20)
        set(v) = prefs.edit().putInt("historico_max", v).apply()

    // ── Velocidades (px/s) ──
    var velParadoPxs: Float
        get()  = prefs.getFloat("vel_parado_pxs", 18f)
        set(v) = prefs.edit().putFloat("vel_parado_pxs", v).apply()

    var velAproximandoPxs: Float
        get()  = prefs.getFloat("vel_aproximando_pxs", 30f)
        set(v) = prefs.edit().putFloat("vel_aproximando_pxs", v).apply()

    // Removido velAltaPxs (não tem mais alerta de alta velocidade)

    // ── Proximidade ──
    var limiarProximoPct: Float
        get()  = prefs.getFloat("limiar_proximo_pct", 0.30f)
        set(v) = prefs.edit().putFloat("limiar_proximo_pct", v).apply()

    // ── Lógica ──
    var tempoRecon: Float
        get()  = prefs.getFloat("tempo_recon", 3.5f)
        set(v) = prefs.edit().putFloat("tempo_recon", v).apply()

    var tempoParadoSeguro: Float
        get()  = prefs.getFloat("tempo_parado_seguro", 3.0f)
        set(v) = prefs.edit().putFloat("tempo_parado_seguro", v).apply()

    var reconThreshold: Float
        get()  = prefs.getFloat("recon_threshold", 0.25f)
        set(v) = prefs.edit().putFloat("recon_threshold", v).apply()

    var reconEarlyThreshold: Float
        get()  = prefs.getFloat("recon_early_threshold", 0.50f)
        set(v) = prefs.edit().putFloat("recon_early_threshold", v).apply()

    var reconEarlyMinFrames: Int
        get()  = prefs.getInt("recon_early_min_frames", 15)
        set(v) = prefs.edit().putInt("recon_early_min_frames", v).apply()

    var upgradeFrames: Int
        get()  = prefs.getInt("upgrade_frames", 8)
        set(v) = prefs.edit().putInt("upgrade_frames", v).apply()

    // ── ROI ──
    var roiAtivo: Boolean
        get()  = prefs.getBoolean("roi_ativo", false)
        set(v) = prefs.edit().putBoolean("roi_ativo", v).apply()

    var roiTop: Float
        get()  = prefs.getFloat("roi_top", 0.05f)
        set(v) = prefs.edit().putFloat("roi_top", v).apply()

    var roiBottom: Float
        get()  = prefs.getFloat("roi_bottom", 0.95f)
        set(v) = prefs.edit().putFloat("roi_bottom", v).apply()

    var roiLeft: Float
        get()  = prefs.getFloat("roi_left", 0.02f)
        set(v) = prefs.edit().putFloat("roi_left", v).apply()

    var roiRight: Float
        get()  = prefs.getFloat("roi_right", 0.98f)
        set(v) = prefs.edit().putFloat("roi_right", v).apply()

    // ── Suavização ──
    var emaAlpha: Float
        get()  = prefs.getFloat("ema_alpha", 0.45f)
        set(v) = prefs.edit().putFloat("ema_alpha", v).apply()

    var cameraCompMinObjetos: Int
        get()  = prefs.getInt("camera_comp_min_objetos", 2)
        set(v) = prefs.edit().putInt("camera_comp_min_objetos", v).apply()

    // ── Faixa ──
    var faixaMargemAlinhamento: Float
        get()  = prefs.getFloat("faixa_margem_alinhamento", 0.10f)
        set(v) = prefs.edit().putFloat("faixa_margem_alinhamento", v).apply()

    // ── Heartbeat ──
    // Intervalo maior = menos interrupções de voz
    var heartbeatInterval: Float
        get()  = prefs.getFloat("heartbeat_interval", 8.0f)
        set(v) = prefs.edit().putFloat("heartbeat_interval", v).apply()

    // ── Volume ──
    var volumeVoz: Float
        get()  = prefs.getFloat("volume_voz", 1.0f)
        set(v) = prefs.edit().putFloat("volume_voz", v).apply()

    // ── Estados ──
    companion object {
        const val EST_INATIVO      = "INATIVO"
        const val EST_RECONHECENDO = "RECONHECENDO"
        const val EST_SEMAFORO     = "SEMAFORO"
        const val EST_FAIXA        = "FAIXA"
        const val EST_VIA_LIVRE    = "VIA_LIVRE"
    }

    // ── Helpers ──
    fun categorizarClasse(nome: String): String? {
        val n = nome.lowercase().trim()
        return when {
            n in keywordsVeiculos            -> "veiculo"
            n in keywordsFaixa               -> "faixa"
            n.startsWith(keywordsSemaforoPrefixo) -> "semaforo"
            else                             -> null
        }
    }

    fun inferirCorSemaforo(nome: String): String {
        val n = nome.lowercase()
        return when {
            kwVermelho.any { it in n } -> "VERMELHO"
            kwVerde.any    { it in n } -> "VERDE"
            kwAmarelo.any  { it in n } -> "AMARELO"
            else                       -> "DESCONHECIDO"
        }
    }

    fun nomeVeiculoPt(nomeClasse: String): String =
        nomesPt[nomeClasse.lowercase().trim()] ?: "veículo"

    fun dentroRoi(cx: Float, cy: Float, w: Int, h: Int): Boolean {
        if (!roiAtivo) return true
        return cx >= roiLeft * w && cx <= roiRight * w &&
                cy >= roiTop * h  && cy <= roiBottom * h
    }

    fun calcularAlinhamentoFaixa(faixaCx: Float, wf: Int): Pair<String, Float> {
        val centro = wf / 2f
        val margem = wf * faixaMargemAlinhamento
        val diff   = faixaCx - centro
        return when {
            diff < -margem -> "ESQUERDA" to (Math.abs(diff) / centro)
            diff >  margem -> "DIREITA"  to (Math.abs(diff) / centro)
            else           -> "ALINHADO" to (Math.abs(diff) / centro)
        }
    }

    fun resetarParaPadrao() = prefs.edit().clear().apply()
}
