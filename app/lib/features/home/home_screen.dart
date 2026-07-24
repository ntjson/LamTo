import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/adaptive_page_route.dart';
import '../../core/error_retry.dart';
import '../../core/format.dart';
import '../../l10n/app_localizations.dart';
import '../../theme.dart';
import '../bills/bill_detail_screen.dart';
import '../bills/bills_repository.dart';
import '../bills/bills_screen.dart';
import '../ledger/ledger_detail_screen.dart';
import '../notifications/notifications_screen.dart';
import '../reports/issue_detail_screen.dart';
import '../reports/my_issues_screen.dart';
import '../shell/home_shell.dart';
import '../transparency/fund_chart.dart';
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
    final announcement = ref.watch(latestAnnouncementProvider);
    final newestBill = ref.watch(newestUnpaidBillProvider);

    return Material(
      color: Colors.transparent,
      child: RefreshIndicator.adaptive(
        onRefresh: () async {
          try {
            await Future.wait([
              ref.refresh(fundSummaryProvider.future),
              ref.refresh(recentSpendingProvider.future),
              ref.refresh(myReportsProvider.future),
              ref.refresh(latestAnnouncementProvider.future),
              ref.refresh(newestUnpaidBillProvider.future),
            ]);
          } catch (_) {
            // Each failed provider retains AsyncError and renders its retry
            // surface below; do not turn a handled section error into a zone error.
          }
        },
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(16),
          children: [
            ...switch (newestBill) {
              AsyncData(value: final bill?) => [
                ListTile(
                  minTileHeight: 64,
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.receipt_long_outlined),
                  title: Text(l10n.homeBillTitle),
                  subtitle: Text(
                    '${bill.title} · ${formatVnd(bill.amountVnd)}',
                  ),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => Navigator.push(
                    context,
                    adaptivePageRoute(
                      builder: (_) => BillDetailScreen(billId: bill.id),
                    ),
                  ),
                ),
                const Divider(),
              ],
              AsyncData() => const [],
              AsyncError(:final error) => [
                Padding(
                  padding: const EdgeInsets.only(bottom: 16),
                  child: ErrorRetry(
                    error: error,
                    onRetry: () => ref.invalidate(newestUnpaidBillProvider),
                  ),
                ),
              ],
              _ => [_SectionLoading(label: l10n.homeBillLoading)],
            },
            if (announcement.value case final notice?) ...[
              Card.filled(
                child: ListTile(
                  minTileHeight: 64,
                  leading: const Icon(Icons.campaign_outlined),
                  title: Text(l10n.homeAnnouncementTitle),
                  subtitle: Text(
                    notice.subject,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                  ),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => _openAnnouncement(context, ref, notice),
                ),
              ),
              const SizedBox(height: 16),
            ],
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
                  icon: const Icon(Icons.receipt_long_outlined),
                  tooltip: l10n.billsTitle,
                  onPressed: () => Navigator.push(
                    context,
                    adaptivePageRoute(builder: (_) => const BillsScreen()),
                  ),
                ),
                IconButton(
                  iconSize: 28,
                  icon: const Icon(Icons.notifications_outlined),
                  tooltip: l10n.notificationsTitle,
                  onPressed: () => Navigator.push(
                    context,
                    adaptivePageRoute(
                      builder: (_) => const NotificationsScreen(),
                    ),
                  ),
                ),
              ],
            ),
            switch (fund) {
              AsyncData(:final value) => _fundBlock(context, ref, l10n, value),
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
              _ => _SectionLoading(label: l10n.homeReportsLoading),
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
              _ => _SectionLoading(label: l10n.homeSpendingLoading),
            },
          ],
        ),
      ),
    );
  }

  Future<void> _openAnnouncement(
    BuildContext context,
    WidgetRef ref,
    NotificationFeed notice,
  ) async {
    await ref
        .read(transparencyRepositoryProvider)
        .markNotificationRead(notice.id);
    ref.invalidate(latestAnnouncementProvider);
    ref.invalidate(notificationsProvider);
    if (context.mounted) await showNotificationDialog(context, notice);
  }

  /// DESIGN.md fund-balance signature: large tabular amount + stat grid.
  Widget _fundBlock(
    BuildContext context,
    WidgetRef ref,
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
        if (MediaQuery.textScalerOf(context).scale(1) >= 1.5)
          Column(
            key: const Key('fund-period-stats-stacked'),
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '${l10n.homeFundInflows}: '
                '${formatVnd(fund.periodInflowsVnd)}',
              ),
              const SizedBox(height: 4),
              Text(
                '${l10n.homeFundOutflows}: '
                '${formatVnd(fund.periodOutflowsVnd)}',
              ),
            ],
          )
        else
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
        const SizedBox(height: 16),
        FundChart(
          range: '6m',
          compact: true,
          onTap: () => selectLedgerTab(ref),
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
              adaptivePageRoute(
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
              adaptivePageRoute(
                builder: (_) => LedgerDetailScreen(entryId: entry.id),
              ),
            ),
          ),
      ],
    );
  }
}

class _SectionLoading extends StatelessWidget {
  const _SectionLoading({required this.label});
  final String label;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 12),
    child: Semantics(
      liveRegion: true,
      child: Row(
        children: [
          const SizedBox.square(
            dimension: 20,
            child: CircularProgressIndicator.adaptive(strokeWidth: 2),
          ),
          const SizedBox(width: 12),
          Expanded(child: Text(label)),
        ],
      ),
    ),
  );
}
