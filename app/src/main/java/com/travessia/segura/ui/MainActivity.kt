package com.travessia.segura.ui

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.util.Log
import android.view.WindowManager
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.travessia.segura.R
import com.travessia.segura.camera.FrameAnalyzer
import com.travessia.segura.config.AppConfig
import com.travessia.segura.config.AppConfig.Companion.EST_INATIVO
import com.travessia.segura.config.AppConfig.Companion.EST_RECONHECENDO
import com.travessia.segura.detection.SimpleIoUTracker
import com.travessia.segura.detection.YoloDetector
import com.travessia.segura.logic.StateMachine
import com.travessia.segura.tracking.Rastreador
import com.travessia.segura.voice.VoiceSystem
import androidx.camera.core.*
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import android.util.Size
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

class MainActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "MainActivity"
        private const val CAMERA_PERMISSION_CODE = 100
    }

    // UI
    private lateinit var previewView: PreviewView
    private lateinit var overlayView: OverlayView
    private lateinit var tvEstado: TextView
    private lateinit var tvSituacao: TextView
    private lateinit var tvInfo: TextView
    private lateinit var tvDetectionCount: TextView
    private lateinit var tvFps: TextView
    private lateinit var btnToggle: Button
    private lateinit var btnConfig: Button

    // Engine
    private lateinit var config: AppConfig
    private lateinit var voz: VoiceSystem
    private lateinit var detector: YoloDetector
    private lateinit var iouTracker: SimpleIoUTracker
    private lateinit var rastreador: Rastreador
    private lateinit var stateMachine: StateMachine
    private lateinit var frameAnalyzer: FrameAnalyzer
    private lateinit var cameraExecutor: ExecutorService

    // Estado
    private var isActive = false

    // FPS
    private var frameCount = 0
    private var lastFpsTime = System.currentTimeMillis()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Manter tela ligada durante uso
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContentView(R.layout.activity_main)

        initViews()
        initEngine()
    }

    private fun initViews() {
        previewView       = findViewById(R.id.previewView)
        overlayView       = findViewById(R.id.overlayView)
        tvEstado          = findViewById(R.id.tvEstado)
        tvSituacao        = findViewById(R.id.tvSituacao)
        tvInfo            = findViewById(R.id.tvInfo)
        tvDetectionCount  = findViewById(R.id.tvDetectionCount)
        tvFps             = findViewById(R.id.tvFps)
        btnToggle         = findViewById(R.id.btnToggle)
        btnConfig         = findViewById(R.id.btnConfig)

        btnToggle.isEnabled = false
        btnToggle.setOnClickListener { toggleAnalysis() }
        btnConfig.setOnClickListener {
            startActivity(Intent(this, SettingsActivity::class.java))
        }

        tvInfo.text = "Carregando modelo..."
    }

    private fun initEngine() {
        cameraExecutor = Executors.newSingleThreadExecutor()
        config = AppConfig(this)

        // VoiceSystem inicializa TTS internamente
        voz = VoiceSystem(this, config)

        // Inicializar detector em background para não travar a UI
        Thread {
            detector = YoloDetector(
                context    = this,
                modelPath  = "model.tflite",
                classNames = config.classNames
            )
            detector.inicializar()

            runOnUiThread {
                if (detector.isReady) {
                    // Montar o resto do engine na thread principal
                    iouTracker   = SimpleIoUTracker()
                    rastreador   = Rastreador(config)
                    stateMachine = StateMachine(config, voz, rastreador)

                    frameAnalyzer = FrameAnalyzer(
                        config        = config,
                        detector      = detector,
                        iouTracker    = iouTracker,
                        tracker       = rastreador,
                        stateMachine  = stateMachine,
                        onStatusUpdate = { estado, situacao, nVeiculos, semCor ->
                            runOnUiThread {
                                atualizarUI(estado, situacao, nVeiculos, semCor)
                            }
                        },
                        onOverlayUpdate = { boxes, w, h, rot ->
                            runOnUiThread {
                                overlayView.updateDetections(boxes, w, h, rot)
                            }
                        }
                    )

                    tvInfo.text = "Pronto! Toque para iniciar."
                    btnToggle.isEnabled = true

                    // Iniciar câmera agora que tudo está pronto
                    if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
                        == PackageManager.PERMISSION_GRANTED) {
                        startCamera()
                    } else {
                        ActivityCompat.requestPermissions(
                            this,
                            arrayOf(Manifest.permission.CAMERA),
                            CAMERA_PERMISSION_CODE
                        )
                    }
                } else {
                    tvInfo.text = "ERRO ao carregar modelo!"
                    Log.e(TAG, "Falha ao inicializar detector")
                }
            }
        }.start()
    }

    // ================================================================
    //  CÂMERA
    // ================================================================

    private fun startCamera() {
        val cameraProviderFuture = ProcessCameraProvider.getInstance(this)
        cameraProviderFuture.addListener({
            val provider = cameraProviderFuture.get()

            val preview = Preview.Builder().build().also {
                it.setSurfaceProvider(previewView.surfaceProvider)
            }

            // Resolução reduzida para melhor performance no S21 FE
            val analysis = ImageAnalysis.Builder()
                .setTargetResolution(Size(480, 640))
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .build()

            analysis.setAnalyzer(cameraExecutor, frameAnalyzer)

            try {
                provider.unbindAll()
                provider.bindToLifecycle(
                    this,
                    CameraSelector.DEFAULT_BACK_CAMERA,
                    preview,
                    analysis
                )
                Log.i(TAG, "Camera iniciada")
            } catch (e: Exception) {
                Log.e(TAG, "Erro ao iniciar camera: ${e.message}")
                tvInfo.text = "Erro na câmera: ${e.message}"
            }
        }, ContextCompat.getMainExecutor(this))
    }

    // ================================================================
    //  CONTROLE
    // ================================================================

    private fun toggleAnalysis() {
        isActive = !isActive

        if (isActive) {
            // Iniciar análise
            stateMachine.entrarEstado(EST_RECONHECENDO)
            voz.forcar("inicio", "Iniciando análise. Analisando a via...")
            btnToggle.text = "PARAR"
            tvInfo.text = "Analisando..."
            overlayView.clear()
            Log.i(TAG, "Análise iniciada")
        } else {
            // Parar análise
            stateMachine.entrarEstado(EST_INATIVO)
            voz.forcar("cancelado", "Análise encerrada.")
            btnToggle.text = "INICIAR"
            tvInfo.text = "Pausado."
            tvEstado.text = "INATIVO"
            tvSituacao.text = "---"
            tvDetectionCount.text = ""
            overlayView.clear()
            Log.i(TAG, "Análise parada")
        }
    }

    // ================================================================
    //  UI
    // ================================================================

    private fun atualizarUI(estado: String, situacao: String, nVeiculos: Int, semCor: String) {
        tvEstado.text = estado

        // Cor do estado
        tvEstado.setTextColor(when (situacao) {
            "SEGURO"     -> 0xFF44DD44.toInt()
            "AGUARDE"    -> 0xFFFF4444.toInt()
            "VERIFICANDO"-> 0xFFFFAA00.toInt()
            else         -> 0xFFFFFFFF.toInt()
        })

        tvSituacao.text = situacao
        tvSituacao.setTextColor(when (situacao) {
            "SEGURO"      -> 0xFF44DD44.toInt()
            "AGUARDE"     -> 0xFFFF4444.toInt()
            "VERIFICANDO" -> 0xFFFFAA00.toInt()
            else          -> 0xFF888888.toInt()
        })

        // Info resumida
        val semInfo = if (semCor != "NENHUM") " | Semáforo: $semCor" else ""
        tvDetectionCount.text = "Veículos: $nVeiculos$semInfo"

        // FPS
        frameCount++
        val agora = System.currentTimeMillis()
        if (agora - lastFpsTime >= 1000L) {
            tvFps.text = "$frameCount FPS"
            frameCount = 0
            lastFpsTime = agora
        }
    }

    // ================================================================
    //  PERMISSÕES
    // ================================================================

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == CAMERA_PERMISSION_CODE) {
            if (grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                startCamera()
            } else {
                Toast.makeText(this, "Permissão de câmera necessária!", Toast.LENGTH_LONG).show()
                tvInfo.text = "Sem permissão de câmera."
            }
        }
    }

    // ================================================================
    //  LIFECYCLE
    // ================================================================

    override fun onDestroy() {
        super.onDestroy()
        isActive = false
        cameraExecutor.shutdown()
        voz.destruir()
        if (::detector.isInitialized) detector.fechar()
    }
}
