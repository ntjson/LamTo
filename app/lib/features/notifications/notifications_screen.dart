import 'package:flutter/cupertino.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/adaptive_buttons.dart';
import '../../core/adaptive_page_route.dart';
import '../../core/adaptive_scaffold.dart';
import '../../core/error_retry.dart';
import '../../core/load_more_button.dart';
import '../../core/page_body.dart';
import '../../core/providers.dart';
import '../../l10n/app_localizations.dart';
import '../../theme.dart';
import '../../widgets/grouped.dart';
import '../bills/bill_detail_screen.dart';
import '../ledger/ledger_detail_screen.dart';
import '../reports/issue_detail_screen.dart';
import '../reports/reports_repository.dart' show cursorFromNext;
import '../shell/home_shell.dart';
import '../shell/tab_page.dart';
import '../transparency/transparency_repository.dart';
import 'deep_link.dart';

class NotificationsController extends AsyncNotifier<List<NotificationFeed>> {
  String? _nextCursor;
  bool get hasMore => _nextCursor != null;

  @override
  Future<List<NotificationFeed>> build() async {
    ref.watch(occupancyScopedProviders);
    final page = await ref
        .read(transparencyRepositoryProvider)
        .listNotifications();
    _nextCursor = cursorFromNext(page.next);
    return page.results.toList();
  }

  Future<void> loadMore() async {
    final cursor = _nextCursor;
    final current = state.value;
    if (cursor == null || current == null) return;
    final page = await ref
        .read(transparencyRepositoryProvider)
        .listNotifications(cursor: cursor);
    // A refresh may have replaced the list while this page was in flight;
    // appending onto the stale snapshot would clobber the fresh state.
    if (!identical(state.value, current)) return;
    _nextCursor = cursorFromNext(page.next);
    state = AsyncData([...current, ...page.results]);
  }

  /// Optimistic mark-read; the in-app feed is authoritative so a failed call
  /// simply leaves the row unread on next refresh.
  Future<void> markRead(NotificationFeed notice) async {
    if (notice.readAt != null) return;
    final current = state.value;
    if (current != null) {
      state = AsyncData([
        for (final row in current)
          row.id == notice.id
              ? row.rebuild((b) => b..readAt = DateTime.now().toUtc())
              : row,
      ]);
    }
    try {
      await ref
          .read(transparencyRepositoryProvider)
          .markNotificationRead(notice.id);
    } catch (_) {
      // Best-effort (spec 7.4: feed authoritative; no workflow blocks on it).
    }
  }
}

final notificationsProvider =
    AsyncNotifierProvider<NotificationsController, List<NotificationFeed>>(
      NotificationsController.new,
    );

Future<void> showNotificationDialog(
  BuildContext context,
  NotificationFeed notice,
) {
  if (defaultTargetPlatform == TargetPlatform.iOS) {
    return showCupertinoDialog<void>(
      context: context,
      builder: (context) => CupertinoAlertDialog(
        title: Text(notice.subject),
        content: Text(notice.body),
        actions: [
          CupertinoDialogAction(
            onPressed: () => Navigator.of(context).pop(),
            child: Text(MaterialLocalizations.of(context).closeButtonLabel),
          ),
        ],
      ),
    );
  }
  return showDialog<void>(
    context: context,
    builder: (context) => AlertDialog(
      scrollable: true,
      title: Text(notice.subject),
      content: Text(notice.body),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: Text(MaterialLocalizations.of(context).closeButtonLabel),
        ),
      ],
    ),
  );
}

final latestAnnouncementProvider =
    FutureProvider.autoDispose<NotificationFeed?>((ref) async {
      ref.watch(occupancyScopedProviders);
      final page = await ref
          .watch(transparencyRepositoryProvider)
          .listNotifications(eventCode: 'building.announcement', unread: true);
      return page.results.firstOrNull;
    });

/// Notifications feed (spec 6.3(8)): list, mark-read, allowlisted deep links.
class NotificationsScreen extends ConsumerWidget {
  const NotificationsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context)!;
    final notices = ref.watch(notificationsProvider);
    final controller = ref.read(notificationsProvider.notifier);

    return AdaptiveScaffold(
      title: l10n.notificationsTitle,
      body: PageBody(
        child: switch (notices) {
          AsyncData(:final value) => RefreshIndicator.adaptive(
            onRefresh: () async {
              // The error branch below is the retry surface; a failed refresh
              // must not escape as an unhandled zone error.
              ref.invalidate(notificationsProvider);
              try {
                await ref.read(notificationsProvider.future);
              } catch (_) {}
            },
            child: value.isEmpty
                ? ListView(
                    physics: const AlwaysScrollableScrollPhysics(),
                    children: [
                      const SizedBox(height: 80),
                      EmptyState(
                        icon: Icons.notifications_none,
                        message: l10n.notificationsEmpty,
                        action: AdaptiveOutlinedButton(
                          onPressed: () => Navigator.maybePop(context),
                          child: Text(
                            MaterialLocalizations.of(context).backButtonTooltip,
                          ),
                        ),
                      ),
                    ],
                  )
                // Builder-based so a long paginated feed lays out lazily.
                : ListView.builder(
                    physics: const AlwaysScrollableScrollPhysics(),
                    padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
                    itemCount: value.length + (controller.hasMore ? 1 : 0),
                    itemBuilder: (context, index) {
                      if (index == value.length) {
                        return LoadMoreButton(
                          label: l10n.notificationsLoadMore,
                          onLoadMore: controller.loadMore,
                        );
                      }
                      final notice = value[index];
                      return GroupedListItem(
                        isFirst: index == 0,
                        isLast: index == value.length - 1,
                        dividerIndent: 40,
                        child: _NoticeTile(
                          notice: notice,
                          onTap: () => _open(context, ref, controller, notice),
                        ),
                      );
                    },
                  ),
          ),
          AsyncError(:final error) => Center(
            child: ErrorRetry(
              error: error,
              onRetry: () => ref.invalidate(notificationsProvider),
            ),
          ),
          _ => const Center(child: CircularProgressIndicator.adaptive()),
        },
      ),
    );
  }

  Future<void> _open(
    BuildContext context,
    WidgetRef ref,
    NotificationsController controller,
    NotificationFeed notice,
  ) async {
    await controller.markRead(notice);
    ref.invalidate(latestAnnouncementProvider);
    ref.invalidate(notificationsProvider);
    if (!context.mounted) return;
    switch (parseEventKey(notice.eventKey)) {
      case DeepLinkReport(:final id):
        Navigator.push(
          context,
          adaptivePageRoute(builder: (_) => IssueDetailScreen(reportId: id)),
        );
      case DeepLinkLedger(:final id):
        selectLedgerTab(ref);
        Navigator.push(
          context,
          adaptivePageRoute(builder: (_) => LedgerDetailScreen(entryId: id)),
        );
      case DeepLinkFeed():
        await showNotificationDialog(context, notice);
      case DeepLinkBill(:final id):
        Navigator.push(
          context,
          adaptivePageRoute(builder: (_) => BillDetailScreen(billId: id)),
        );
    }
  }
}

/// One notice: an unread dot, the subject in full weight while unread, and
/// two lines of the body. The dot is visual only; the state word makes
/// unread audible.
class _NoticeTile extends StatelessWidget {
  const _NoticeTile({required this.notice, required this.onTap});

  final NotificationFeed notice;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final palette = LamToPalette.of(context);
    final unread = notice.readAt == null;
    return ListTile(
      minTileHeight: 68,
      contentPadding: const EdgeInsets.fromLTRB(12, 6, 16, 6),
      horizontalTitleGap: 8,
      leading: Semantics(
        label: unread ? l10n.notificationUnread : l10n.notificationRead,
        child: SizedBox(
          width: 20,
          child: unread
              ? Center(
                  child: Container(
                    width: 10,
                    height: 10,
                    decoration: BoxDecoration(
                      color: palette.primary,
                      shape: BoxShape.circle,
                    ),
                  ),
                )
              : null,
        ),
      ),
      title: Text(
        notice.subject,
        style: unread ? const TextStyle(fontWeight: FontWeight.w600) : null,
      ),
      subtitle: Text(notice.body, maxLines: 2, overflow: TextOverflow.ellipsis),
      onTap: onTap,
    );
  }
}
