package com.travessia.segura.ui

import android.os.Bundle
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import com.travessia.segura.config.AppConfig
import android.view.View

class SettingsActivity : AppCompatActivity() {

    private lateinit var config: AppConfig
    private lateinit var container: LinearLayout

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        config = AppConfig(this)

        val scrollView = ScrollView(this).apply {
            setPadding(32, 32, 32, 32)
        }

        container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            )
        }

        // ── Título ──
        addTitle("⚙ CONFIGURAÇÕES")

        // ── Detecção ──
        addSection("DETECÇÃO")
        addSliderFloat("Confiança Mínima", config.confMinima, 0.05f, 0.95f, 0.05f) {
            config.confMinima = it
        }
        addSpinnerInt("Tamanho Inferência", config.inferenciaTamanho,
            listOf(160, 224, 320, 416, 640)
        ) {
            config.inferenciaTamanho = it
        }
        addSliderInt("Histórico Máx", config.historicoMax, 5, 60) {
            config.historicoMax = it
        }

        // ── Velocidades ──
        addSection("VELOCIDADES (px/s)")
        addSliderFloat("Vel. Parado", config.velParadoPxs, 5f, 50f, 1f) {
            config.velParadoPxs = it
        }
        addSliderFloat("Vel. Aproximando", config.velAproximandoPxs, 10f, 80f, 1f) {
            config.velAproximandoPxs = it
        }

        // ── Proximidade ──
        addSection("PROXIMIDADE")
        addSliderFloat("Limiar Próximo", config.limiarProximoPct, 0.10f, 0.60f, 0.02f) {
            config.limiarProximoPct = it
        }

        // ── Lógica / Tempos ──
        addSection("TEMPOS E LÓGICA")
        addSliderFloat("Tempo Reconhecimento", config.tempoRecon, 1f, 10f, 0.5f) {
            config.tempoRecon = it
        }
        addSliderFloat("Tempo Parado Seguro", config.tempoParadoSeguro, 1f, 10f, 0.5f) {
            config.tempoParadoSeguro = it
        }
        addSliderFloat("Recon Threshold", config.reconThreshold, 0.05f, 0.80f, 0.05f) {
            config.reconThreshold = it
        }
        addSliderFloat("Recon Early Threshold", config.reconEarlyThreshold, 0.10f, 0.90f, 0.05f) {
            config.reconEarlyThreshold = it
        }
        addSliderInt("Recon Early Min Frames", config.reconEarlyMinFrames, 5, 60) {
            config.reconEarlyMinFrames = it
        }
        addSliderInt("Upgrade Frames", config.upgradeFrames, 3, 30) {
            config.upgradeFrames = it
        }

        // ── ROI ──
        addSection("REGIÃO DE INTERESSE (ROI)")
        addSwitch("ROI Ativo", config.roiAtivo) { config.roiAtivo = it }
        addSliderFloat("ROI Top", config.roiTop, 0f, 0.50f, 0.01f) {
            config.roiTop = it
        }
        addSliderFloat("ROI Bottom", config.roiBottom, 0.50f, 1.0f, 0.01f) {
            config.roiBottom = it
        }
        addSliderFloat("ROI Left", config.roiLeft, 0f, 0.30f, 0.01f) {
            config.roiLeft = it
        }
        addSliderFloat("ROI Right", config.roiRight, 0.70f, 1.0f, 0.01f) {
            config.roiRight = it
        }

        // ── Suavização ──
        addSection("SUAVIZAÇÃO")
        addSliderFloat("EMA Alpha", config.emaAlpha, 0.10f, 0.90f, 0.05f) {
            config.emaAlpha = it
        }
        addSliderInt("Cam Comp Min Objetos", config.cameraCompMinObjetos, 1, 5) {
            config.cameraCompMinObjetos = it
        }
        addSliderFloat("Faixa Margem Alinhamento", config.faixaMargemAlinhamento,
            0.02f, 0.30f, 0.01f
        ) {
            config.faixaMargemAlinhamento = it
        }

        // ── Outros ──
        addSection("OUTROS")
        addSliderFloat("Heartbeat Interval", config.heartbeatInterval, 2f, 15f, 0.5f) {
            config.heartbeatInterval = it
        }
        addSliderFloat("Volume da Voz", config.volumeVoz, 0.1f, 1.0f, 0.1f) {
            config.volumeVoz = it
        }

        // ── Botão Reset ──
        addSection("")
        val btnReset = Button(this).apply {
            text = "RESETAR PARA PADRÃO"
            setOnClickListener {
                config.resetarParaPadrao()
                Toast.makeText(this@SettingsActivity,
                    "Configurações resetadas!", Toast.LENGTH_SHORT).show()
                recreate()
            }
        }
        container.addView(btnReset)

        scrollView.addView(container)
        setContentView(scrollView)
    }

    // ══════════════════════════════════════════
    //  HELPERS PARA GERAR UI
    // ══════════════════════════════════════════

    private fun addTitle(text: String) {
        container.addView(TextView(this).apply {
            this.text = text
            textSize = 22f
            setPadding(0, 0, 0, 24)
            setTextColor(0xFFFFFFFF.toInt())
        })
    }

    private fun addSection(text: String) {
        container.addView(TextView(this).apply {
            this.text = text
            textSize = 16f
            setPadding(0, 32, 0, 8)
            setTextColor(0xFF90CAF9.toInt())
        })
    }

    private fun addSliderFloat(
        label: String,
        initialValue: Float,
        min: Float,
        max: Float,
        step: Float,
        onChange: (Float) -> Unit
    ) {
        val steps = ((max - min) / step).toInt()
        val initialProgress = ((initialValue - min) / step).toInt().coerceIn(0, steps)

        val tvLabel = TextView(this).apply {
            text = "$label: %.3f".format(initialValue)
            textSize = 14f
            setTextColor(0xFFE0E0E0.toInt())
        }
        container.addView(tvLabel)

        val seekBar = SeekBar(this).apply {
            this.max = steps
            progress = initialProgress
            setPadding(0, 0, 0, 16)
            setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
                override fun onProgressChanged(sb: SeekBar?, progress: Int, fromUser: Boolean) {
                    val value = min + progress * step
                    tvLabel.text = "$label: %.3f".format(value)
                    onChange(value)
                }
                override fun onStartTrackingTouch(sb: SeekBar?) {}
                override fun onStopTrackingTouch(sb: SeekBar?) {}
            })
        }
        container.addView(seekBar)
    }

    private fun addSliderInt(
        label: String,
        initialValue: Int,
        min: Int,
        max: Int,
        onChange: (Int) -> Unit
    ) {
        val tvLabel = TextView(this).apply {
            text = "$label: $initialValue"
            textSize = 14f
            setTextColor(0xFFE0E0E0.toInt())
        }
        container.addView(tvLabel)

        val seekBar = SeekBar(this).apply {
            this.max = max - min
            progress = initialValue - min
            setPadding(0, 0, 0, 16)
            setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
                override fun onProgressChanged(sb: SeekBar?, progress: Int, fromUser: Boolean) {
                    val value = min + progress
                    tvLabel.text = "$label: $value"
                    onChange(value)
                }
                override fun onStartTrackingTouch(sb: SeekBar?) {}
                override fun onStopTrackingTouch(sb: SeekBar?) {}
            })
        }
        container.addView(seekBar)
    }

    private fun addSpinnerInt(
        label: String,
        initialValue: Int,
        options: List<Int>,
        onChange: (Int) -> Unit
    ) {
        val tvLabel = TextView(this).apply {
            text = label
            textSize = 14f
            setTextColor(0xFFE0E0E0.toInt())
        }
        container.addView(tvLabel)

        val spinner = Spinner(this).apply {
            adapter = ArrayAdapter(
                this@SettingsActivity,
                android.R.layout.simple_spinner_dropdown_item,
                options.map { it.toString() }
            )
            val idx = options.indexOf(initialValue).coerceAtLeast(0)
            setSelection(idx)
            onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
                override fun onItemSelected(
                    parent: AdapterView<*>?, view: View?, position: Int, id: Long
                ) {
                    onChange(options[position])
                }
                override fun onNothingSelected(parent: AdapterView<*>?) {}
            }
        }
        container.addView(spinner)
    }

    private fun addSwitch(
        label: String,
        initialValue: Boolean,
        onChange: (Boolean) -> Unit
    ) {
        val switch = Switch(this).apply {
            text = label
            isChecked = initialValue
            textSize = 14f
            setPadding(0, 8, 0, 16)
            setTextColor(0xFFE0E0E0.toInt())
            setOnCheckedChangeListener { _, isChecked -> onChange(isChecked) }
        }
        container.addView(switch)
    }
}