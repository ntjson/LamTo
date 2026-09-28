import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/legacy.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/adaptive_buttons.dart';
import '../../core/adaptive_page_route.dart';
import '../../core/error_retry.dart';
import '../../core/format.dart';
import '../../core/load_more_button.dart';
import '../../core/providers.dart';
import '../../l10n/app_localizations.dart';
import '../../theme.dart';
import '../../widgets/grouped.dart';
import '../shell/tab_page.dart';
import '../reports/reports_repository.dart' show cursorFromNext;
import '../proposals/proposals_list_screen.dart';
import '../transparency/fund_chart.dart';
import '../transparency/transparency_repository.dart';
import 'evidence_labels.dart';
import 'ledger_detail_screen.dart';

/// Period filter lives outside the controller: Riverpod 3 recreates the
/// notifier whenever the provider rebuilds, so fields stored on it do not
/// survive an invalidation (the selected year silently reset to "all").
final ledgerYearProvider = StateProvider<int?>((_) => null);
final ledgerMonthProvider = StateProvider<int?>((_) => null);

class LedgerListController extends AsyncNotifier<List<LedgerEntryList>> {
  String? _nextCursor;

  bool get hasMore => _nextCursor != null;

  @override
  Future<List<LedgerEntryList>> build() async {
    ref.watch(occupancyScopedProviders);
    final page = await ref
        .read(transparencyRepositoryProvider)
        .listLedger(
          year: ref.watch(ledgerYearProvider),
          month: ref.watch(ledgerMonthProvider),
        );
    _nextCursor = cursorFromNext(page.next);
    return page.results.toList();
  }

  Future<void> loadMore() async {
    final cursor = _nextCursor;
    final current = state.value;
    if (cursor == null || current == null) return;
    final page = await ref
        .read(transparencyRepositoryProvider)
        .listLedger(
          cursor: cursor,
          year: ref.read(ledgerYearProvider),
          month: ref.read(ledgerMonthProvider),
        );
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

/// Ledger tab (spec 6.3(6)). Body-only: the shell owns the tab chrome,
/// [TabPage] the collapsing title. One segmented control switches between
/// the published ledger and the proposals behind it.
class LedgerScreen extends ConsumerWidget {
  const LedgerScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context)!;
    final segment = ref.watch(ledgerSegmentProvider);
    final header = SliverPadding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 20),
      sliver: const SliverToBoxAdapter(
        child: SizedBox(width: double.infinity, child: _LedgerSegmentControl()),
      ),
    );
    return Material(
      color: Colors.transparent,
      child: TabPage(
        title: l10n.ledgerTitle,
        onRefresh: () async {
          // The error branches are the retry surfaces; a failed refresh
          // must not escape as an unhandled zone error.
          try {
            if (segment == 1) {
              ref.invalidate(proposalsListProvider);
              await ref.read(proposalsListProvider.future);
            } else {
              ref.invalidate(ledgerListProvider);
              await ref.read(ledgerListProvider.future);
            }
          } catch (_) {}
        },
        slivers: [
          header,
          if (segment == 1) const ProposalsSliver() else const _LedgerEntries(),
        ],
      ),
    );
  }
}

/// The trailing-year fund chart, the period filter, and the entries.
class _LedgerEntries extends ConsumerWidget {
  const _LedgerEntries();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context)!;
    final entries = ref.watch(ledgerListProvider);
    final controller = ref.read(ledgerListProvider.notifier);
    final year = ref.watch(ledgerYearProvider);
    final month = ref.watch(ledgerMonthProvider);
    final currentYear = DateTime.now().year;
    final years = [for (var y = currentYear; y >= 2000; y--) y];
    final localeName = Localizations.localeOf(context).toString();

    final intro = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        InsetGroup(
          header: l10n.fundChartTitle,
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
          children: [FundChart(range: '12m')],
        ),
        const SizedBox(height: 28),
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: DropdownButtonFormField<int?>(
                initialValue: year,
                decoration: InputDecoration(labelText: l10n.ledgerYearLabel),
                items: [
                  DropdownMenuItem(
                    value: null,
                    child: Text(l10n.ledgerAllTime),
                  ),
                  for (final y in years)
                    DropdownMenuItem(value: y, child: Text('$y')),
                ],
                onChanged: (value) {
                  // Month is a within-year refinement; a new year resets it.
                  ref.read(ledgerYearProvider.notifier).state = value;
                  ref.read(ledgerMonthProvider.notifier).state = null;
                },
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: DropdownButtonFormField<int?>(
                initialValue: month,
                decoration: InputDecoration(labelText: l10n.ledgerMonthLabel),
                items: [
                  DropdownMenuItem(
                    value: null,
                    child: Text(l10n.ledgerAllTime),
                  ),
                  for (var m = 1; m <= 12; m++)
                    DropdownMenuItem(
                      value: m,
                      child: Text(formatMonthLabel(m, localeName)),
                    ),
                ],
                onChanged: year == null
                    ? null
                    : (value) =>
                          ref.read(ledgerMonthProvider.notifier).state = value,
              ),
            ),
          ],
        ),
        const SizedBox(height: 16),
      ],
    );

    final list = switch (entries) {
      // Builder-based so a long paginated history lays out lazily.
      AsyncData(:final value) when value.isNotEmpty => [
        SliverList.builder(
          itemCount: value.length,
          itemBuilder: (context, i) => GroupedListItem(
            isFirst: i == 0,
            isLast: i == value.length - 1,
            child: _entryTile(context, l10n, value[i]),
          ),
        ),
        if (controller.hasMore)
          SliverToBoxAdapter(
            child: LoadMoreButton(
              label: l10n.ledgerLoadMore,
              onLoadMore: controller.loadMore,
            ),
          ),
      ],
      AsyncData() => [
        SliverToBoxAdapter(
          child: InsetGroup(
            children: [
              EmptyState(
                icon: Icons.account_balance_outlined,
                message: l10n.ledgerEmpty,
                action: AdaptiveOutlinedButton(
                  onPressed: year == null
                      ? () => ref.read(ledgerSegmentProvider.notifier).state = 1
                      : () {
                          ref.read(ledgerYearProvider.notifier).state = null;
                          ref.read(ledgerMonthProvider.notifier).state = null;
                        },
                  child: Text(
                    year == null ? l10n.proposalsSegment : l10n.ledgerAllTime,
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
      AsyncError(:final error) => [
        SliverToBoxAdapter(
          child: ErrorRetry(
            error: error,
            onRetry: () => ref.invalidate(ledgerListProvider),
          ),
        ),
      ],
      _ => [
        const SliverToBoxAdapter(
          child: Padding(
            padding: EdgeInsets.symmetric(vertical: 24),
            child: Center(child: CircularProgressIndicator.adaptive()),
          ),
        ),
      ],
    };

    return SliverPadding(
      padding: tabContentPadding,
      sliver: SliverMainAxisGroup(
        slivers: [
          SliverToBoxAdapter(child: intro),
          ...list,
        ],
      ),
    );
  }

  Widget _entryTile(
    BuildContext context,
    AppLocalizations l10n,
    LedgerEntryList entry,
  ) => ListTile(
    minTileHeight: 72,
    contentPadding: const EdgeInsets.fromLTRB(16, 4, 12, 4),
    // Lead with the story subject; the constant title is only the fallback
    // so a row never renders a bare blank.
    title: Text(
      entry.whatWasFixed.isNotEmpty
          ? entry.whatWasFixed
          : l10n.ledgerDetailTitle,
      maxLines: 2,
      overflow: TextOverflow.ellipsis,
    ),
    subtitle: Padding(
      padding: const EdgeInsets.only(top: 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            entry.contractorName,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
          if (!figuresTrail(context))
            Text(
              formatVnd(entry.actualCostVnd),
              style: listAmountStyle(context),
            ),
          const SizedBox(height: 8),
          EvidenceBadge(level: entry.evidenceLevel),
        ],
      ),
    ),
    trailing: figuresTrail(context)
        ? Text(formatVnd(entry.actualCostVnd), style: listAmountStyle(context))
        : null,
    onTap: () => Navigator.push(
      context,
      adaptivePageRoute(builder: (_) => LedgerDetailScreen(entryId: entry.id)),
    ),
  );
}
