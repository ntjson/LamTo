import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/theme.dart';

void main() {
  test('theme uses Accountability Indigo as primary', () {
    final theme = lamToTheme(Brightness.light);
    expect(theme.colorScheme.primary, LamToColors.primary);
    expect(theme.useMaterial3, isTrue);
  });

  test('dark theme has complete surface tokens', () {
    final theme = lamToTheme(Brightness.dark);
    expect(theme.colorScheme.surface, LamToColorsDark.surface);
    expect(theme.colorScheme.onSurface, LamToColorsDark.ink);
    expect(theme.colorScheme.outline, LamToColorsDark.border);
    expect(theme.scaffoldBackgroundColor, LamToColorsDark.bg);
    expect(theme.brightness, Brightness.dark);
  });

  test('moneyTextStyle uses tabular figures', () {
    final theme = lamToTheme(Brightness.light);
    final style = moneyTextStyle(theme.textTheme);
    expect(style.fontFeatures, contains(const FontFeature.tabularFigures()));
    expect(
      theme.textTheme.titleMedium?.fontFeatures,
      contains(const FontFeature.tabularFigures()),
    );
  });
}
