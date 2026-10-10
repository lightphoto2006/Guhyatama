package com.vedalibrary.app.data.update

import org.json.JSONObject

/** Адрес каталога обновлений. Лежит в публичном репозитории (только APK + каталог,
 *  текстов книг там нет): поменять на свой после создания репозитория. */
const val CATALOG_URL =
    "https://raw.githubusercontent.com/lightphoto2006/Guhyatama/main/catalog.json"

/** Описание APK из каталога. books/audio допишутся позже тем же стилем.
 *  Токен приватных файлов — local.properties → BuildConfig.GITHUB_FILES_TOKEN (не в исходниках). */
data class ApkInfo(
    val versionCode: Long,
    val versionName: String,
    val url: String,
    val size: Long,
    val sha256: String,
    val notes: String,
    /** Дельта APK (bsdiff) для обновляющихся: from = versionCode, с которого
     *  патч применим; пустой deltaUrl = дельты нет, качаем полный APK */
    val deltaFrom: Long = -1,
    val deltaUrl: String = "",
    val deltaSize: Long = 0,
    val deltaSha: String = ""
)

/** Разбор секции "apk" каталога. Пустой url = секции нет. Без новых зависимостей (org.json встроен). */
fun parseApkInfo(root: JSONObject): ApkInfo? {
    return try {
        val o = root.optJSONObject("apk") ?: return null
        val url = o.optString("url", "").trim()
        if (url.isBlank()) return null
        ApkInfo(
            versionCode = o.optLong("versionCode", 0),
            versionName = o.optString("versionName", "?"),
            url = url,
            size = o.optLong("size", 0),
            sha256 = o.optString("sha256", "").trim().lowercase(),
            notes = o.optString("notes", "").trim(),
            deltaFrom = o.optLong("deltaFrom", -1),
            deltaUrl = o.optString("deltaUrl", "").trim(),
            deltaSize = o.optLong("deltaSize", 0),
            deltaSha = o.optString("deltaSha", "").trim().lowercase()
        )
    } catch (_: Exception) { null }
}

/** Одна книга файла в отпечатке: тип, _id в исходнике, число стихов без галерей (v)
 *  и со строками-галереями (vg — старые импорты тащили их, миграция v9 сносила) */
data class FpRow(val t: String, val g: Long, val v: Int, val vg: Int = -1)

/** Файл книг из каталога: key стабилен (имя файла-источника), version растёт с каждым выпуском.
 *  auth="github" — качать с Authorization: Bearer BuildConfig.GITHUB_FILES_TOKEN (приватные релизы).
 *  fp — отпечаток содержимого для усыновления уже установленных (ставили вручную). */
data class BookInfo(
    val key: String,
    val title: String,
    val lang: String,
    val version: Int,
    val url: String,
    val size: Long,
    val sha256: String,
    val notes: String,
    val auth: String = "",
    val fp: List<FpRow> = emptyList(),
    /** false = не усыновлять (текстовые правки при том же числе стихов) */
    val adopt: Boolean = true,
    /** Дельта для обновляющихся (полный файл — только новичкам):
     *  from = версия, с которой применяется; пустой url = дельты нет */
    val deltaFrom: Int = -1,
    val deltaUrl: String = "",
    val deltaSize: Long = 0,
    val deltaSha: String = ""
)

/** Разбор секции "books"/"audio" каталога (кривые записи пропускаем молча) */
fun parseBookInfos(root: JSONObject, section: String = "books"): List<BookInfo> {
    return try {
        val arr = root.optJSONArray(section) ?: return emptyList()
        List(arr.length()) { i -> arr.optJSONObject(i) }.mapNotNull { o ->
            if (o == null) return@mapNotNull null
            val key = o.optString("key", "").trim()
            val url = o.optString("url", "").trim()
            if (key.isBlank() || url.isBlank()) return@mapNotNull null
            BookInfo(
                key = key,
                title = o.optString("title", key).trim(),
                lang = o.optString("lang", "rus").trim().takeIf { it == "eng" } ?: "rus",
                version = o.optInt("version", 0).coerceAtLeast(0),
                url = url,
                size = o.optLong("size", 0),
                sha256 = o.optString("sha256", "").trim().lowercase(),
                notes = o.optString("notes", "").trim(),
                auth = o.optString("auth", "").trim().lowercase(),
                adopt = !o.has("adopt") || o.optBoolean("adopt", true),
                deltaFrom = o.optInt("deltaFrom", -1),
                deltaUrl = o.optString("deltaUrl", "").trim(),
                deltaSize = o.optLong("deltaSize", 0),
                deltaSha = o.optString("deltaSha", "").trim().lowercase(),
                fp = try {
                    val arr = o.optJSONArray("fp") ?: org.json.JSONArray()
                    List(arr.length()) { i ->
                        val f = arr.optJSONObject(i) ?: org.json.JSONObject()
                        FpRow(f.optString("t", ""), f.optLong("g", -1),
                            f.optInt("v", -1), f.optInt("vg", -1))
                    }.filter { it.t.isNotBlank() && it.g >= 0 && it.v >= 0 }
                } catch (_: Exception) { emptyList() }
            )
        }
    } catch (_: Exception) { emptyList() }
}
