package com.vedalibrary.app.data.update

import android.content.Context
import javax.net.ssl.SSLSocketFactory
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManagerFactory
import java.security.KeyStore

/**
 * Строит SSLSocketFactory, который доверяет системным CA + дополнительный корневой сертификат.
 * Кэширует результат для избежания повторного построения KeyStore.
 */
object ExtraTrust {

    @Volatile
    private var cached: SSLSocketFactory? = null

    fun socketFactory(ctx: Context): SSLSocketFactory {
        cached?.let { return it }
        synchronized(this) {
            cached?.let { return it }

            val ks = KeyStore.getInstance(KeyStore.getDefaultType()).apply {
                load(null, null)
            }

            // Копируем системные CA (AndroidCAStore)
            val sys = KeyStore.getInstance("AndroidCAStore").apply {
                load(null, null)
            }
            val aliases = sys.aliases()
            while (aliases.hasMoreElements()) {
                val alias = aliases.nextElement()
                try {
                    ks.setCertificateEntry(alias, sys.getCertificate(alias))
                } catch (_: Exception) {
                    // пропускаем проблемные записи
                }
            }

            // Добавляем дополнительный корневой сертификат (ISRG Root X1)
            val cf = java.security.cert.CertificateFactory.getInstance("X.509")
            ctx.resources.openRawResource(com.vedalibrary.app.R.raw.isrg_root_x1).use { ins ->
                ks.setCertificateEntry("isrg_root_x1", cf.generateCertificate(ins))
            }

            val tmf = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm())
            tmf.init(ks)

            val ssl = SSLContext.getInstance("TLS")
            ssl.init(null, tmf.trustManagers, null)
            cached = ssl.socketFactory
            return ssl.socketFactory
        }
    }
}
