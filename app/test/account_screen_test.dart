import 'package:built_collection/built_collection.dart';
import 'package:flutter/cupertino.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto/core/providers.dart';
import 'package:lamto/core/token_store.dart';
import 'package:lamto/features/account/account_screen.dart';
import 'package:lamto/features/auth/auth_repository.dart';
import 'package:lamto/features/reports/reports_repository.dart';
import 'package:lamto/features/shell/home_shell.dart';
import 'package:lamto/features/transparency/transparency_repository.dart';
import 'package:lamto/l10n/app_localizations.dart';
import 'package:lamto_api/lamto_api.dart';
import 'package:shared_preferences/shared_preferences.dart';

Me _me() => Me(
      (b) => b
        ..displayName = 'Cư dân A'
        ..email = 'r@example.com'
        ..occupancies = ListBuilder<Occupancy>([
          Occupancy((o) => o
            ..id = 1
            ..unitLabel = 'B-1204'
            ..buildingName = 'Tòa A'),
          Occupancy((o) => o
            ..id = 2
            ..unitLabel = 'C-101'
            ..buildingName = 'Tòa C'),
        ])
        ..notificationPreferences = ListBuilder<NotificationPreference>([
          NotificationPreference((p) => p
            ..eventCode = 'ledger.publication'
            ..emailEnabled = true
            ..pushEnabled = false),
        ]),
    );

class _FakeAuth implements AuthRepository {
  @override
  Future<Me> fetchMe() async => _me();
  @override
  Future<String> login(String i, String p) async => 'tok';
  @override
  Future<void> logout() async {}
  @override
  Future<void> logoutAll() async {}
}

/// Bootstrap reads secure storage first; give it an in-memory token.
class _FakeStore implements TokenStore {
  String? token = 'knox-token';
  @override
  Future<void> clear() async => token = null;
  @override
  Future<String?> read() async => token;
  @override
  Future<void> write(String value) async => token = value;
}

class _FakeTransparency implements TransparencyRepository {
  final patches = <(String, bool?, bool?)>[];

  @override
  Future<List<NotificationPreference>> updatePreference({
    required String eventCode,
    bool? emailEnabled,
    bool? pushEnabled,
  }) async {
    patches.add((eventCode, emailEnabled, pushEnabled));
    return [];
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

/// Preference PATCH fails so the account screen must revert + surface error.
/// Fund/ledger still succeed so HomeShell other tabs do not block Account.
class _ThrowingTransparency implements TransparencyRepository {
  @override
  Future<List<NotificationPreference>> updatePreference({
    required String eventCode,
    bool? emailEnabled,
    bool? pushEnabled,
  }) async {
    throw Exception('boom');
  }

  @override
  Future<FundSummary> fetchFundSummary() async => FundSummary(
        (b) => b
          ..balanceVnd = 0
          ..periodDays = 30
          ..periodInflowsVnd = 0
          ..periodOutflowsVnd = 0,
      );

  @override
  Future<PaginatedLedgerEntryListList> listLedger(
          {String? cursor, int? year, int? month}) async =>
      PaginatedLedgerEntryListList(
        (b) => b..results = ListBuilder<LedgerEntryList>(),
      );

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class _EmptyReports implements ReportsRepository {
  @override
  Future<PaginatedReportSummaryList> listReports({String? cursor}) async =>
      PaginatedReportSummaryList(
        (b) => b..results = ListBuilder<ReportSummary>(),
      );

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

/// Exception('boom') → Failure.fromObject → server_error → l10n.errServer (vi).
const _errServerVi =
    'Đã có lỗi từ phía hệ thống. Thao tác có thể chưa được lưu. Vui lòng thử lại sau.';

void main() {
  testWidgets('shows profile, occupancies, preference toggles; patches a flip',
      (tester) async {
    SharedPreferences.setMockInitialValues({}); // occupancy store backing
    final repo = _FakeTransparency();
    await tester.pumpWidget(ProviderScope(
      overrides: [
        tokenStoreProvider.overrideWithValue(_FakeStore()),
        authRepositoryProvider.overrideWithValue(_FakeAuth()),
        transparencyRepositoryProvider.overrideWithValue(repo),
      ],
      child: MaterialApp(
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        locale: const Locale('vi'),
        home: const Scaffold(body: AccountScreen()),
      ),
    ));
    await tester.pumpAndSettle();

    expect(find.text('Cư dân A'), findsOneWidget);
    expect(find.text('Tòa A · B-1204'), findsOneWidget);
    expect(find.text('Tòa C · C-101'), findsOneWidget);
    expect(find.text('Khoản chi được công bố'), findsOneWidget);

    // Push toggle for ledger.publication starts OFF (from /me row); flip it.
    final pushSwitches = find.byType(Switch);
    expect(pushSwitches, findsWidgets);
    // The screen keys each switch: 'push_ledger.publication'.
    await tester.tap(find.byKey(const Key('push_ledger.publication')));
    await tester.pumpAndSettle();
    expect(repo.patches.single, ('ledger.publication', null, true));
    expect(find.text('Đăng xuất'), findsOneWidget);
    expect(find.text('Đăng xuất mọi thiết bị'), findsOneWidget);
  });

  testWidgets(
      'preference PATCH failure reverts switch and shows inline resident error',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    await tester.pumpWidget(ProviderScope(
      overrides: [
        tokenStoreProvider.overrideWithValue(_FakeStore()),
        authRepositoryProvider.overrideWithValue(_FakeAuth()),
        transparencyRepositoryProvider
            .overrideWithValue(_ThrowingTransparency()),
      ],
      child: MaterialApp(
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        locale: const Locale('vi'),
        home: const Scaffold(body: AccountScreen()),
      ),
    ));
    await tester.pumpAndSettle();

    final pushKey = find.byKey(const Key('push_ledger.publication'));
    // Server pref starts pushEnabled = false.
    expect(tester.widget<Switch>(pushKey).value, isFalse);

    await tester.tap(pushKey);
    // Optimistic flip then async PATCH fail + revert.
    await tester.pump();
    await tester.pumpAndSettle();

    expect(tester.widget<Switch>(pushKey).value, isFalse);
    // Inline error — not SnackBar (works under Cupertino shell too).
    expect(find.byKey(const Key('account_pref_error')), findsOneWidget);
    expect(find.text(_errServerVi), findsOneWidget);
    expect(find.byType(SnackBar), findsNothing);
  });

  testWidgets(
      'iOS HomeShell CupertinoPageScaffold: PATCH fail shows visible error',
      (tester) async {
    // Production iOS path: CupertinoTabScaffold + CupertinoPageScaffold has no
    // Material ScaffoldMessenger. Inline error must still appear.
    final previous = debugDefaultTargetPlatformOverride;
    debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
    try {
      SharedPreferences.setMockInitialValues({});
      await tester.pumpWidget(ProviderScope(
        overrides: [
          tokenStoreProvider.overrideWithValue(_FakeStore()),
          authRepositoryProvider.overrideWithValue(_FakeAuth()),
          transparencyRepositoryProvider
              .overrideWithValue(_ThrowingTransparency()),
          reportsRepositoryProvider.overrideWithValue(_EmptyReports()),
        ],
        child: MaterialApp(
          // MaterialApp still supplies Theme/l10n; body is real HomeShell.
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          locale: const Locale('vi'),
          home: const HomeShell(),
        ),
      ));
      await tester.pumpAndSettle();

      // HomeShell iOS uses Cupertino chrome, not Material Scaffold.
      expect(find.byType(CupertinoTabScaffold), findsOneWidget);
      expect(find.byType(CupertinoPageScaffold), findsWidgets);
      // No Material Scaffold wrapping tab bodies on iOS.
      expect(find.byType(Scaffold), findsNothing);

      // Switch to Account tab (index 4).
      await tester.tap(find.text('Tài khoản'));
      await tester.pumpAndSettle();

      expect(find.byType(AccountScreen), findsOneWidget);

      final pushKey = find.byKey(const Key('push_ledger.publication'));
      expect(tester.widget<Switch>(pushKey).value, isFalse);

      await tester.tap(pushKey);
      await tester.pump();
      await tester.pumpAndSettle();

      // Toggle reverted + resident-visible inline error (no SnackBar host).
      expect(tester.widget<Switch>(pushKey).value, isFalse);
      expect(find.byKey(const Key('account_pref_error')), findsOneWidget);
      expect(find.text(_errServerVi), findsOneWidget);
      expect(tester.takeException(), isNull);
    } finally {
      debugDefaultTargetPlatformOverride = previous;
    }
  });
}
