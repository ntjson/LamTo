import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/failure.dart';
import '../../core/providers.dart';
import '../../l10n/app_localizations.dart';
import '../../theme.dart';
import '../auth/session_controller.dart';
import 'issue_detail_screen.dart';
import 'reports_repository.dart';

/// Plain-language status labels (DESIGN.md: color never alone).
String reportStatusLabel(String status, AppLocalizations l10n) =>
    switch (status) {
      'RESOLVED' => l10n.statusResolved,
      _ => l10n.statusOpen,
    };

/// Active = not resolved. API enum today is OPEN/RESOLVED (amendment A3).
bool isActiveReportStatus(String status) => status != 'RESOLVED';

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
    final page =
        await ref.read(reportsRepositoryProvider).listReports(cursor: cursor);
    _nextCursor = cursorFromNext(page.next);
    state = AsyncData([...current, ...page.results]);
  }
}

final myReportsProvider =
    AsyncNotifierProvider<MyReportsController, List<ReportSummary>>(
        MyReportsController.new);

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
    // Body-only: shell owns Scaffold/CupertinoPageScaffold chrome (no nested
    // AppBar). Material provides ListTile ink without a second scaffold.
    final title = Padding(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
      child: Text(
        l10n.issuesTitle,
        style: Theme.of(context).textTheme.titleLarge,
      ),
    );
    final body = switch (reports) {
      AsyncData(:final value) => RefreshIndicator.adaptive(
          onRefresh: () => ref.refresh(myReportsProvider.future),
          child: value.isEmpty
              ? ListView(
                  children: [
                    title,
                    const SizedBox(height: 120),
                    Center(child: Text(l10n.issuesEmpty)),
                  ],
                )
              : ListView(
                  children: [
                    title,
                    for (final report in value)
                      ListTile(
                        minTileHeight: 64,
                        title: Text(
                          report.text,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                        ),
                        subtitle: Text(
                          report.locationPathSnapshot,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                        trailing: Chip(
                          visualDensity: VisualDensity.compact,
                          // DESIGN.md success-bg / info-bg tokens.
                          backgroundColor: report.status == 'RESOLVED'
                              ? const Color(0xFFE7F6EE)
                              : const Color(0xFFEFF8FF),
                          label: Text(
                            reportStatusLabel(report.status, l10n),
                            style: TextStyle(
                              color: report.status == 'RESOLVED'
                                  ? LamToColors.success
                                  : LamToColors.info,
                            ),
                          ),
                        ),
                        onTap: () => Navigator.push(
                          context,
                          MaterialPageRoute(
                            builder: (_) =>
                                IssueDetailScreen(reportId: report.id),
                          ),
                        ),
                      ),
                    if (ref.read(myReportsProvider.notifier).hasMore)
                      Padding(
                        padding: const EdgeInsets.all(16),
                        child: OutlinedButton(
                          onPressed: () =>
                              ref.read(myReportsProvider.notifier).loadMore(),
                          child: Text(l10n.issuesLoadMore),
                        ),
                      ),
                  ],
                ),
        ),
      AsyncError(:final error) => ListView(
          children: [
            title,
            const SizedBox(height: 48),
            Center(child: Text(failureMessage(Failure.fromObject(error), l10n))),
          ],
        ),
      _ => ListView(
          children: [
            title,
            const SizedBox(height: 48),
            const Center(child: CircularProgressIndicator.adaptive()),
          ],
        ),
    };
    return Material(
      color: Theme.of(context).scaffoldBackgroundColor,
      child: body,
    );
  }
}
