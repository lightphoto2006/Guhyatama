package com.vedalibrary.app.data.importer

import android.content.Context
import android.net.Uri
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Импорт PDF: текст извлекаем через pdfbox-android (две колонки чинятся sortByPosition).
 * PdfRenderer текста не даёт — только fallback-подсчёт страниц, здесь не нужен.
 */
@Singleton
class PdfImporter @Inject constructor(
    @ApplicationContext private val ctx: Context,
    private val txtImporter: TxtImporter
) {
    suspend fun import(uri: Uri, titleHint: String? = null): String =
        withContext(Dispatchers.IO) {
            // Копируем в кэш (нужен seekable файл)
            val tmp = File.createTempFile("import", ".pdf", ctx.cacheDir)
            try {
                ctx.contentResolver.openInputStream(uri)!!.use { inp -> tmp.outputStream().use { inp.copyTo(it) } }
                val text = try {
                    extractWithPdfBox(tmp)
                } catch (_: Throwable) {
                    ""
                }
                val title = titleHint ?: tmp.nameWithoutExtension.ifBlank { "Импорт PDF" }
                txtImporter.importText(text.ifBlank { "Пустой PDF — возможно это скан. Нужен OCR." }, title)
            } finally {
                tmp.delete()
            }
        }

    private fun extractWithPdfBox(file: File): String {
        // tom-roush pdfbox-android (пакет com.tom_roush, не org.apache)
        com.tom_roush.pdfbox.pdmodel.PDDocument.load(file).use { doc ->
            val stripper = com.tom_roush.pdfbox.text.PDFTextStripper()
            stripper.sortByPosition = true // чинит две колонки в большинстве лекций
            return stripper.getText(doc)
        }
    }
}
