package com.travessia.segura.ui

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Matrix
import android.os.Bundle
import android.util.Log
import android.view.WindowManager
import android.widget.Button
import android.widget.ImageView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.travessia.segura.R
import com.travessia.segura.camera.EspCameraClient
import com.travessia.segura.camera.EspFrameProcessor
import com.travessia.segura.camera.FrameAnalyzer
import com.travessia.segura.config.AppConfig
import com.travessia.segura.config.LanguageManager
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
import android.view.View
import kotlinx.coroutines.*
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

class MainActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "MainActivity"
        private const val CAMERA_PERMISSION_CODE = 100

        // Modos de câmera
        const val MODE_LOCAL_CAMERA = 0
        const val MODE_ESP32_CAMERA = 1
    }

    // UI
    private lateinit var previewView: PreviewView
    private lateinit var overlayView: OverlayView
    private lateinit var tvEstado: TextView
    private lateinit var tvSituacao: TextView
    private lateinit var tvInfo: TextView
    private lateinit var tvDetectionCount: TextView
    private lateinit var tvFps: TextView
    private lateinit var tvAlertStatus: TextView
    private lateinit var tvScreenTitle: TextView
    private lateinit var btnToggle: Button
    private lateinit var btnConfig: Button
    private lateinit var btnSource: Button
    private lateinit var statusBar: View
    private lateinit var bottomPanel: View

    // ImageView para exibir frames do ESP32 (alternativa ao PreviewView)
    private var espImageView: ImageView? = null

    // Engine
    private lateinit var config: AppConfig
    private lateinit var voz: VoiceSystem
    private lateinit var detector: YoloDetector
    private lateinit var iouTracker: SimpleIoUTracker
    private lateinit var rastreador: Rastreador
    private lateinit var stateMachine: StateMachine
    private lateinit var cameraExecutor: ExecutorService

    // CameraX (modo local)
    private var frameAnalyzer: FrameAnalyzer? = null

    // ESP32 (modo externo)
    private var espClient: EspCameraClient? = null
    private var espProcessor: EspFrameProcessor? = null
    private var processingScope: CoroutineScope? = null

    // Estado
    private var isActive = false
    private var cameraMode = MODE_ESP32_CAMERA // Padrão: ESP32

    // FPS
    private var frameCount = 0
    private var lastFpsTime = System.currentTimeMillis()

    private fun tr(key: String): String = LanguageManager.text(this, key)

    private fun estadoExibido(estado: String): String {
        return when (estado) {
            EST_INATIVO -> tr("state_inactive")
            EST_RECONHECENDO -> tr("state_recognizing")
            AppConfig.EST_SEMAFORO -> tr("state_traffic_light")
            AppConfig.EST_FAIXA -> tr("state_crosswalk")
            AppConfig.EST_VIA_LIVRE -> tr("state_clear_road")
            else -> estado
        }
    }

    private fun situacaoExibida(situacao: String): String {
        return when (situacao) {
            "SEGURO" -> tr("situation_safe")
            "AGUARDE" -> tr("situation_wait")
            "VERIFICANDO" -> tr("situation_checking")
            else -> situacao
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContentView(R.layout.activity_main)

        config = AppConfig(this)
        initViews()
        initEngine()
    }

    private fun initViews() {
        previewView = findViewById(R.id.previewView)
        overlayView = findViewById(R.id.overlayView)
        tvEstado = findViewById(R.id.tvEstado)
        tvSituacao = findViewById(R.id.tvSituacao)
        tvInfo = findViewById(R.id.tvInfo)
        tvDetectionCount = findViewById(R.id.tvDetectionCount)
        tvFps = findViewById(R.id.tvFps)
        tvAlertStatus = findViewById(R.id.tvAlertStatus)
        tvScreenTitle = findViewById(R.id.tvScreenTitle)
        btnToggle = findViewById(R.id.btnToggle)
        btnConfig = findViewById(R.id.btnConfig)
        btnSource = findViewById(R.id.btnSource)
        statusBar = findViewById(R.id.statusBar)
        bottomPanel = findViewById(R.id.bottomPanel)

        // ImageView para ESP32 frames (adicionada programaticamente ou via layout)
        espImageView = findViewById(R.id.espImageView)

        btnToggle.isEnabled = false
        btnToggle.setOnClickListener { toggleAnalysis() }
        btnConfig.setOnClickListener {
            startActivity(Intent(this, SettingsActivity::class.java))
        }
        btnSource.setOnClickListener { alternarFonte() }

        aplicarTextoBase()
        atualizarUIFonte()
        aplicarPreferenciasVisuais()
        tvInfo.text = tr("loading_model")
    }

    private fun initEngine() {
        cameraExecutor = Executors.newSingleThreadExecutor()
        voz = VoiceSystem(this, config)

        Thread {
            detector = YoloDetector(
                context = this,
                modelPath = "model.tflite",
                classNames = config.classNames
            )
            detector.inicializar()

            runOnUiThread {
                if (detector.isReady) {
                    iouTracker = SimpleIoUTracker()
                    rastreador = Rastreador(config)
                    stateMachine = StateMachine(config, voz, rastreador)

                    // Preparar processador para ESP32
                    espProcessor = EspFrameProcessor(
                        config = config,
                        detector = detector,
                        iouTracker = iouTracker,
                        tracker = rastreador,
                        stateMachine = stateMachine,
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

                    // Preparar FrameAnalyzer para câmera local
                    frameAnalyzer = FrameAnalyzer(
                        config = config,
                        detector = detector,
                        iouTracker = iouTracker,
                        tracker = rastreador,
                        stateMachine = stateMachine,
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

                    tvInfo.text = tr("ready_wifi")
                    btnToggle.isEnabled = true

                    configurarFonte()

                } else {
                    tvInfo.text = tr("model_error")
                    Log.e(TAG, "Falha ao inicializar detector")
                }
            }
        }.start()
    }

    // ================================================================
    //  FONTE DE VÍDEO
    // ================================================================

    private fun alternarFonte() {
        if (isActive) {
            Toast.makeText(this, tr("stop_before_source"), Toast.LENGTH_SHORT).show()
            return
        }

        cameraMode = if (cameraMode == MODE_LOCAL_CAMERA) MODE_ESP32_CAMERA else MODE_LOCAL_CAMERA
        atualizarUIFonte()
        configurarFonte()
    }

    private fun atualizarUIFonte() {
        when (cameraMode) {
            MODE_ESP32_CAMERA -> {
                btnSource.text = "ESP32"
                previewView.visibility = View.GONE
                espImageView?.visibility = View.VISIBLE
            }
            MODE_LOCAL_CAMERA -> {
                btnSource.text = tr("source_local")
                previewView.visibility = View.VISIBLE
                espImageView?.visibility = View.GONE
            }
        }
    }

    private fun configurarFonte() {
        aplicarPreferenciasVisuais()
        when (cameraMode) {
            MODE_ESP32_CAMERA -> configurarEsp32()
            MODE_LOCAL_CAMERA -> configurarCameraLocal()
        }
    }

    // ================================================================
    //  APARÊNCIA / HUD
    // ================================================================

    private fun aplicarPreferenciasVisuais() {
        if (!::config.isInitialized) return

        espImageView?.scaleType = if (config.espPreviewTelaCheia) {
            ImageView.ScaleType.CENTER_CROP
        } else {
            ImageView.ScaleType.FIT_CENTER
        }

        overlayView.visibility = if (config.mostrarOverlay) View.VISIBLE else View.GONE
        statusBar.visibility = if (config.mostrarPainelSuperior) View.VISIBLE else View.GONE
        bottomPanel.visibility = if (config.mostrarPainelInferior) View.VISIBLE else View.GONE
    }


    private fun aplicarTextoBase() {
        tvScreenTitle.text = tr("screen_title")
        btnConfig.text = tr("config_short")
        btnToggle.text = if (isActive) tr("stop") else tr("start")

        if (!isActive) {
            tvAlertStatus.text = tr("waiting_camera")
            tvEstado.text = tr("state_inactive")
            tvSituacao.text = "---"
            tvDetectionCount.text = "${tr("vehicles")}: 0"
        }
    }

    private fun prepararBitmapPreview(bitmap: Bitmap): Bitmap {
        val rotation = config.espPreviewRotation
        if (rotation == 0) return bitmap

        val matrix = Matrix().apply {
            postRotate(rotation.toFloat())
        }

        return Bitmap.createBitmap(
            bitmap,
            0,
            0,
            bitmap.width,
            bitmap.height,
            matrix,
            true
        )
    }

    override fun onResume() {
        super.onResume()
        if (::config.isInitialized) {
            aplicarTextoBase()
            atualizarUIFonte()
            aplicarPreferenciasVisuais()
        }
    }

    // ================================================================
    //  ESP32 CAMERA
    // ================================================================

    private fun configurarEsp32() {
        // Parar câmera local se estiver rodando
        pararCameraLocal()

        tvInfo.text = tr("esp_connect_info")

        espClient = EspCameraClient(
            baseUrl = "http://192.168.4.1",
            frameEndpoint = "/frame", // Ajuste conforme seu firmware do ESP32
            onFrame = { bitmap ->
                // Aparência do preview: tela cheia/rotação visual.
                // A IA continua processando o bitmap original para não mudar a lógica.
                val previewBitmap = prepararBitmapPreview(bitmap)
                espImageView?.scaleType = if (config.espPreviewTelaCheia) {
                    ImageView.ScaleType.CENTER_CROP
                } else {
                    ImageView.ScaleType.FIT_CENTER
                }
                espImageView?.setImageBitmap(previewBitmap)

                // Processar apenas se análise estiver ativa
                if (isActive) {
                    processingScope?.launch(Dispatchers.Default) {
                        espProcessor?.processarFrame(bitmap)
                    }
                }
            },
            onError = { msg ->
                tvInfo.text = "ESP32: $msg\n${tr("esp_error_suffix")}"
                tvAlertStatus.text = tr("esp_waiting")
            },
            onFpsUpdate = { fps ->
                tvFps.text = "$fps FPS"
            }
        )
    }

    private fun iniciarEsp32() {
        processingScope = CoroutineScope(Dispatchers.Default + SupervisorJob())

        // Testar conexão antes
        processingScope?.launch {
            val conectado = espClient?.testarConexao() ?: false
            withContext(Dispatchers.Main) {
                if (conectado) {
                    tvInfo.text = tr("esp_connected")
                    espClient?.iniciar()
                } else {
                    tvInfo.text = tr("esp_connection_failed")
                    tvAlertStatus.text = tr("esp_no_signal")
                    this@MainActivity.isActive = false
                    btnToggle.text = tr("start")
                    stateMachine.entrarEstado(EST_INATIVO)
                }
            }
        }
    }

    private fun pararEsp32() {
        espClient?.parar()
        processingScope?.cancel()
        processingScope = null
    }

    // ================================================================
    //  CÂMERA LOCAL (CameraX original)
    // ================================================================

    private fun configurarCameraLocal() {
        pararEsp32()

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
            == PackageManager.PERMISSION_GRANTED
        ) {
            startCamera()
        } else {
            ActivityCompat.requestPermissions(
                this,
                arrayOf(Manifest.permission.CAMERA),
                CAMERA_PERMISSION_CODE
            )
        }
    }

    private fun pararCameraLocal() {
        try {
            val cameraProviderFuture = ProcessCameraProvider.getInstance(this)
            cameraProviderFuture.addListener({
                cameraProviderFuture.get().unbindAll()
            }, ContextCompat.getMainExecutor(this))
        } catch (e: Exception) {
            Log.w(TAG, "Erro ao parar câmera local: ${e.message}")
        }
    }

    private fun startCamera() {
        val cameraProviderFuture = ProcessCameraProvider.getInstance(this)
        cameraProviderFuture.addListener({
            val provider = cameraProviderFuture.get()

            val preview = Preview.Builder().build().also {
                it.setSurfaceProvider(previewView.surfaceProvider)
            }

            val analysis = ImageAnalysis.Builder()
                .setTargetResolution(Size(480, 640))
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .build()

            analysis.setAnalyzer(cameraExecutor, frameAnalyzer!!)

            try {
                provider.unbindAll()
                provider.bindToLifecycle(
                    this,
                    CameraSelector.DEFAULT_BACK_CAMERA,
                    preview,
                    analysis
                )
                Log.i(TAG, "Camera local iniciada")
            } catch (e: Exception) {
                Log.e(TAG, "Erro ao iniciar camera: ${e.message}")
                tvInfo.text = "${tr("camera_error")}: ${e.message}"
            }
        }, ContextCompat.getMainExecutor(this))
    }

    // ================================================================
    //  CONTROLE
    // ================================================================

    private fun toggleAnalysis() {
        isActive = !isActive

        if (isActive) {
            stateMachine.entrarEstado(EST_RECONHECENDO)
            voz.forcar("inicio", tr("analysis_start_voice"))
            btnToggle.text = tr("stop")
            tvAlertStatus.text = tr("analysis_running")
            overlayView.clear()

            when (cameraMode) {
                MODE_ESP32_CAMERA -> iniciarEsp32()
                MODE_LOCAL_CAMERA -> tvInfo.text = tr("analyzing")
            }

            Log.i(TAG, "Análise iniciada (modo: ${if (cameraMode == MODE_ESP32_CAMERA) "ESP32" else "Local"})")
        } else {
            stateMachine.entrarEstado(EST_INATIVO)
            voz.forcar("cancelado", tr("analysis_stop_voice"))
            btnToggle.text = tr("start")
            tvAlertStatus.text = tr("analysis_paused")
            tvInfo.text = tr("paused")
            tvEstado.text = tr("state_inactive")
            tvSituacao.text = "---"
            tvDetectionCount.text = "${tr("vehicles")}: 0"
            overlayView.clear()

            if (cameraMode == MODE_ESP32_CAMERA) {
                pararEsp32()
            }

            Log.i(TAG, "Análise parada")
        }
    }

    // ================================================================
    //  UI
    // ================================================================

    private fun atualizarUI(estado: String, situacao: String, nVeiculos: Int, semCor: String) {
        tvEstado.text = estadoExibido(estado)

        tvEstado.setTextColor(
            when (situacao) {
                "SEGURO" -> 0xFF44DD44.toInt()
                "AGUARDE" -> 0xFFFF4444.toInt()
                "VERIFICANDO" -> 0xFFFFAA00.toInt()
                else -> 0xFFFFFFFF.toInt()
            }
        )

        tvSituacao.text = situacaoExibida(situacao)
        tvSituacao.setTextColor(
            when (situacao) {
                "SEGURO" -> 0xFF44DD44.toInt()
                "AGUARDE" -> 0xFFFF4444.toInt()
                "VERIFICANDO" -> 0xFFFFAA00.toInt()
                else -> 0xFF888888.toInt()
            }
        )

        val semInfo = if (semCor != "NENHUM") " | ${tr("traffic_light")}: ${config.nomeCorSemaforo(semCor).replaceFirstChar { it.uppercase() }}" else ""
        tvDetectionCount.text = "${tr("vehicles")}: $nVeiculos$semInfo"
        tvAlertStatus.text = "${tr("current_situation")}: ${situacaoExibida(situacao)}"

        // FPS para câmera local
        if (cameraMode == MODE_LOCAL_CAMERA) {
            frameCount++
            val agora = System.currentTimeMillis()
            if (agora - lastFpsTime >= 1000L) {
                tvFps.text = "$frameCount FPS"
                frameCount = 0
                lastFpsTime = agora
            }
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
                Toast.makeText(this, tr("camera_permission_needed"), Toast.LENGTH_LONG).show()
                tvInfo.text = tr("no_camera_permission")
            }
        }
    }

    // ================================================================
    //  LIFECYCLE
    // ================================================================

    override fun onDestroy() {
        super.onDestroy()
        isActive = false
        pararEsp32()
        cameraExecutor.shutdown()
        voz.destruir()
        if (::detector.isInitialized) detector.fechar()
    }
}