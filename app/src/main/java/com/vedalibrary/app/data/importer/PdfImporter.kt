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
            // Инициализируем PDFBoxResourceLoader (нужен для pdfbox-android)
            try { com.tom_roush.pdfbox.android.PDFBoxResourceLoader.init(ctx) } catch (_: Throwable) { }

            // Копируем в кэш (нужен seekable файл)
            val tmp = File.createTempFile("import", ".pdf", ctx.cacheDir)
            try {
                val inp = ctx.contentResolver.openInputStream(uri) ?: throw IllegalStateException("Нет доступа к файлу")
                inp.use { tmp.outputStream().use { inp.copyTo(it) } }
                val text = try {
                    extractWithPdfBox(tmp)
                } catch (e: Throwable) {
                    throw IllegalStateException("Не удалось прочитать PDF (${e.javaClass.simpleName}: ${e.message ?: "?"})")
                }
                // Заменяем null-символы на пробелы; если текста < 10 букв — бросаем, а не ставим заглушку
                val cleaned = text.replace('\u0000', ' ')
                val letterCount = cleaned.count { it.isLetter() }
                if (letterCount < 10) {
                    throw IllegalStateException("В PDF не найден текстовый слой — это скан, нужен OCR")
                }
                val title = titleHint ?: tmp.nameWithoutExtension.ifBlank { "Импорт PDF" }
                txtImporter.importText(cleaned, title)
            } finally {
                tmp.delete()
            }
        }

    private fun extractWithPdfBox(file: File): String {
        com.tom_roush.pdfbox.pdmodel.PDDocument.load(file).use { doc ->
            val sb = StringBuilder()
            for (p in 0 until doc.numberOfPages) {
                try {
                    val stripper = com.tom_roush.pdfbox.text.PDFTextStripper()
                    stripper.sortByPosition = true
                    stripper.startPage = p + 1
                    stripper.endPage = p + 1
                    sb.append(stripper.getText(doc))
                } catch (_: Throwable) {
                    // битую страницу пропускаем
                }
            }
            return sb.toString()
        }
    }
}
