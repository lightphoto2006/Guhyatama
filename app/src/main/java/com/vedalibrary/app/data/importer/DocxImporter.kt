package com.vedalibrary.app.data.importer

import android.content.Context
import android.net.Uri
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.xmlpull.v1.XmlPullParserFactory
import java.util.zip.ZipInputStream
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Импорт .docx без тяжёлых библиотек: docx это zip, текст в word/document.xml.
 * Заголовки Word (Heading 1/2) -> "## ..." понимает ChapterSplitter.
 * Старый .doc (бинарный) не поддерживается — подсказываем сохранить как .docx.
 */
@Singleton
class DocxImporter @Inject constructor(
    @ApplicationContext private val ctx: Context,
    private val txtImporter: TxtImporter
) {
    suspend fun import(uri: Uri, titleHint: String? = null): String = withContext(Dispatchers.IO) {
        val name = titleHint ?: "Импорт DOCX"
        ctx.contentResolver.openInputStream(uri)!!.use { inp ->
            val xml = extractDocumentXml(inp.readBytes())
                ?: error("В файле нет word/document.xml — это не .docx (старый .doc сохраните как .docx)")
            importXml(xml, name)
        }
    }

    private fun extractDocumentXml(zip: ByteArray): ByteArray? {
        ZipInputStream(zip.inputStream()).use { zin ->
            var e = zin.nextEntry
            while (e != null) {
                if (e.name == "word/document.xml") return zin.readBytes()
                zin.closeEntry()
                e = zin.nextEntry
            }
        }
        return null
    }

    private suspend fun importXml(xml: ByteArray, title: String): String {
        val out = StringBuilder(xml.size / 4)
        val f = XmlPullParserFactory.newInstance().apply { isNamespaceAware = false }
        val p = f.newPullParser().apply { setInput(xml.inputStream(), "UTF-8") }
        var para = StringBuilder()
        var heading = false
        fun flushPara() {
            val t = para.toString().trim()
            if (t.isNotEmpty()) {
                if (heading) out.append("\n\n## ").append(t).append('\n')
                else out.append(t).append('\n')
            }
            para = StringBuilder()
            heading = false
        }
        var ev = p.eventType
        while (ev != org.xmlpull.v1.XmlPullParser.END_DOCUMENT) {
            when (ev) {
                org.xmlpull.v1.XmlPullParser.START_TAG -> when (p.name) {
                    "w:p" -> flushPara()
                    "w:pStyle" -> {
                        val v = p.getAttributeValue(null, "w:val") ?: ""
                        if (v.startsWith("Heading", true)) heading = true
                    }
                    "w:t" -> para.append(p.nextText())
                    "w:tab" -> para.append(' ')
                    "w:br", "w:cr" -> para.append('\n')
                }
                org.xmlpull.v1.XmlPullParser.END_TAG -> if (p.name == "w:p") flushPara()
            }
            ev = p.next()
        }
        flushPara()
        val text = out.toString().trim()
        if (text.isEmpty()) error("DOCX пустой — нет текстовых параграфов")
        return txtImporter.importText(text, title)
    }
}
