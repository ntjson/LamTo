import 'package:flutter/material.dart';

/// DESIGN.md light tokens. Accountability Indigo is primary (≤10% of a screen).
class LamToColors {
  static const primary = Color(0xFF2F3A8F);
  static const onPrimary = Color(0xFFFFFFFF);
  static const bg = Color(0xFFF6F7FB);
  static const surface = Color(0xFFFFFFFF);
  static const ink = Color(0xFF1C2434);
  static const muted = Color(0xFF5B6577);
  static const border = Color(0xFFD7DCE8);
  static const success = Color(0xFF0F7A45);
  static const warning = Color(0xFF9A6700);
  static const error = Color(0xFFB42318);
  static const info = Color(0xFF175CD3);
}

/// Complete dark-theme tokens (clarification #6).
class LamToColorsDark {
  static const bg = Color(0xFF12141C);
  static const surface = Color(0xFF1C2030);
  static const ink = Color(0xFFE8EAF2);
  static const muted = Color(0xFFA0A8B8);
  static const border = Color(0xFF3A4158);
  static const onPrimary = Color(0xFFFFFFFF);
}

/// Money / VND text style with real tabular figures (DESIGN.md).
TextStyle moneyTextStyle(TextTheme base, {Color? color}) {
  return (base.titleMedium ?? const TextStyle()).copyWith(
    fontFeatures: const [FontFeature.tabularFigures()],
    color: color,
    fontWeight: FontWeight.w600,
  );
}

ThemeData lamToTheme(Brightness brightness) {
  final isDark = brightness == Brightness.dark;
  final surface = isDark ? LamToColorsDark.surface : LamToColors.surface;
  final bg = isDark ? LamToColorsDark.bg : LamToColors.bg;
  final onSurface = isDark ? LamToColorsDark.ink : LamToColors.ink;
  final outline = isDark ? LamToColorsDark.border : LamToColors.border;
  final scheme = ColorScheme.fromSeed(
    seedColor: LamToColors.primary,
    brightness: brightness,
    primary: LamToColors.primary,
    onPrimary: LamToColors.onPrimary,
    error: LamToColors.error,
    surface: surface,
    onSurface: onSurface,
    outline: outline,
  );
  final baseText = Typography.material2021(platform: TargetPlatform.android)
      .black
      .apply(
        bodyColor: onSurface,
        displayColor: onSurface,
        fontFamilyFallback: const ['Roboto'],
      );
  final textTheme = baseText.copyWith(
    titleMedium: moneyTextStyle(baseText, color: onSurface),
  );
  return ThemeData(
    useMaterial3: true,
    brightness: brightness,
    colorScheme: scheme,
    scaffoldBackgroundColor: bg,
    textTheme: textTheme,
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(48)),
    ),
    inputDecorationTheme: InputDecorationTheme(
      border: const OutlineInputBorder(),
      filled: true,
      fillColor: surface,
    ),
  );
}
