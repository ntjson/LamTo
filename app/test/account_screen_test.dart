import 'package:built_collection/built_collection.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto/core/providers.dart';
import 'package:lamto/core/token_store.dart';
import 'package:lamto/features/account/account_screen.dart';
import 'package:lamto/features/auth/auth_repository.dart';
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
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

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
      'preference PATCH failure reverts switch and shows resident SnackBar',
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
    // Exception('boom') → Failure.fromObject → server_error → l10n.errServer
    expect(
      find.text(
          'Đã có lỗi từ phía hệ thống. Thao tác có thể chưa được lưu. Vui lòng thử lại sau.'),
      findsOneWidget,
    );
    expect(find.byType(SnackBar), findsOneWidget);
  });
}
