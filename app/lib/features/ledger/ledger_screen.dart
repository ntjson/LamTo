import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/failure.dart';
import '../../core/format.dart';
import '../../core/providers.dart';
import '../../l10n/app_localizations.dart';
import '../reports/reports_repository.dart' show cursorFromNext;
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
    await future;
  }

  Future<void> loadMore() async {
    final cursor = _nextCursor;
    final current = state.value;
    if (cursor == null || current == null) return;
    final page = await ref
        .read(transparencyRepositoryProvider)
        .listLedger(cursor: cursor, year: year, month: month);
    _nextCursor = cursorFromNext(page.next);
    state = AsyncData([...current, ...page.results]);
  }
}

final ledgerListProvider =
    AsyncNotifierProvider<LedgerListController, List<LedgerEntryList>>(
        LedgerListController.new);

/// Ledger tab (spec 6.3(6)). Body-only: the shell owns chrome.
class LedgerScreen extends ConsumerWidget {
  const LedgerScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context)!;
    final entries = ref.watch(ledgerListProvider);
    final controller = ref.read(ledgerListProvider.notifier);
    final currentYear = DateTime.now().year;
    final years = [for (var y = currentYear; y >= currentYear - 2; y--) y];

    return Material(
      color: Colors.transparent,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(l10n.ledgerTitle,
              style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          // Period filter: "All" + recent years (spec 6.3(6) period filters).
          Wrap(
            spacing: 8,
            children: [
              ChoiceChip(
                label: Text(l10n.ledgerAllTime),
                selected: controller.year == null,
                onSelected: (_) => controller.setPeriod(),
              ),
              for (final y in years)
                ChoiceChip(
                  label: Text('$y'),
                  selected: controller.year == y,
                  onSelected: (_) => controller.setPeriod(newYear: y),
                ),
            ],
          ),
          const SizedBox(height: 8),
          switch (entries) {
            AsyncData(:final value) when value.isEmpty =>
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 24),
                child: Text(l10n.ledgerEmpty),
              ),
            AsyncData(:final value) => Column(
                children: [
                  for (final entry in value)
                    ListTile(
                      minTileHeight: 64,
                      contentPadding: EdgeInsets.zero,
                      title: Text(entry.contractorName,
                          maxLines: 1, overflow: TextOverflow.ellipsis),
                      subtitle: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(formatVnd(entry.actualCostVnd)),
                          const SizedBox(height: 4),
                          EvidenceBadge(level: entry.evidenceLevel),
                        ],
                      ),
                      onTap: () => Navigator.push(
                        context,
                        MaterialPageRoute(
                          builder: (_) =>
                              LedgerDetailScreen(entryId: entry.id),
                        ),
                      ),
                    ),
                  if (controller.hasMore)
                    OutlinedButton(
                      onPressed: controller.loadMore,
                      child: Text(l10n.ledgerLoadMore),
                    ),
                ],
              ),
            AsyncError(:final error) =>
              Text(failureMessage(Failure.fromObject(error), l10n)),
            _ => const Padding(
                padding: EdgeInsets.symmetric(vertical: 24),
                child: Center(child: CircularProgressIndicator.adaptive()),
              ),
          },
        ],
      ),
    );
  }
}
