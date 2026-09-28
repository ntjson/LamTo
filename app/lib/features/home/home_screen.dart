import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/adaptive_buttons.dart';
import '../../core/adaptive_page_route.dart';
import '../../core/error_retry.dart';
import '../../core/format.dart';
import '../../core/providers.dart';
import '../../l10n/app_localizations.dart';
import '../../theme.dart';
import '../../widgets/grouped.dart';
import '../auth/session_controller.dart';
import '../bills/bill_detail_screen.dart';
import '../bills/bills_repository.dart';
import '../bills/bills_screen.dart';
import '../ledger/ledger_detail_screen.dart';
import '../notifications/notifications_screen.dart';
import '../reports/issue_detail_screen.dart';
import '../reports/my_issues_screen.dart';
import '../reports/report_form_screen.dart';
import '../shell/home_shell.dart';
import '../shell/tab_page.dart';
import '../transparency/fund_chart.dart';
import '../transparency/transparency_repository.dart';

/// Home tab: a summary in the order a resident needs it — what asks for
/// their attention, where to go, then the fund, their open reports, and the
/// spending the building has just published. Body-only: the shell owns the
/// tab chrome, [TabPage] the collapsing title.
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
    // Same feed the Notifications screen shows (mark-read updates it
    // optimistically). Best-effort: loading or failed feed = no badge.
    final unreadCount =
        ref
            .watch(notificationsProvider)
            .value
            ?.where((notice) => notice.readAt == null)
            .length ??
        0;

    final attention = <Widget>[
      ...switch (newestBill) {
        AsyncData(value: final bill?) => [
          ListTile(
            minTileHeight: 64,
            leading: const IconWell(
              Icons.receipt_long_outlined,
              tone: StatusTone.warning,
            ),
            title: Text(l10n.homeBillTitle),
            subtitle: Text('${bill.title} · ${formatVnd(bill.amountVnd)}'),
            trailing: const _Chevron(),
            onTap: () => Navigator.push(
              context,
              adaptivePageRoute(
                builder: (_) => BillDetailScreen(billId: bill.id),
              ),
            ),
          ),
        ],
        _ => const <Widget>[],
      },
      if (announcement.value case final notice?)
        ListTile(
          minTileHeight: 64,
          leading: const IconWell(Icons.campaign_outlined),
          title: Text(l10n.homeAnnouncementTitle),
          subtitle: Text(
            notice.subject,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
          trailing: const _Chevron(),
          onTap: () => _openAnnouncement(context, ref, notice),
        ),
    ];

    return Material(
      color: Colors.transparent,
      child: TabPage(
        title: l10n.tabHome,
        onRefresh: () async {
          try {
            await Future.wait([
              ref.refresh(fundSummaryProvider.future),
              ref.refresh(recentSpendingProvider.future),
              ref.refresh(myReportsProvider.future),
              ref.refresh(latestAnnouncementProvider.future),
              ref.refresh(newestUnpaidBillProvider.future),
              ref.refresh(notificationsProvider.future),
            ]);
          } catch (_) {
            // Each failed provider retains AsyncError and renders its retry
            // surface below; do not turn a handled section error into a zone error.
          }
        },
        slivers: [
          SliverPadding(
            padding: tabContentPadding,
            // Short, bounded content: built whole, like a plain column.
            sliver: SliverToBoxAdapter(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const _HomeContext(),
                  if (newestBill case AsyncError(:final error))
                    Padding(
                      padding: const EdgeInsets.only(bottom: 16),
                      child: ErrorRetry(
                        error: error,
                        onRetry: () => ref.invalidate(newestUnpaidBillProvider),
                      ),
                    )
                  else if (newestBill is! AsyncData)
                    _SectionLoading(label: l10n.homeBillLoading),
                  if (attention.isNotEmpty) ...[
                    InsetGroup(dividerIndent: 68, children: attention),
                    const SizedBox(height: 16),
                  ],
                  // Labeled entries, not icon-only chrome: every resident can
                  // read where a row goes without long-pressing for a tooltip.
                  InsetGroup(
                    dividerIndent: 68,
                    children: [
                      ListTile(
                        minTileHeight: 56,
                        leading: const IconWell(Icons.receipt_long_outlined),
                        title: Text(l10n.billsTitle),
                        trailing: const _Chevron(),
                        onTap: () => Navigator.push(
                          context,
                          adaptivePageRoute(
                            builder: (_) => const BillsScreen(),
                          ),
                        ),
                      ),
                      ListTile(
                        minTileHeight: 56,
                        leading: const IconWell(Icons.notifications_outlined),
                        title: Text(l10n.notificationsTitle),
                        trailing: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            if (unreadCount > 0) ...[
                              Semantics(
                                label: l10n.notificationsUnreadCount(
                                  unreadCount,
                                ),
                                child: ExcludeSemantics(
                                  child: Badge.count(count: unreadCount),
                                ),
                              ),
                              const SizedBox(width: 8),
                            ],
                            const _Chevron(),
                          ],
                        ),
                        onTap: () => Navigator.push(
                          context,
                          adaptivePageRoute(
                            builder: (_) => const NotificationsScreen(),
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 28),
                  SectionHeader(l10n.homeFundTitle),
                  switch (fund) {
                    AsyncData(:final value) => _fundBlock(
                      context,
                      ref,
                      l10n,
                      value,
                    ),
                    AsyncError(:final error) => ErrorRetry(
                      error: error,
                      onRetry: () => ref.invalidate(fundSummaryProvider),
                    ),
                    _ => const Padding(
                      padding: EdgeInsets.symmetric(vertical: 24),
                      child: Center(
                        child: CircularProgressIndicator.adaptive(),
                      ),
                    ),
                  },
                  const SizedBox(height: 28),
                  SectionHeader(l10n.homeActiveReports),
                  switch (reports) {
                    AsyncData(:final value) => _activeReports(
                      context,
                      l10n,
                      value,
                    ),
                    AsyncError(:final error) => ErrorRetry(
                      error: error,
                      onRetry: () => ref.invalidate(myReportsProvider),
                    ),
                    _ => _SectionLoading(label: l10n.homeReportsLoading),
                  },
                  const SizedBox(height: 28),
                  SectionHeader(l10n.homeRecentSpending),
                  switch (spending) {
                    AsyncData(:final value) => _recentSpending(
                      context,
                      ref,
                      l10n,
                      value,
                    ),
                    AsyncError(:final error) => ErrorRetry(
                      error: error,
                      onRetry: () => ref.invalidate(recentSpendingProvider),
                    ),
                    _ => _SectionLoading(label: l10n.homeSpendingLoading),
                  },
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _openAnnouncement(
    BuildContext context,
    WidgetRef ref,
    NotificationFeed notice,
  ) async {
    // Best-effort mark-read, same doctrine as NotificationsController
    // .markRead: the feed is authoritative, a failed call simply leaves the
    // row unread — and reading the announcement must work offline.
    unawaited(() async {
      try {
        await ref
            .read(transparencyRepositoryProvider)
            .markNotificationRead(notice.id);
      } catch (_) {
        return; // unread it stays; nothing to refresh
      }
      if (!context.mounted) return;
      ref.invalidate(latestAnnouncementProvider);
      ref.invalidate(notificationsProvider);
    }());
    await showNotificationDialog(context, notice);
  }

  /// The fund at a glance: the balance, its 30-day movement, and the
  /// six-month trend — which is itself the way into the ledger.
  Widget _fundBlock(
    BuildContext context,
    WidgetRef ref,
    AppLocalizations l10n,
    FundSummary fund,
  ) {
    final theme = Theme.of(context);
    final muted = theme.textTheme.bodySmall?.copyWith(fontSize: 13);
    final figure = theme.textTheme.bodyMedium?.copyWith(
      fontWeight: FontWeight.w600,
      fontFeatures: const [FontFeature.tabularFigures()],
    );
    Text stat(String label, int amount) => Text.rich(
      TextSpan(
        children: [
          TextSpan(text: '$label: ', style: muted),
          TextSpan(text: formatVnd(amount), style: figure),
        ],
      ),
    );
    return InsetGroup(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
      children: [
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(formatVnd(fund.balanceVnd), style: heroAmountStyle(context)),
            const SizedBox(height: 6),
            // A figure broken across two lines reads as a different number, so
            // each stat stays whole and the pair stacks when it no longer fits
            // side by side. A long amount and a large text size are the same
            // problem, and this measures the content rather than guessing at
            // either.
            Wrap(
              key: const Key('fund-period-stats'),
              spacing: 16,
              runSpacing: 4,
              children: [
                stat(l10n.homeFundInflows, fund.periodInflowsVnd),
                stat(l10n.homeFundOutflows, fund.periodOutflowsVnd),
              ],
            ),
            const SizedBox(height: 16),
            FundChart(
              range: '6m',
              compact: true,
              onTap: () => selectLedgerTab(ref),
            ),
            const SizedBox(height: 8),
            Text(l10n.homeFundChartCaption, style: theme.textTheme.bodySmall),
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
    final open = all
        .where((r) => isActiveReportStatus(r.status))
        .take(3)
        .toList();
    if (open.isEmpty) {
      return InsetGroup(
        children: [
          EmptyState(
            icon: Icons.check_circle_outline,
            message: l10n.homeNoActiveReports,
            action: AdaptiveTextButton(
              onPressed: () => openReportForm(context),
              child: Text(l10n.tabReport),
            ),
          ),
        ],
      );
    }
    return InsetGroup(
      children: [
        for (final report in open)
          ListTile(
            minTileHeight: 64,
            title: Text(
              report.text,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
            subtitle: Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Align(
                alignment: Alignment.centerLeft,
                child: StatusChip(
                  tone: reportStatusTone(report.status),
                  label: reportStatusLabel(report.status, l10n),
                ),
              ),
            ),
            trailing: const _Chevron(),
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
    WidgetRef ref,
    AppLocalizations l10n,
    List<LedgerEntryList> entries,
  ) {
    if (entries.isEmpty) {
      return InsetGroup(
        children: [
          EmptyState(
            icon: Icons.account_balance_outlined,
            message: l10n.homeNoSpending,
            action: AdaptiveTextButton(
              onPressed: () => selectLedgerTab(ref),
              child: Text(l10n.tabLedger),
            ),
          ),
        ],
      );
    }
    return InsetGroup(
      children: [
        for (final entry in entries)
          ListTile(
            minTileHeight: 64,
            // Lead with the story subject; the constant title is only the
            // fallback so a row never renders a bare blank.
            title: Text(
              entry.whatWasFixed.isNotEmpty
                  ? entry.whatWasFixed
                  : l10n.ledgerDetailTitle,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
            subtitle: Column(
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
              ],
            ),
            trailing: figuresTrail(context)
                ? Text(
                    formatVnd(entry.actualCostVnd),
                    style: listAmountStyle(context),
                  )
                : const _Chevron(),
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

/// The resident's building and unit under the title, so a multi-unit
/// resident always knows which home the numbers belong to.
class _HomeContext extends ConsumerWidget {
  const _HomeContext();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(sessionControllerProvider);
    final me = switch (session) {
      AsyncData(value: SessionAuthenticated(:final me)) => me,
      _ => null,
    };
    final selected = ref.watch(occupancyHolderProvider).occupancyId;
    final occupancy = me?.occupancies
        .where((o) => o.id == selected)
        .firstOrNull;
    if (occupancy == null) return const SizedBox(height: 4);
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 0, 4, 16),
      child: Text(
        '${occupancy.buildingName} · ${occupancy.unitLabel}',
        style: Theme.of(
          context,
        ).textTheme.bodyLarge?.copyWith(color: LamToPalette.of(context).muted),
      ),
    );
  }
}

class _Chevron extends StatelessWidget {
  const _Chevron();

  @override
  Widget build(BuildContext context) => Icon(
    Icons.chevron_right,
    color: LamToPalette.of(context).muted.withValues(alpha: 0.6),
  );
}

class _SectionLoading extends StatelessWidget {
  const _SectionLoading({required this.label});
  final String label;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 4),
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
