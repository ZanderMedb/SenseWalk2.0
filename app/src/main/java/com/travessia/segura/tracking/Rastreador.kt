package com.travessia.segura.tracking

import com.travessia.segura.config.AppConfig
import com.travessia.segura.detection.CinematicaResult
import kotlin.math.sqrt

/**
 * Rastreador simplificado.
 * EMA + cinemática. Sem ghosts, sem compensação de câmera, sem emergência.
 */
class Rastreador(private val config: AppConfig) {

    private val historicos = mutableMapOf<Int, ArrayDeque<Triple<Double, Double, Double>>>()
    private val ultimoVisto = mutableMapOf<Int, Double>()
    val bboxLargura = mutableMapOf<Int, Int>()
    private val ema = mutableMapOf<Int, Pair<Double, Double>>()

    fun atualizar(tid: Int, cx: Float, cy: Float, t: Double, bboxW: Int = 0) {
        val (sx, sy) = if (tid in ema) {
            val (ox, oy) = ema[tid]!!
            val alpha = config.emaAlpha.toDouble()
            Pair(
                alpha * cx + (1 - alpha) * ox,
                alpha * cy + (1 - alpha) * oy
            )
        } else {
            Pair(cx.toDouble(), cy.toDouble())
        }

        ema[tid] = Pair(sx, sy)

        val hist = historicos.getOrPut(tid) { ArrayDeque() }
        hist.addLast(Triple(sx, sy, t))
        while (hist.size > config.historicoMax) hist.removeFirst()

        ultimoVisto[tid] = t
        if (bboxW > 0) bboxLargura[tid] = bboxW
    }

    fun limpar(agora: Double, timeout: Double = 3.0) {
        val mortos = ultimoVisto.filter { agora - it.value > timeout }.keys.toList()
        for (k in mortos) {
            historicos.remove(k)
            ultimoVisto.remove(k)
            bboxLargura.remove(k)
            ema.remove(k)
        }
    }

    fun cinematica(tid: Int, wFrame: Int = 640, hFrame: Int = 480): CinematicaResult {
        val h = historicos[tid]
        if (h == null || h.size < 3) {
            return CinematicaResult(0f, 0f, 0f, false, false)
        }

        val pts = h.toList()
        val n = minOf(8, pts.size)
        val p = pts.takeLast(n)
        val dt = p.last().third - p.first().third
        if (dt < 0.05) return CinematicaResult(0f, 0f, 0f, false, false)

        val vxs = mutableListOf<Double>()
        val vys = mutableListOf<Double>()
        val pesos = mutableListOf<Double>()

        for (i in 1 until p.size) {
            val dtPar = p[i].third - p[i - 1].third
            if (dtPar < 0.001) continue
            val vx = (p[i].first - p[i - 1].first) / dtPar
            val vy = (p[i].second - p[i - 1].second) / dtPar
            vxs.add(vx * i)
            vys.add(vy * i)
            pesos.add(i.toDouble())
        }

        if (pesos.isEmpty()) return CinematicaResult(0f, 0f, 0f, false, false)

        val sp = pesos.sum()
        val vx = (vxs.sum() / sp).toFloat()
        val vy = (vys.sum() / sp).toFloat()
        val vel = sqrt((vx * vx + vy * vy).toDouble()).toFloat()
        val emMov = vel > config.velParadoPxs

        val centroX = wFrame / 2f
        val noEsq = p.last().first < centroX
        val aproxY = vy > config.velAproximandoPxs
        val aproxX = (noEsq && vx > config.velAproximandoPxs) ||
                (!noEsq && vx < -config.velAproximandoPxs)
        val aproximando = aproxY || aproxX

        return CinematicaResult(vel, vx, vy, emMov, aproximando)
    }

    fun classificar(tid: Int, w: Int = 640, h: Int = 480): Pair<String, Float> {
        val c = cinematica(tid, w, h)
        return when {
            c.aproximando -> "APROXIMANDO" to c.vel
            c.emMovimento -> "EM_MOVIMENTO" to c.vel
            else -> "PARADO" to c.vel
        }
    }

    fun ehProximo(tid: Int, wFrame: Int): Boolean {
        val bw = bboxLargura[tid] ?: return false
        return (bw.toFloat() / wFrame) >= config.limiarProximoPct
    }

    fun historicoOk(tid: Int, minimo: Int = 5): Boolean {
        val h = historicos[tid] ?: return false
        return h.size >= minimo
    }

    fun resetar() {
        historicos.clear()
        ultimoVisto.clear()
        bboxLargura.clear()
        ema.clear()
    }
}