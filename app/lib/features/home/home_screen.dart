import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/error_retry.dart';
import '../../core/format.dart';
import '../../l10n/app_localizations.dart';
import '../../theme.dart';
import '../ledger/ledger_detail_screen.dart';
import '../notifications/notifications_screen.dart';
import '../reports/issue_detail_screen.dart';
import '../reports/my_issues_screen.dart';
import '../transparency/transparency_repository.dart';

/// Home tab (spec 6.3(3)): fund block, period flows, my open reports, recent
/// published spending, notification bell. Body-only: the shell owns chrome.
class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context)!;
    final fund = ref.watch(fundSummaryProvider);
    final reports = ref.watch(myReportsProvider);
    final spending = ref.watch(recentSpendingProvider);

    return Material(
      color: Colors.transparent,
      child: RefreshIndicator.adaptive(
        onRefresh: () async {
          // Each section renders its own AsyncError; a failed refresh must
          // not escape as an unhandled zone error.
          try {
            await Future.wait([
              ref.refresh(fundSummaryProvider.future),
              ref.refresh(recentSpendingProvider.future),
              ref.refresh(myReportsProvider.future),
            ]);
          } catch (_) {}
        },
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(16),
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    l10n.homeFundTitle,
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                ),
                IconButton(
                  iconSize: 28,
                  icon: const Icon(Icons.notifications_outlined),
                  tooltip: l10n.notificationsTitle,
                  onPressed: () => Navigator.push(
                    context,
                    MaterialPageRoute(
                      builder: (_) => const NotificationsScreen(),
                    ),
                  ),
                ),
              ],
            ),
            switch (fund) {
              AsyncData(:final value) => _fundBlock(context, l10n, value),
              AsyncError(:final error) => ErrorRetry(
                error: error,
                onRetry: () => ref.invalidate(fundSummaryProvider),
              ),
              _ => const Padding(
                padding: EdgeInsets.symmetric(vertical: 24),
                child: Center(child: CircularProgressIndicator.adaptive()),
              ),
            },
            const SizedBox(height: 24),
            Text(
              l10n.homeActiveReports,
              style: Theme.of(context).textTheme.titleMedium,
            ),
            switch (reports) {
              AsyncData(:final value) => _activeReports(context, l10n, value),
              AsyncError(:final error) => ErrorRetry(
                error: error,
                onRetry: () => ref.invalidate(myReportsProvider),
              ),
              _ => const SizedBox.shrink(),
            },
            const SizedBox(height: 24),
            Text(
              l10n.homeRecentSpending,
              style: Theme.of(context).textTheme.titleMedium,
            ),
            switch (spending) {
              AsyncData(:final value) => _recentSpending(context, l10n, value),
              AsyncError(:final error) => ErrorRetry(
                error: error,
                onRetry: () => ref.invalidate(recentSpendingProvider),
              ),
              _ => const SizedBox.shrink(),
            },
          ],
        ),
      ),
    );
  }

  /// DESIGN.md fund-balance signature: large tabular amount + stat grid.
  Widget _fundBlock(
    BuildContext context,
    AppLocalizations l10n,
    FundSummary fund,
  ) {
    final amountStyle = Theme.of(context).textTheme.headlineMedium?.copyWith(
      fontWeight: FontWeight.w700,
      fontFeatures: const [FontFeature.tabularFigures()],
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(formatVnd(fund.balanceVnd), style: amountStyle),
        const SizedBox(height: 8),
        Row(
          children: [
            Expanded(
              child: Text(
                '${l10n.homeFundInflows}: '
                '${formatVnd(fund.periodInflowsVnd)}',
              ),
            ),
            Expanded(
              child: Text(
                '${l10n.homeFundOutflows}: '
                '${formatVnd(fund.periodOutflowsVnd)}',
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _activeReports(
    BuildContext context,
    AppLocalizations l10n,
    List<ReportSummary> all,
  ) {
    // A3: shared helper — not a bare inline magic string.
    final open = all
        .where((r) => isActiveReportStatus(r.status))
        .take(3)
        .toList();
    if (open.isEmpty) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Text(l10n.homeNoActiveReports),
      );
    }
    return Column(
      children: [
        for (final report in open)
          ListTile(
            minTileHeight: 56,
            contentPadding: EdgeInsets.zero,
            title: Text(
              report.text,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
            subtitle: Text(reportStatusLabel(report.status, l10n)),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.push(
              context,
              MaterialPageRoute(
                builder: (_) => IssueDetailScreen(reportId: report.id),
              ),
            ),
          ),
      ],
    );
  }

  Widget _recentSpending(
    BuildContext context,
    AppLocalizations l10n,
    List<LedgerEntryList> entries,
  ) {
    if (entries.isEmpty) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Text(l10n.homeNoSpending),
      );
    }
    return Column(
      children: [
        for (final entry in entries)
          ListTile(
            minTileHeight: 56,
            contentPadding: EdgeInsets.zero,
            title: Text(
              entry.contractorName,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
            subtitle: Text(
              formatVnd(entry.actualCostVnd),
              style: listAmountStyle(context),
            ),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.push(
              context,
              MaterialPageRoute(
                builder: (_) => LedgerDetailScreen(entryId: entry.id),
              ),
            ),
          ),
      ],
    );
  }
}
