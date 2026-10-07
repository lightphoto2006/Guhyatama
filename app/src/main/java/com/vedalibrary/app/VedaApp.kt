package com.vedalibrary.app

import android.app.Application
import dagger.hilt.android.HiltAndroidApp

/** Канал «Стих дня» (daily-verse) удалён: уведомления нигде не отправляются,
 *  вместе с каналом убрано разрешение POST_NOTIFICATIONS. */
@HiltAndroidApp
class VedaApp : Application()
