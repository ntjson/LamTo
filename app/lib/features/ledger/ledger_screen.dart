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
import '../proposals/proposals_list_screen.dart';
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

final ledgerSegmentProvider = StateProvider<int>((_) => 0);

class _LedgerSegmentControl extends ConsumerWidget {
  const _LedgerSegmentControl();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context)!;
    final selected = ref.watch(ledgerSegmentProvider);
    return SegmentedButton<int>(
      segments: [
        ButtonSegment(value: 0, label: Text(l10n.ledgerSegment)),
        ButtonSegment(value: 1, label: Text(l10n.proposalsSegment)),
      ],
      selected: {selected},
      showSelectedIcon: false,
      onSelectionChanged: (value) =>
          ref.read(ledgerSegmentProvider.notifier).state = value.first,
    );
  }
}

/// Ledger tab (spec 6.3(6)). Body-only: the shell owns chrome.
class LedgerScreen extends ConsumerWidget {
  const LedgerScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context)!;
    final segment = ref.watch(ledgerSegmentProvider);
    if (segment == 1) {
      return const Material(
        color: Colors.transparent,
        child: Column(
          children: [
            Padding(
              padding: EdgeInsets.fromLTRB(16, 16, 16, 0),
              child: SizedBox(
                width: double.infinity,
                child: _LedgerSegmentControl(),
              ),
            ),
            Expanded(child: ProposalsListScreen(showTitle: false)),
          ],
        ),
      );
    }
    final entries = ref.watch(ledgerListProvider);
    final controller = ref.read(ledgerListProvider.notifier);
    final currentYear = DateTime.now().year;
    final years = [for (var y = currentYear; y >= 2000; y--) y];

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
            const SizedBox(
              width: double.infinity,
              child: _LedgerSegmentControl(),
            ),
            const SizedBox(height: 16),
            Text(
              l10n.ledgerTitle,
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 8),
            DropdownButtonFormField<int?>(
              initialValue: controller.year,
              decoration: InputDecoration(labelText: l10n.ledgerAllTime),
              items: [
                DropdownMenuItem(value: null, child: Text(l10n.ledgerAllTime)),
                for (final year in years)
                  DropdownMenuItem(value: year, child: Text('$year')),
              ],
              onChanged: (year) => controller.setPeriod(newYear: year),
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
                FundChart(range: '12m'),
                const SizedBox(height: 24),
              ],
            ),
            switch (entries) {
              AsyncData(:final value) when value.isEmpty => Padding(
                padding: const EdgeInsets.symmetric(vertical: 24),
                child: Column(
                  children: [
                    Text(l10n.ledgerEmpty),
                    const SizedBox(height: 12),
                    OutlinedButton(
                      onPressed: controller.year == null
                          ? () =>
                                ref.read(ledgerSegmentProvider.notifier).state =
                                    1
                          : () => controller.setPeriod(),
                      child: Text(
                        controller.year == null
                            ? l10n.proposalsSegment
                            : l10n.ledgerAllTime,
                      ),
                    ),
                  ],
                ),
              ),
              AsyncData(:final value) => Column(
                children: [
                  for (final entry in value)
                    ListTile(
                      minTileHeight: 64,
                      contentPadding: EdgeInsets.zero,
                      title: Text(l10n.ledgerDetailTitle),
                      subtitle: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            entry.contractorName,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
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
