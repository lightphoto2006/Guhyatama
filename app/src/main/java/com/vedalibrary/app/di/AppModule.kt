package com.vedalibrary.app.di

import android.content.Context
import androidx.room.Room
import com.vedalibrary.app.data.local.AppDatabase
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module @InstallIn(SingletonComponent::class)
object AppModule {
    @Provides @Singleton
    fun db(@ApplicationContext c: Context): AppDatabase =
        Room.databaseBuilder(c, AppDatabase::class.java, "vedalibrary.db")
            .addMigrations(AppDatabase.MIGRATION_3_4, AppDatabase.MIGRATION_4_5, AppDatabase.MIGRATION_5_6, AppDatabase.MIGRATION_6_7, AppDatabase.MIGRATION_7_8, AppDatabase.MIGRATION_8_9, AppDatabase.MIGRATION_9_10)
            // Даунгрейд APK (старая версия поверх новой): без этого Room крашится
            // «migration X→Y not found» и приложение не стартует, пока не сотрут данные
            .fallbackToDestructiveMigrationOnDowngrade()
            // Страховка на время, пока нет миграций 1→2/2→3 (exportSchema включён —
            // с этого момента схемы пишутся в app/schemas/ и миграции проверяются)
            .fallbackToDestructiveMigration()
            .build()
}
