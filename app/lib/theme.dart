import 'package:flutter/cupertino.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

/// Light tokens. One interactive blue drawn from the brand navy, neutral
/// grouped surfaces, and four semantic tones that always travel with a word.
class LamToColors {
  /// The logo navy; brand moments only (avatar, marks), never an action.
  static const brand = Color(0xFF003081);

  /// Interactive tint: links, primary buttons, selection. 7.2:1 on white.
  static const primary = Color(0xFF0A4FC4);
  static const onPrimary = Color(0xFFFFFFFF);
  static const primarySoft = Color(0xFFE8EFFC);

  /// Grouped background (iOS systemGroupedBackground); content sits on
  /// white [surface] groups above it.
  static const bg = Color(0xFFF2F2F7);
  static const surface = Color(0xFFFFFFFF);

  /// Quiet fill for inputs, segmented tracks, and icon wells.
  static const fill = Color(0xFFEDEDF0);
  static const ink = Color(0xFF1D1D1F);

  /// Secondary copy: 5.1:1 on white, 4.7:1 on [bg].
  static const muted = Color(0xFF6E6E73);

  /// Hairlines between rows and around inputs.
  static const border = Color(0xFFE3E3E8);
  static const success = Color(0xFF1E7B34);
  static const successBg = Color(0xFFE8F5EC);
  static const warning = Color(0xFF9A4F00);
  static const warningBg = Color(0xFFFFF4E5);
  static const error = Color(0xFFC4271D);
  static const errorBg = Color(0xFFFDECEC);
  static const info = primary;
  static const infoBg = primarySoft;
}

/// Dark tokens (iOS grouped dark): black ground, lifted groups.
class LamToColorsDark {
  /// 6.1:1 on [surface]; filled-button labels flip to [onPrimary].
  static const primary = Color(0xFF5B9BFF);

  /// Near-black ink on the light blue (≈7.3:1). White fails AA there.
  static const onPrimary = Color(0xFF12141C);
  static const primarySoft = Color(0xFF172A4D);
  static const bg = Color(0xFF000000);
  static const surface = Color(0xFF1C1C1E);
  static const fill = Color(0xFF2C2C2E);
  static const ink = Color(0xFFF5F5F7);
  static const muted = Color(0xFFA1A1A6);
  static const border = Color(0xFF38383A);
  static const success = Color(0xFF5AD08A);
  static const successBg = Color(0xFF12301E);
  static const warning = Color(0xFFFFB340);
  static const warningBg = Color(0xFF33250D);
  static const error = Color(0xFFFF7A70);
  static const errorBg = Color(0xFF3A1614);
  static const info = primary;
  static const infoBg = primarySoft;
}

/// Brightness-resolved neutrals for widgets that paint their own surfaces.
class LamToPalette {
  const LamToPalette._(this._dark);

  factory LamToPalette.of(BuildContext context) =>
      LamToPalette._(Theme.of(context).brightness == Brightness.dark);

  final bool _dark;

  Color get primary => _dark ? LamToColorsDark.primary : LamToColors.primary;
  Color get primarySoft =>
      _dark ? LamToColorsDark.primarySoft : LamToColors.primarySoft;
  Color get bg => _dark ? LamToColorsDark.bg : LamToColors.bg;
  Color get surface => _dark ? LamToColorsDark.surface : LamToColors.surface;
  Color get fill => _dark ? LamToColorsDark.fill : LamToColors.fill;
  Color get ink => _dark ? LamToColorsDark.ink : LamToColors.ink;
  Color get muted => _dark ? LamToColorsDark.muted : LamToColors.muted;
  Color get border => _dark ? LamToColorsDark.border : LamToColors.border;
}

/// Semantic roles: always paired with a text label, never colour alone.
enum StatusTone { success, warning, error, info }

/// Resolves a tone to brightness-correct chip colors.
({Color bg, Color fg}) statusToneColors(BuildContext context, StatusTone tone) {
  final dark = Theme.of(context).brightness == Brightness.dark;
  return switch (tone) {
    StatusTone.success when dark => (
      bg: LamToColorsDark.successBg,
      fg: LamToColorsDark.success,
    ),
    StatusTone.success => (bg: LamToColors.successBg, fg: LamToColors.success),
    StatusTone.warning when dark => (
      bg: LamToColorsDark.warningBg,
      fg: LamToColorsDark.warning,
    ),
    StatusTone.warning => (bg: LamToColors.warningBg, fg: LamToColors.warning),
    StatusTone.error when dark => (
      bg: LamToColorsDark.errorBg,
      fg: LamToColorsDark.error,
    ),
    StatusTone.error => (bg: LamToColors.errorBg, fg: LamToColors.error),
    StatusTone.info when dark => (
      bg: LamToColorsDark.infoBg,
      fg: LamToColorsDark.info,
    ),
    StatusTone.info => (bg: LamToColors.infoBg, fg: LamToColors.info),
  };
}

/// The one chip: a pill with a semantic tint, a label, and an optional icon.
/// Report status and evidence state share it.
class StatusChip extends StatelessWidget {
  const StatusChip({
    required this.tone,
    required this.label,
    this.icon,
    super.key,
  });

  final StatusTone tone;
  final String label;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final colors = statusToneColors(context, tone);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: colors.bg,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, size: 14, color: colors.fg),
            const SizedBox(width: 5),
          ] else ...[
            ExcludeSemantics(
              child: Container(
                width: 6,
                height: 6,
                decoration: BoxDecoration(
                  color: colors.fg,
                  shape: BoxShape.circle,
                ),
              ),
            ),
            const SizedBox(width: 6),
          ],
          Flexible(
            child: Text(
              label,
              style: Theme.of(context).textTheme.labelMedium?.copyWith(
                color: colors.fg,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Inline outcome notice: tinted semantic block + icon + text. The app's
/// snack-bar replacement — snack bars need a Material Scaffold host that the
/// iOS Cupertino tab shell does not provide, so outcomes render inline where
/// the user is looking. A live region, so screen readers announce it.
class StatusNotice extends StatelessWidget {
  const StatusNotice({
    required this.tone,
    required this.message,
    this.icon,
    super.key,
  });

  final StatusTone tone;
  final String message;
  final IconData? icon;

  static IconData _defaultIcon(StatusTone tone) => switch (tone) {
    StatusTone.success => Icons.check_circle_outline,
    StatusTone.error => Icons.error_outline,
    StatusTone.warning || StatusTone.info => Icons.info_outline,
  };

  @override
  Widget build(BuildContext context) {
    final colors = statusToneColors(context, tone);
    return Semantics(
      liveRegion: true,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        decoration: BoxDecoration(
          color: colors.bg,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon ?? _defaultIcon(tone), color: colors.fg, size: 20),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                message,
                style: Theme.of(
                  context,
                ).textTheme.bodyMedium?.copyWith(color: colors.fg),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Tabular-figure style for amounts inside list rows. Full ink on purpose:
/// financial figures are primary copy, not muted metadata.
TextStyle? listAmountStyle(BuildContext context) =>
    Theme.of(context).textTheme.bodyMedium?.copyWith(
      fontFeatures: const [FontFeature.tabularFigures()],
      fontWeight: FontWeight.w600,
    );

/// Money / VND text style with real tabular figures.
TextStyle moneyTextStyle(TextTheme base, {Color? color}) {
  return (base.titleMedium ?? const TextStyle()).copyWith(
    fontFeatures: const [FontFeature.tabularFigures()],
    color: color,
    fontWeight: FontWeight.w600,
  );
}

/// The large figure a screen is about (a balance, a bill, an expense).
TextStyle? heroAmountStyle(BuildContext context) =>
    Theme.of(context).textTheme.headlineMedium?.copyWith(
      fontWeight: FontWeight.w700,
      letterSpacing: -0.6,
      fontFeatures: const [FontFeature.tabularFigures()],
    );

ThemeData lamToTheme(Brightness brightness) {
  final isDark = brightness == Brightness.dark;
  final primary = isDark ? LamToColorsDark.primary : LamToColors.primary;
  final onPrimary = isDark ? LamToColorsDark.onPrimary : LamToColors.onPrimary;
  final primarySoft = isDark
      ? LamToColorsDark.primarySoft
      : LamToColors.primarySoft;
  final surface = isDark ? LamToColorsDark.surface : LamToColors.surface;
  final bg = isDark ? LamToColorsDark.bg : LamToColors.bg;
  final fill = isDark ? LamToColorsDark.fill : LamToColors.fill;
  final ink = isDark ? LamToColorsDark.ink : LamToColors.ink;
  final muted = isDark ? LamToColorsDark.muted : LamToColors.muted;
  final outline = isDark ? LamToColorsDark.border : LamToColors.border;
  final error = isDark ? LamToColorsDark.error : LamToColors.error;

  final scheme = ColorScheme.fromSeed(
    seedColor: LamToColors.primary,
    brightness: brightness,
    primary: primary,
    onPrimary: onPrimary,
    primaryContainer: primarySoft,
    onPrimaryContainer: primary,
    secondaryContainer: primarySoft,
    onSecondaryContainer: primary,
    error: error,
    surface: surface,
    onSurface: ink,
    onSurfaceVariant: muted,
    surfaceContainerLowest: surface,
    surfaceContainerLow: surface,
    surfaceContainer: surface,
    surfaceContainerHigh: fill,
    surfaceContainerHighest: fill,
    outline: outline,
    outlineVariant: outline,
  );

  final baseText = Typography.material2021(
    platform: defaultTargetPlatform,
  ).black.apply(bodyColor: ink, displayColor: ink);
  // Apple-like hierarchy: heavier, tighter titles; body stays the platform
  // default so Dynamic Type and Vietnamese diacritics keep their room.
  final textTheme = baseText.copyWith(
    headlineLarge: baseText.headlineLarge?.copyWith(
      fontSize: 34,
      fontWeight: FontWeight.w700,
      letterSpacing: -0.6,
      height: 1.15,
    ),
    headlineMedium: baseText.headlineMedium?.copyWith(
      fontSize: 30,
      fontWeight: FontWeight.w700,
      letterSpacing: -0.5,
    ),
    headlineSmall: baseText.headlineSmall?.copyWith(
      fontWeight: FontWeight.w700,
      letterSpacing: -0.3,
    ),
    titleLarge: baseText.titleLarge?.copyWith(
      fontSize: 20,
      fontWeight: FontWeight.w700,
      letterSpacing: -0.2,
    ),
    titleMedium: moneyTextStyle(baseText, color: ink),
    titleSmall: baseText.titleSmall?.copyWith(fontWeight: FontWeight.w600),
    labelLarge: baseText.labelLarge?.copyWith(fontWeight: FontWeight.w600),
    bodySmall: baseText.bodySmall?.copyWith(color: muted),
  );

  final controlShape = RoundedRectangleBorder(
    borderRadius: BorderRadius.circular(12),
  );
  const buttonSize = Size.fromHeight(50);
  final buttonText = textTheme.labelLarge?.copyWith(fontSize: 16);

  OutlineInputBorder inputBorder(Color color, [double width = 1]) =>
      OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide(color: color, width: width),
      );

  return ThemeData(
    useMaterial3: true,
    brightness: brightness,
    colorScheme: scheme,
    scaffoldBackgroundColor: bg,
    canvasColor: bg,
    textTheme: textTheme,
    dividerColor: outline,
    dividerTheme: DividerThemeData(color: outline, thickness: 1, space: 1),
    appBarTheme: AppBarTheme(
      backgroundColor: bg,
      foregroundColor: ink,
      elevation: 0,
      scrolledUnderElevation: 0,
      surfaceTintColor: Colors.transparent,
    ),
    cardTheme: CardThemeData(
      color: surface,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
    ),
    listTileTheme: ListTileThemeData(
      iconColor: muted,
      textColor: ink,
      subtitleTextStyle: textTheme.bodyMedium?.copyWith(color: muted),
      minVerticalPadding: 10,
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: buttonSize,
        shape: controlShape,
        textStyle: buttonText,
      ),
    ),
    // Secondary actions read as tinted buttons, not outlined boxes.
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(64, 50),
        shape: controlShape,
        foregroundColor: primary,
        backgroundColor: primarySoft,
        side: BorderSide.none,
        textStyle: buttonText,
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: primary,
        shape: controlShape,
        textStyle: buttonText,
      ),
    ),
    iconButtonTheme: IconButtonThemeData(
      style: IconButton.styleFrom(foregroundColor: ink),
    ),
    floatingActionButtonTheme: FloatingActionButtonThemeData(
      backgroundColor: primary,
      foregroundColor: onPrimary,
      elevation: 3,
      highlightElevation: 4,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
      extendedTextStyle: buttonText,
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: surface,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
      border: inputBorder(outline),
      enabledBorder: inputBorder(outline),
      disabledBorder: inputBorder(outline),
      focusedBorder: inputBorder(primary, 2),
      errorBorder: inputBorder(error),
      focusedErrorBorder: inputBorder(error, 2),
      labelStyle: TextStyle(color: muted),
      floatingLabelStyle: TextStyle(color: primary),
      hintStyle: TextStyle(color: muted),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: surface,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      height: 68,
      indicatorColor: primarySoft,
      labelTextStyle: WidgetStateProperty.resolveWith(
        (states) => textTheme.labelMedium?.copyWith(
          color: states.contains(WidgetState.selected) ? primary : muted,
          fontWeight: states.contains(WidgetState.selected)
              ? FontWeight.w600
              : FontWeight.w500,
        ),
      ),
      iconTheme: WidgetStateProperty.resolveWith(
        (states) => IconThemeData(
          color: states.contains(WidgetState.selected) ? primary : muted,
        ),
      ),
    ),
    navigationRailTheme: NavigationRailThemeData(
      backgroundColor: surface,
      indicatorColor: primarySoft,
      selectedIconTheme: IconThemeData(color: primary),
      unselectedIconTheme: IconThemeData(color: muted),
      selectedLabelTextStyle: textTheme.labelMedium?.copyWith(
        color: primary,
        fontWeight: FontWeight.w600,
      ),
      unselectedLabelTextStyle: textTheme.labelMedium?.copyWith(color: muted),
    ),
    segmentedButtonTheme: SegmentedButtonThemeData(
      style: SegmentedButton.styleFrom(
        backgroundColor: fill,
        foregroundColor: ink,
        selectedBackgroundColor: surface,
        selectedForegroundColor: ink,
        side: BorderSide(color: fill, width: 2),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        textStyle: textTheme.labelLarge,
      ),
    ),
    chipTheme: ChipThemeData(
      backgroundColor: primarySoft,
      labelStyle: textTheme.labelLarge?.copyWith(color: primary),
      iconTheme: IconThemeData(color: primary, size: 18),
      side: BorderSide.none,
      shape: const StadiumBorder(),
    ),
    bottomSheetTheme: BottomSheetThemeData(
      backgroundColor: bg,
      surfaceTintColor: Colors.transparent,
      showDragHandle: true,
      dragHandleColor: outline,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: surface,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
    ),
    expansionTileTheme: ExpansionTileThemeData(
      shape: const Border(),
      collapsedShape: const Border(),
      iconColor: muted,
      collapsedIconColor: muted,
    ),
    progressIndicatorTheme: ProgressIndicatorThemeData(color: primary),
    badgeTheme: BadgeThemeData(backgroundColor: primary, textColor: onPrimary),
    cupertinoOverrideTheme: CupertinoThemeData(
      brightness: brightness,
      primaryColor: primary,
      primaryContrastingColor: onPrimary,
      scaffoldBackgroundColor: bg,
      barBackgroundColor: bg.withValues(alpha: 0.86),
    ),
  );
}
