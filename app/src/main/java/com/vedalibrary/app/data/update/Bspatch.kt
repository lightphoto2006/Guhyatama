package com.vedalibrary.app.data.update

/**
 * Чистый Kotlin-применитель bsdiff4-патчей (BSDIFF40) — автообновление APK
 * как в Play Market: патч применяется к УЖЕ УСТАНОВЛЕННОМУ APK
 * (applicationInfo.sourceDir) и воспроизводит новый подписанный APK
 * байт-в-байт. Приватный ключ подписи клиенту не нужен — подпись нового APK
 * целиком внутри воспроизведённых байтов new.
 *
 * ВАЖНО про формат (реализация сверена с bsdiff4/core.c — эталонным patch
 * BSDIFF40; в исходном ТЗ описание троек было перепутано):
 *  - int64 little-endian, но НЕ дополнительный код: величина в байтах 0..6,
 *    знак — бит 0x80 седьмого байта; для неотрицательных < 2^56 совпадает
 *    с обычным LE;
 *  - заголовок: magic "BSDIFF40" (0..7), ctrl_len (8..15), diff_len (16..23),
 *    newsize (24..31); далее ctrl-блок, diff-блок, extra (остаток до EOF).
 *    Серверная тулза tools/dbcomposer/make_apk_delta.py пишет блоки В
 *    ОТКРЫТОМ виде (на Android нет bzip2), т.е. длины в заголовке — длины
 *    несжатых блоков;
 *  - ctrl — тройки int64 (x, y, z), oldpos — курсор old, newpos — new,
 *    d/e — курсоры diff/extra блоков:
 *    1) x байт: new[newpos+j] = diff[d+j] + old[oldpos+j] (байтовая
 *       арифметика mod 256; если oldpos+j вне old — байт diff берётся как есть),
 *       newpos += x, oldpos += x, d += x;
 *    2) y байт: new[newpos+j] = extra[e+j] (копия ИМЕННО из extra-блока,
 *       а не из old), newpos += y, e += y;
 *    3) z — знаковый переход oldpos += z (в ТЗ он значился как длина extra;
 *       на самом деле extra читается шагом y).
 *  Финал (как в bsdiff4): newpos == newsize, и оба блока diff/extra израсходованы
 *  ровно до байта; иначе патч битый.
 *
 * new воспроизводится байт-в-байт. Битый патч — IllegalArgumentException("битый патч"):
 * magic, отрицательные/выходящие за границы значения, неполный ctrl, перерасход
 * блоков. Из аллокаций — только выходной массив newsize; diff/extra читаем из patch.
 */
object Bspatch {

    private val MAGIC = "BSDIFF40".toByteArray(Charsets.US_ASCII)

    private fun bad(): Nothing = throw IllegalArgumentException("битый патч")

    /** int64 BSDIFF40: little-endian величина байтов 0..6, знак — бит 0x80 байта 7
     *  (encode_int64/decode_int64 из bsdiff4/core.c). Границы проверяет вызывающий. */
    private fun decodeInt64(b: ByteArray, off: Int): Long {
        var x = b[off + 7].toLong() and 0x7F
        for (i in 6 downTo 0) x = (x shl 8) or (b[off + i].toLong() and 0xFF)
        return if (b[off + 7].toInt() and 0x80 != 0) -x else x
    }

    /** Применяет patch (BSDIFF40, несжатые блоки) к old → new.
     *  new воспроизводится байт-в-байт; при любом повреждении — "битый патч". */
    fun apply(old: ByteArray, patch: ByteArray): ByteArray {
        if (patch.size < 32) bad()
        for (k in MAGIC.indices) if (patch[k] != MAGIC[k]) bad()
        val ctrlLen = decodeInt64(patch, 8)
        val diffLen = decodeInt64(patch, 16)
        val newsize = decodeInt64(patch, 24)
        if (ctrlLen < 0 || diffLen < 0 || newsize < 0) bad()
        if (newsize > Int.MAX_VALUE) bad()
        val ctrlStart = 32L
        val ctrlEnd = ctrlStart + ctrlLen
        val diffEnd = ctrlEnd + diffLen
        if (ctrlEnd > patch.size || diffEnd > patch.size) bad()
        if (ctrlLen % 24 != 0L) bad()
        val new = ByteArray(newsize.toInt())
        var oldpos = 0L
        var newpos = 0L
        var d = ctrlEnd      // diff-блок сразу за ctrl (в открытом виде, без bzip2)
        var e = diffEnd      // extra-блок — остаток до конца файла
        var c = ctrlStart    // ctrl-курсор (тройки int64)
        while (c + 24 <= ctrlEnd) {
            val x = decodeInt64(patch, c.toInt())
            val y = decodeInt64(patch, (c + 8).toInt())
            val z = decodeInt64(patch, (c + 16).toInt())
            c += 24
            if (x < 0 || y < 0) bad()
            if (x != 0L) {
                if (newpos + x > newsize || d + x > diffEnd) bad()
                val pi = newpos.toInt()
                val di = d.toInt()
                for (j in 0 until x.toInt()) {
                    var v = patch[di + j].toInt()
                    val oi = oldpos + j
                    if (oi >= 0 && oi < old.size) v += old[oi.toInt()]
                    new[pi + j] = v.toByte()
                }
            }
            newpos += x
            oldpos += x
            d += x
            if (y != 0L) {
                if (newpos + y > newsize || e + y > patch.size) bad()
                val pi = newpos.toInt()
                val ei = e.toInt()
                val yi = y.toInt()
                for (j in 0 until yi) new[pi + j] = patch[ei + j]
            }
            newpos += y
            e += y
            oldpos += z
        }
        // ровно как bsdiff4: new собран до байта, оба блока израсходованы до конца
        if (newpos != newsize || d != diffEnd || e != patch.size.toLong()) bad()
        return new
    }
}
