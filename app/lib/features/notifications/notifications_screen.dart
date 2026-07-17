import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/failure.dart';
import '../../core/providers.dart';
import '../../l10n/app_localizations.dart';
import '../ledger/ledger_detail_screen.dart';
import '../reports/issue_detail_screen.dart';
import '../reports/reports_repository.dart' show cursorFromNext;
import '../transparency/transparency_repository.dart';
import 'deep_link.dart';

class NotificationsController extends AsyncNotifier<List<NotificationFeed>> {
  String? _nextCursor;
  bool get hasMore => _nextCursor != null;

  @override
  Future<List<NotificationFeed>> build() async {
    ref.watch(occupancyScopedProviders);
    final page =
        await ref.read(transparencyRepositoryProvider).listNotifications();
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
        NotificationsController.new);

/// Notifications feed (spec 6.3(8)): list, mark-read, allowlisted deep links.
class NotificationsScreen extends ConsumerWidget {
  const NotificationsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context)!;
    final notices = ref.watch(notificationsProvider);
    final controller = ref.read(notificationsProvider.notifier);

    return Scaffold(
      appBar: AppBar(title: Text(l10n.notificationsTitle)),
      body: switch (notices) {
        AsyncData(:final value) when value.isEmpty =>
          Center(child: Text(l10n.notificationsEmpty)),
        AsyncData(:final value) => RefreshIndicator.adaptive(
            onRefresh: () => ref.refresh(notificationsProvider.future),
            child: ListView(
              children: [
                for (final notice in value)
                  ListTile(
                    minTileHeight: 64,
                    leading: Icon(
                      notice.readAt == null
                          ? Icons.circle_notifications
                          : Icons.notifications_none,
                    ),
                    title: Text(
                      notice.subject,
                      style: notice.readAt == null
                          ? const TextStyle(fontWeight: FontWeight.w600)
                          : null,
                    ),
                    subtitle: Text(notice.body,
                        maxLines: 2, overflow: TextOverflow.ellipsis),
                    onTap: () => _open(context, controller, notice),
                  ),
                if (controller.hasMore)
                  Padding(
                    padding: const EdgeInsets.all(16),
                    child: OutlinedButton(
                      onPressed: controller.loadMore,
                      child: Text(l10n.notificationsLoadMore),
                    ),
                  ),
              ],
            ),
          ),
        AsyncError(:final error) => Center(
            child: Text(failureMessage(Failure.fromObject(error), l10n)),
          ),
        _ => const Center(child: CircularProgressIndicator.adaptive()),
      },
    );
  }

  void _open(BuildContext context, NotificationsController controller,
      NotificationFeed notice) {
    controller.markRead(notice);
    switch (parseEventKey(notice.eventKey)) {
      case DeepLinkReport(:final id):
        Navigator.push(
          context,
          MaterialPageRoute(builder: (_) => IssueDetailScreen(reportId: id)),
        );
      case DeepLinkLedger(:final id):
        Navigator.push(
          context,
          MaterialPageRoute(builder: (_) => LedgerDetailScreen(entryId: id)),
        );
      case DeepLinkFeed():
        break; // already on the feed
    }
  }
}
