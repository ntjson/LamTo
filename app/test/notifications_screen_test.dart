import 'package:built_collection/built_collection.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto/features/notifications/notifications_screen.dart';
import 'package:lamto/features/transparency/transparency_repository.dart';
import 'package:lamto/l10n/app_localizations.dart';
import 'package:lamto_api/lamto_api.dart';

NotificationFeed _notice(int id, {String? eventKey, DateTime? readAt}) =>
    NotificationFeed(
      (b) => b
        ..id = id
        ..eventCode = 'ledger.publication'
        ..eventKey = eventKey ?? 'ledger.publication:entry:42'
        ..subject = 'Khoản chi mới'
        ..body = 'Một khoản chi vừa được công bố.'
        ..createdAt = DateTime.utc(2026, 7, 15)
        ..readAt = readAt,
    );

class _FakeRepo implements TransparencyRepository {
  final read = <int>[];

  @override
  Future<PaginatedNotificationFeedList> listNotifications(
          {String? cursor}) async =>
      PaginatedNotificationFeedList(
        (b) => b..results = ListBuilder<NotificationFeed>([_notice(9)]),
      );

  @override
  Future<void> markNotificationRead(int id) async => read.add(id);

  @override
  Future<LedgerEntryDetail> fetchLedgerEntry(int id) async =>
      throw StateError('detail fetch not needed for this test');

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  testWidgets('lists notices; tap marks read and deep-links to ledger detail',
      (tester) async {
    final repo = _FakeRepo();
    await tester.pumpWidget(ProviderScope(
      overrides: [transparencyRepositoryProvider.overrideWithValue(repo)],
      child: MaterialApp(
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        locale: const Locale('vi'),
        home: const NotificationsScreen(),
      ),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Khoản chi mới'), findsOneWidget);

    await tester.tap(find.text('Khoản chi mới'));
    await tester.pump(); // navigation begins; detail fetch may error (fine)
    expect(repo.read, [9]);
    // Landed on the pushed ledger detail scaffold (its own AppBar title).
    await tester.pumpAndSettle();
    expect(find.text('Sổ quỹ tòa nhà'), findsOneWidget);
  });
}
