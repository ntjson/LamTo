import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/legacy.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/adaptive_page_route.dart';
import '../../core/error_retry.dart';
import '../../core/format.dart';
import '../../core/load_more_button.dart';
import '../../core/providers.dart';
import '../../l10n/app_localizations.dart';
import '../../theme.dart';
import '../reports/reports_repository.dart' show cursorFromNext;
import '../transparency/fund_chart.dart';
import '../transparency/transparency_repository.dart';
import 'evidence_labels.dart';
import 'ledger_detail_screen.dart';

class LedgerListController extends AsyncNotifier<List<LedgerEntryList>> {
  String? _nextCursor;
  int? year;
  int? month;

  bool get hasMore => _nextCursor != null;

  @override
  Future<List<LedgerEntryList>> build() async {
    ref.watch(occupancyScopedProviders);
    final page = await ref
        .read(transparencyRepositoryProvider)
        .listLedger(year: year, month: month);
    _nextCursor = cursorFromNext(page.next);
    return page.results.toList();
  }

  Future<void> setPeriod({int? newYear, int? newMonth}) async {
    year = newYear;
    month = newMonth;
    ref.invalidateSelf();
    // The list area renders the failure with its own retry; the chip tap
    // must not escape as an unhandled zone error.
    try {
      await future;
    } catch (_) {}
  }

  Future<void> loadMore() async {
    final cursor = _nextCursor;
    final current = state.value;
    if (cursor == null || current == null) return;
    final page = await ref
        .read(transparencyRepositoryProvider)
        .listLedger(cursor: cursor, year: year, month: month);
    // A refresh or period change may have replaced the list while this page
    // was in flight; appending onto the stale snapshot would clobber it.
    if (!identical(state.value, current)) return;
    _nextCursor = cursorFromNext(page.next);
    state = AsyncData([...current, ...page.results]);
  }
}

final ledgerListProvider =
    AsyncNotifierProvider<LedgerListController, List<LedgerEntryList>>(
      LedgerListController.new,
    );

/// Selected chart range on the Sổ quỹ tab; survives tab switches.
final fundChartRangeProvider = StateProvider<String>((_) => '6m');

/// DESIGN.md filter-chip: Quiet Surface at rest, Accountability Indigo with
/// on-primary ink when selected (never a semantic state color).
class _PeriodChip extends StatelessWidget {
  const _PeriodChip({
    required this.label,
    required this.selected,
    required this.onSelected,
  });

  final String label;
  final bool selected;
  final VoidCallback onSelected;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return ChoiceChip(
      label: Text(label),
      selected: selected,
      selectedColor: scheme.primary,
      checkmarkColor: scheme.onPrimary,
      labelStyle: selected ? TextStyle(color: scheme.onPrimary) : null,
      onSelected: (_) => onSelected(),
    );
  }
}

/// Ledger tab (spec 6.3(6)). Body-only: the shell owns chrome.
class LedgerScreen extends ConsumerWidget {
  const LedgerScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context)!;
    final entries = ref.watch(ledgerListProvider);
    final controller = ref.read(ledgerListProvider.notifier);
    final chartRange = ref.watch(fundChartRangeProvider);
    final currentYear = DateTime.now().year;
    final years = [for (var y = currentYear; y >= currentYear - 2; y--) y];
    String rangeLabel(String key) => switch (key) {
      '30d' => l10n.fundChartRange30d,
      '12m' => l10n.fundChartRange12m,
      _ => l10n.fundChartRange6m,
    };

    return Material(
      color: Colors.transparent,
      child: RefreshIndicator.adaptive(
        onRefresh: () async {
          // The error branch below is the retry surface; a failed refresh
          // must not escape as an unhandled zone error.
          ref.invalidate(ledgerListProvider);
          try {
            await ref.read(ledgerListProvider.future);
          } catch (_) {}
        },
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(16),
          children: [
            Text(
              l10n.ledgerTitle,
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 8),
            // Period filter: "All" + recent years (spec 6.3(6) period filters).
            Wrap(
              spacing: 8,
              children: [
                _PeriodChip(
                  label: l10n.ledgerAllTime,
                  selected: controller.year == null,
                  onSelected: () => controller.setPeriod(),
                ),
                for (final y in years)
                  _PeriodChip(
                    label: '$y',
                    selected: controller.year == y,
                    onSelected: () => controller.setPeriod(newYear: y),
                  ),
              ],
            ),
            const SizedBox(height: 8),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  l10n.fundChartTitle,
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: 8),
                SegmentedButton<String>(
                  segments: [
                    for (final key in fundSeriesRanges)
                      ButtonSegment(value: key, label: Text(rangeLabel(key))),
                  ],
                  selected: {chartRange},
                  showSelectedIcon: false,
                  onSelectionChanged: (selection) =>
                      ref.read(fundChartRangeProvider.notifier).state =
                          selection.first,
                ),
                const SizedBox(height: 12),
                FundChart(range: chartRange),
                const SizedBox(height: 24),
              ],
            ),
            switch (entries) {
              AsyncData(:final value) when value.isEmpty => Padding(
                padding: const EdgeInsets.symmetric(vertical: 24),
                child: Text(l10n.ledgerEmpty),
              ),
              AsyncData(:final value) => Column(
                children: [
                  for (final entry in value)
                    ListTile(
                      minTileHeight: 64,
                      contentPadding: EdgeInsets.zero,
                      title: Text(
                        entry.contractorName,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      subtitle: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            formatVnd(entry.actualCostVnd),
                            style: listAmountStyle(context),
                          ),
                          const SizedBox(height: 4),
                          EvidenceBadge(level: entry.evidenceLevel),
                        ],
                      ),
                      onTap: () => Navigator.push(
                        context,
                        adaptivePageRoute(
                          builder: (_) => LedgerDetailScreen(entryId: entry.id),
                        ),
                      ),
                    ),
                  if (controller.hasMore)
                    LoadMoreButton(
                      label: l10n.ledgerLoadMore,
                      onLoadMore: controller.loadMore,
                    ),
                ],
              ),
              AsyncError(:final error) => ErrorRetry(
                error: error,
                onRetry: () => ref.invalidate(ledgerListProvider),
              ),
              _ => const Padding(
                padding: EdgeInsets.symmetric(vertical: 24),
                child: Center(child: CircularProgressIndicator.adaptive()),
              ),
            },
          ],
        ),
      ),
    );
  }
}
