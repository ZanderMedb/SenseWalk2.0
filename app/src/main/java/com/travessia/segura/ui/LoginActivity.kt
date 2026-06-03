package com.travessia.segura.ui

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.travessia.segura.R
import com.travessia.segura.config.LanguageManager

class LoginActivity : AppCompatActivity() {

    private lateinit var tvTitle: TextView
    private lateinit var tvSubtitle: TextView
    private lateinit var tvLanguageLabel: TextView
    private lateinit var tvHint: TextView
    private lateinit var btnPortuguese: Button
    private lateinit var btnEnglish: Button
    private lateinit var btnSpanish: Button
    private lateinit var btnContinue: Button

    private var selectedLanguage: String = LanguageManager.PT

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_login)

        selectedLanguage = LanguageManager.currentLanguage(this)

        tvTitle = findViewById(R.id.tvLoginTitle)
        tvSubtitle = findViewById(R.id.tvLoginSubtitle)
        tvLanguageLabel = findViewById(R.id.tvLoginLanguageLabel)
        tvHint = findViewById(R.id.tvLoginHint)
        btnPortuguese = findViewById(R.id.btnPortuguese)
        btnEnglish = findViewById(R.id.btnEnglish)
        btnSpanish = findViewById(R.id.btnSpanish)
        btnContinue = findViewById(R.id.btnContinue)

        btnPortuguese.setOnClickListener { selectLanguage(LanguageManager.PT) }
        btnEnglish.setOnClickListener { selectLanguage(LanguageManager.EN) }
        btnSpanish.setOnClickListener { selectLanguage(LanguageManager.ES) }

        btnContinue.setOnClickListener {
            LanguageManager.setLanguage(this, selectedLanguage)
            startActivity(Intent(this, MainActivity::class.java))
            finish()
        }

        applyTexts()
        updateSelectedButton()
    }

    private fun selectLanguage(code: String) {
        selectedLanguage = code

        // Salva imediatamente o idioma escolhido
        LanguageManager.setLanguage(this, selectedLanguage)

        applyTexts()
        updateSelectedButton()
    }

    private fun applyTexts() {
        tvTitle.text = LanguageManager.text(selectedLanguage, "login_title")
        tvSubtitle.text = LanguageManager.text(selectedLanguage, "login_subtitle")
        tvLanguageLabel.text = LanguageManager.text(selectedLanguage, "login_language_label")
        tvHint.text = LanguageManager.text(selectedLanguage, "login_hint")
        btnContinue.text = LanguageManager.text(selectedLanguage, "login_continue")
        btnPortuguese.text = LanguageManager.text(selectedLanguage, "login_pt")
        btnEnglish.text = LanguageManager.text(selectedLanguage, "login_en")
        btnSpanish.text = LanguageManager.text(selectedLanguage, "login_es")
    }

    private fun updateSelectedButton() {
        btnPortuguese.setBackgroundResource(
            if (selectedLanguage == LanguageManager.PT) R.drawable.bg_button_primary else R.drawable.bg_button_secondary
        )
        btnEnglish.setBackgroundResource(
            if (selectedLanguage == LanguageManager.EN) R.drawable.bg_button_primary else R.drawable.bg_button_secondary
        )
        btnSpanish.setBackgroundResource(
            if (selectedLanguage == LanguageManager.ES) R.drawable.bg_button_primary else R.drawable.bg_button_secondary
        )
    }
}
