import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/adaptive_buttons.dart';
import '../../core/adaptive_page_route.dart';
import '../../core/error_retry.dart';
import '../../core/load_more_button.dart';
import '../../core/providers.dart';
import '../../l10n/app_localizations.dart';
import '../../theme.dart';
import '../../widgets/grouped.dart';
import '../shell/tab_page.dart';
import '../auth/session_controller.dart';
import 'issue_detail_screen.dart';
import 'report_form_screen.dart';
import 'reports_repository.dart';

/// Plain-language status labels (DESIGN.md: color never alone).
String reportStatusLabel(StatusEnum status, AppLocalizations l10n) =>
    switch (status) {
      StatusEnum.SUBMITTED => l10n.statusSubmitted,
      StatusEnum.IN_REVIEW => l10n.statusInReview,
      StatusEnum.NEEDS_INFO => l10n.statusNeedsInfo,
      StatusEnum.DECLINED => l10n.statusDeclined,
      StatusEnum.IN_PROGRESS => l10n.statusInProgress,
      StatusEnum.PROPOSED => l10n.statusProposed,
      StatusEnum.COMPLETED => l10n.statusCompleted,
      StatusEnum.CLOSED => l10n.statusClosed,
      _ => status.name,
    };

bool isActiveReportStatus(StatusEnum status) =>
    status != StatusEnum.DECLINED &&
    status != StatusEnum.COMPLETED &&
    status != StatusEnum.CLOSED;

StatusTone reportStatusTone(StatusEnum status) => switch (status) {
  StatusEnum.COMPLETED || StatusEnum.CLOSED => StatusTone.success,
  StatusEnum.DECLINED || StatusEnum.NEEDS_INFO => StatusTone.warning,
  _ => StatusTone.info,
};

/// Cursor-paginated list of **all** reports submitted by the authenticated
/// user across units (user-global; amendment 12). Not filtered to the
/// selected occupancy. Rebuilds when session identity changes so a later
/// sign-in cannot show the previous user's cached list.
class MyReportsController extends AsyncNotifier<List<ReportSummary>> {
  String? _nextCursor;
  bool get hasMore => _nextCursor != null;

  @override
  Future<List<ReportSummary>> build() async {
    // Session identity: drop cross-user cache on logout / re-login.
    ref.watch(sessionControllerProvider);
    ref.watch(occupancyScopedProviders);
    final page = await ref.read(reportsRepositoryProvider).listReports();
    _nextCursor = cursorFromNext(page.next);
    return page.results.toList();
  }

  Future<void> loadMore() async {
    final cursor = _nextCursor;
    final current = state.value;
    if (cursor == null || current == null) return;
    final page = await ref
        .read(reportsRepositoryProvider)
        .listReports(cursor: cursor);
    // A refresh may have replaced the list while this page was in flight;
    // appending onto the stale snapshot would clobber the fresh state.
    if (!identical(state.value, current)) return;
    _nextCursor = cursorFromNext(page.next);
    state = AsyncData([...current, ...page.results]);
  }
}

final myReportsProvider =
    AsyncNotifierProvider<MyReportsController, List<ReportSummary>>(
      MyReportsController.new,
    );

/// Issues tab body: user-global "My issues" / "Việc của tôi" list with
/// semantic status chips, pull-to-refresh, and load-more (spec §6.3(5)).
///
/// Scope is **user-global** (amendment 12): every report the authenticated
/// resident submitted, across all units — not limited to the currently
/// selected occupancy.
class MyIssuesScreen extends ConsumerWidget {
  const MyIssuesScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context)!;
    final reports = ref.watch(myReportsProvider);
    final slivers = switch (reports) {
      AsyncData(:final value) when value.isEmpty => [
        SliverFillRemaining(
          hasScrollBody: false,
          child: Center(
            child: EmptyState(
              icon: Icons.inbox_outlined,
              message: l10n.issuesEmpty,
              action: AdaptiveFilledButton(
                onPressed: () => openReportForm(context),
                child: Text(l10n.tabReport),
              ),
            ),
          ),
        ),
      ],
      // Builder-based so a long paginated history lays out lazily.
      AsyncData(:final value) => [
        SliverPadding(
          padding: tabContentPadding,
          sliver: SliverList.builder(
            itemCount: value.length,
            itemBuilder: (context, i) => GroupedListItem(
              isFirst: i == 0,
              isLast: i == value.length - 1,
              child: _ReportTile(report: value[i]),
            ),
          ),
        ),
        if (ref.read(myReportsProvider.notifier).hasMore)
          SliverToBoxAdapter(
            child: LoadMoreButton(
              label: l10n.issuesLoadMore,
              onLoadMore: ref.read(myReportsProvider.notifier).loadMore,
            ),
          ),
      ],
      AsyncError(:final error) => [
        SliverToBoxAdapter(
          child: ErrorRetry(
            error: error,
            onRetry: () => ref.invalidate(myReportsProvider),
          ),
        ),
      ],
      _ => [
        const SliverToBoxAdapter(
          child: Padding(
            padding: EdgeInsets.only(top: 48),
            child: Center(child: CircularProgressIndicator.adaptive()),
          ),
        ),
      ],
    };
    // Body-only: shell owns the tab chrome; Material provides ListTile ink.
    return Material(
      color: Colors.transparent,
      child: TabPage(
        title: l10n.issuesTitle,
        onRefresh: () async {
          // The error branch below is the retry surface; a failed refresh
          // must not escape as an unhandled zone error.
          ref.invalidate(myReportsProvider);
          try {
            await ref.read(myReportsProvider.future);
          } catch (_) {}
        },
        slivers: slivers,
      ),
    );
  }
}

class _ReportTile extends StatelessWidget {
  const _ReportTile({required this.report});

  final ReportSummary report;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final muted = Theme.of(context).textTheme.bodySmall;
    return ListTile(
      minTileHeight: 72,
      contentPadding: const EdgeInsets.fromLTRB(16, 4, 12, 4),
      title: Text(report.text, maxLines: 2, overflow: TextOverflow.ellipsis),
      subtitle: Padding(
        padding: const EdgeInsets.only(top: 4),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              report.locationPathSnapshot,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: muted,
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                StatusChip(
                  tone: reportStatusTone(report.status),
                  label: reportStatusLabel(report.status, l10n),
                ),
                if (report.isPrivate)
                  StatusChip(
                    tone: StatusTone.info,
                    icon: Icons.lock_outline,
                    label: l10n.privateBadge,
                  ),
              ],
            ),
          ],
        ),
      ),
      trailing: Icon(
        Icons.chevron_right,
        color: LamToPalette.of(context).muted.withValues(alpha: 0.6),
      ),
      onTap: () => Navigator.push(
        context,
        adaptivePageRoute(
          builder: (_) => IssueDetailScreen(reportId: report.id),
        ),
      ),
    );
  }
}
