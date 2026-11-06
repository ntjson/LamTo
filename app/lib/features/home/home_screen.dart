import 'dart:async';

import 'package:flutter/cupertino.dart';
import 'package:flutter/foundation.dart';
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
import '../../widgets/brand_identity.dart';
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
import 'ad_carousel.dart';
import 'home_ads.dart';
import '../shell/tab_page.dart';
import '../transparency/fund_chart.dart';
import '../transparency/transparency_repository.dart';

/// Home tab: a summary in the order a resident needs it — the fund on a card
/// over the brand header, where to go, what asks for their attention, the
/// ads, then the fund trend, their open reports, and the spending the
/// building has just published. Body-only: the shell owns the tab chrome;
/// unlike the other tabs, Home draws its own header instead of [TabPage]'s.
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

    Future<void> refresh() async {
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
    }

    final isIos = defaultTargetPlatform == TargetPlatform.iOS;
    final bottom = MediaQuery.paddingOf(context).bottom;
    final view = CustomScrollView(
      physics: AlwaysScrollableScrollPhysics(
        parent: isIos ? const BouncingScrollPhysics() : null,
      ),
      slivers: [
        if (isIos) CupertinoSliverRefreshControl(onRefresh: refresh),
        // Home draws its own brand header instead of TabPage's large title.
        SliverToBoxAdapter(
          child: _HomeHeader(
            card: switch (fund) {
              AsyncData(:final value) => _fundCard(context, l10n, value),
              AsyncError(:final error) => ErrorRetry(
                error: error,
                onRetry: () => ref.invalidate(fundSummaryProvider),
              ),
              _ => const Padding(
                padding: EdgeInsets.symmetric(vertical: 24),
                child: Center(child: CircularProgressIndicator.adaptive()),
              ),
            },
          ),
        ),
        SliverPadding(
          padding: tabContentPadding,
          // Short, bounded content: built whole, like a plain column.
          sliver: SliverToBoxAdapter(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const SizedBox(height: 16),
                // Labeled tiles, not icon-only chrome: every resident can
                // read where a tile goes without long-pressing for a tooltip.
                _ShortcutGrid(
                  tiles: [
                    _Shortcut(
                      icon: Icons.receipt_long_outlined,
                      label: l10n.billsTitle,
                      onTap: () => Navigator.push(
                        context,
                        adaptivePageRoute(builder: (_) => const BillsScreen()),
                      ),
                    ),
                    _Shortcut(
                      icon: Icons.add_comment_outlined,
                      label: l10n.tabReport,
                      onTap: () => openReportForm(context),
                    ),
                    _Shortcut(
                      icon: Icons.account_balance_outlined,
                      label: l10n.tabLedger,
                      onTap: () => selectLedgerTab(ref),
                    ),
                    _Shortcut(
                      icon: Icons.notifications_outlined,
                      label: l10n.notificationsTitle,
                      unreadCount: unreadCount,
                      onTap: () => Navigator.push(
                        context,
                        adaptivePageRoute(
                          builder: (_) => const NotificationsScreen(),
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
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
              ],
            ),
          ),
        ),
        // Full width, so the neighbouring slides peek in at the edges.
        const SliverToBoxAdapter(child: AdCarousel(ads: demoHomeAds)),
        SliverPadding(
          padding: tabContentPadding,
          sliver: SliverToBoxAdapter(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (fund is AsyncData) ...[
                  const SizedBox(height: 24),
                  _fundTrend(context, ref, l10n),
                ],
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
        // Room below the last row for the tab bar / floating action button.
        SliverToBoxAdapter(child: SizedBox(height: bottom + 96)),
      ],
    );
    return Material(
      color: Colors.transparent,
      child: isIos ? view : RefreshIndicator(onRefresh: refresh, child: view),
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

  /// The fund at a glance, on the card over the header: whose home, the
  /// balance, and its 30-day movement.
  Widget _fundCard(
    BuildContext context,
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
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _HomeContext(),
        Text(
          l10n.homeFundTitle,
          style: theme.textTheme.labelLarge?.copyWith(
            color: LamToPalette.of(context).muted,
          ),
        ),
        const SizedBox(height: 2),
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
      ],
    );
  }

  /// The six-month trend, which is itself the way into the ledger.
  Widget _fundTrend(
    BuildContext context,
    WidgetRef ref,
    AppLocalizations l10n,
  ) {
    return InsetGroup(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
      children: [
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            FundChart(
              range: '6m',
              compact: true,
              onTap: () => selectLedgerTab(ref),
            ),
            const SizedBox(height: 8),
            Text(
              l10n.homeFundChartCaption,
              style: Theme.of(context).textTheme.bodySmall,
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
/// resident always knows which home the numbers belong to. The top line of
/// the fund card.
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
    if (occupancy == null) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
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

/// The brand header: a gradient band with the logo and a bell, and [card]
/// lifted over its lower edge.
class _HomeHeader extends StatelessWidget {
  const _HomeHeader({required this.card});

  final Widget card;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final palette = LamToPalette.of(context);
    final dark = Theme.of(context).brightness == Brightness.dark;
    final top = MediaQuery.paddingOf(context).top;
    const white = Color(0xFFFFFFFF);
    final bandHeight = top + 150;
    return Stack(
      children: [
        Positioned(
          left: 0,
          right: 0,
          top: 0,
          height: bandHeight,
          child: ClipRRect(
            borderRadius: const BorderRadius.vertical(
              bottom: Radius.circular(28),
            ),
            child: DecoratedBox(
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                  colors: dark
                      ? const [Color(0xFF0B1E45), Color(0xFF1C2A4A)]
                      : const [LamToColors.brand, LamToColors.primary],
                ),
              ),
              // Soft light shapes, so the band reads as depth, not a flat fill.
              child: Stack(
                children: [
                  Positioned(
                    right: -60,
                    top: -40,
                    child: _Glow(size: 220, opacity: dark ? 0.05 : 0.10),
                  ),
                  Positioned(
                    left: -40,
                    bottom: -90,
                    child: _Glow(size: 180, opacity: dark ? 0.04 : 0.07),
                  ),
                ],
              ),
            ),
          ),
        ),
        Padding(
          padding: EdgeInsets.fromLTRB(16, top + 12, 16, 0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  Semantics(
                    header: true,
                    label: 'LÀM TỔ',
                    // The wordmark is a logo: it keeps its size at any text scale.
                    child: MediaQuery.withNoTextScaling(
                      child: const ExcludeSemantics(
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            BrandMark(size: 40),
                            SizedBox(width: 10),
                            Text(
                              'LÀM TỔ',
                              style: TextStyle(
                                color: white,
                                fontSize: 20,
                                fontWeight: FontWeight.w800,
                                letterSpacing: 1.2,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                  const Spacer(),
                  // Unread count lives on the Notifications tile below; one
                  // badge, announced once.
                  IconButton(
                    tooltip: l10n.notificationsTitle,
                    color: white,
                    style: IconButton.styleFrom(
                      backgroundColor: white.withValues(alpha: 0.14),
                    ),
                    icon: const Icon(Icons.notifications_none),
                    onPressed: () => Navigator.push(
                      context,
                      adaptivePageRoute(
                        builder: (_) => const NotificationsScreen(),
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 20),
              DecoratedBox(
                decoration: BoxDecoration(
                  color: palette.surface,
                  borderRadius: BorderRadius.circular(18),
                  boxShadow: dark
                      ? null
                      : const [
                          BoxShadow(
                            color: Color(0x24003081),
                            blurRadius: 24,
                            offset: Offset(0, 8),
                          ),
                        ],
                ),
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(18, 16, 18, 16),
                  child: card,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _Glow extends StatelessWidget {
  const _Glow({required this.size, required this.opacity});

  final double size;
  final double opacity;

  @override
  Widget build(BuildContext context) => Container(
    width: size,
    height: size,
    decoration: BoxDecoration(
      shape: BoxShape.circle,
      color: const Color(0xFFFFFFFF).withValues(alpha: opacity),
    ),
  );
}

class _Shortcut {
  const _Shortcut({
    required this.icon,
    required this.label,
    required this.onTap,
    this.unreadCount = 0,
  });

  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final int unreadCount;
}

/// Where to go from Home: one row of labeled tiles on a single surface.
class _ShortcutGrid extends StatelessWidget {
  const _ShortcutGrid({required this.tiles});

  final List<_Shortcut> tiles;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final palette = LamToPalette.of(context);
    return Material(
      color: palette.surface,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
      clipBehavior: Clip.antiAlias,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 4),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            for (final tile in tiles)
              Expanded(
                child: InkWell(
                  borderRadius: BorderRadius.circular(14),
                  onTap: tile.onTap,
                  child: Padding(
                    padding: const EdgeInsets.symmetric(
                      vertical: 10,
                      horizontal: 2,
                    ),
                    child: Column(
                      children: [
                        Builder(
                          builder: (context) {
                            final well = Container(
                              width: 48,
                              height: 48,
                              decoration: BoxDecoration(
                                color: palette.primarySoft,
                                borderRadius: BorderRadius.circular(14),
                              ),
                              child: Icon(
                                tile.icon,
                                size: 24,
                                color: palette.primary,
                              ),
                            );
                            if (tile.unreadCount == 0) return well;
                            return Semantics(
                              label: l10n.notificationsUnreadCount(
                                tile.unreadCount,
                              ),
                              child: ExcludeSemantics(
                                child: Badge.count(
                                  count: tile.unreadCount,
                                  child: well,
                                ),
                              ),
                            );
                          },
                        ),
                        const SizedBox(height: 8),
                        Text(
                          tile.label,
                          textAlign: TextAlign.center,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: Theme.of(context).textTheme.labelMedium
                              ?.copyWith(fontWeight: FontWeight.w600),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
