import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/error_retry.dart';
import '../../l10n/app_localizations.dart';
import 'transparency_repository.dart';

/// Fund balance history. Home uses the compact line; Ledger uses the full view.
class FundChart extends ConsumerWidget {
  const FundChart({
    super.key,
    required this.range,
    this.compact = false,
    this.onTap,
  });

  final String range;
  final bool compact;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context)!;
    return switch (ref.watch(fundSeriesProvider(range))) {
      AsyncData(:final value) => Semantics(
        label: l10n.fundChartSemantics,
        button: onTap != null,
        child: _chart(context, l10n, value),
      ),
      AsyncError(:final error) => ErrorRetry(
        error: error,
        onRetry: () => ref.invalidate(fundSeriesProvider(range)),
      ),
      _ => const SizedBox(
        height: 160,
        child: Center(child: CircularProgressIndicator.adaptive()),
      ),
    };
  }

  Widget _chart(
    BuildContext context,
    AppLocalizations l10n,
    FundSeries series,
  ) {
    final points = series.points.toList();
    if (points.isEmpty) return const SizedBox.shrink();
    final line = _balanceLine(context, points);
    if (compact) {
      return InkWell(
        onTap: onTap,
        child: SizedBox(height: 140, child: line),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(height: 180, child: line),
        const SizedBox(height: 16),
        Text(
          l10n.fundChartFlowsTitle,
          style: Theme.of(context).textTheme.titleSmall,
        ),
        const SizedBox(height: 8),
        SizedBox(height: 120, child: _flowsBars(context, points)),
      ],
    );
  }

  Duration _animationDuration(BuildContext context) =>
      MediaQuery.disableAnimationsOf(context)
      ? Duration.zero
      : const Duration(milliseconds: 200);

  Widget _balanceLine(BuildContext context, List<FundSeriesPoint> points) {
    final scheme = Theme.of(context).colorScheme;
    return LineChart(
      LineChartData(
        gridData: const FlGridData(show: false),
        borderData: FlBorderData(show: false),
        titlesData: FlTitlesData(
          leftTitles: const AxisTitles(),
          topTitles: const AxisTitles(),
          rightTitles: const AxisTitles(),
          bottomTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: !compact,
              interval: (points.length / 6).ceilToDouble(),
              getTitlesWidget: (value, _) =>
                  _periodLabel(context, points, value),
            ),
          ),
        ),
        lineTouchData: LineTouchData(enabled: !compact),
        lineBarsData: [
          LineChartBarData(
            spots: [
              for (var i = 0; i < points.length; i++)
                FlSpot(i.toDouble(), points[i].balanceVnd.toDouble()),
            ],
            isCurved: false,
            color: scheme.primary,
            dotData: const FlDotData(show: false),
            belowBarData: BarAreaData(
              show: true,
              color: scheme.primary.withValues(alpha: 0.12),
            ),
          ),
        ],
      ),
      duration: _animationDuration(context),
    );
  }

  Widget _flowsBars(BuildContext context, List<FundSeriesPoint> points) {
    final scheme = Theme.of(context).colorScheme;
    return BarChart(
      BarChartData(
        gridData: const FlGridData(show: false),
        borderData: FlBorderData(show: false),
        titlesData: const FlTitlesData(
          leftTitles: AxisTitles(),
          topTitles: AxisTitles(),
          rightTitles: AxisTitles(),
          bottomTitles: AxisTitles(),
        ),
        barGroups: [
          for (var i = 0; i < points.length; i++)
            BarChartGroupData(
              x: i,
              barRods: [
                BarChartRodData(
                  toY: points[i].inflowsVnd.toDouble(),
                  color: scheme.tertiary,
                  width: 6,
                ),
                BarChartRodData(
                  toY: points[i].outflowsVnd.toDouble(),
                  color: scheme.error,
                  width: 6,
                ),
              ],
            ),
        ],
      ),
      duration: _animationDuration(context),
    );
  }

  Widget _periodLabel(
    BuildContext context,
    List<FundSeriesPoint> points,
    double value,
  ) {
    final i = value.toInt();
    if (i < 0 || i >= points.length) return const SizedBox.shrink();
    final pattern = range == '30d' ? 'd/M' : 'M/yy';
    final label = DateFormat(
      pattern,
      Localizations.localeOf(context).toLanguageTag(),
    ).format(points[i].periodStart);
    return Padding(
      padding: const EdgeInsets.only(top: 4),
      child: Text(label, style: Theme.of(context).textTheme.labelSmall),
    );
  }
}
