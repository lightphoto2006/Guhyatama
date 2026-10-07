# Keep app local data layer (Room entities/DAOs) — Room itself ships its own consumer rules
-keep class com.vedalibrary.app.data.local.** { *; }
-dontwarn org.apache.pdfbox.**

# Strip debug logging from release builds
-assumenosideeffects class android.util.Log {
    public static int v(...);
    public static int d(...);
    public static int i(...);
}
