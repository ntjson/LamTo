@Tags(['web'])
library;

import 'package:firebase_core_platform_interface/firebase_core_platform_interface.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/app.dart';
import 'package:lamto/core/providers.dart';
import 'package:lamto/core/token_store.dart';
import 'package:lamto/features/auth/auth_repository.dart';
import 'package:lamto_api/lamto_api.dart';
import 'package:plugin_platform_interface/plugin_platform_interface.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// The Firebase plugin, recording whether anything asked it to initialise.
/// On the web, initialising is what fetches the Firebase SDK scripts.
class _RecordingFirebase extends FirebasePlatform
    with MockPlatformInterfaceMixin {
  int initialiseCalls = 0;

  @override
  List<FirebaseAppPlatform> get apps => const [];

  @override
  Future<FirebaseAppPlatform> initializeApp({
    String? name,
    FirebaseOptions? options,
  }) async {
    initialiseCalls++;
    // As on a build without Firebase config: push degrades to a no-op.
    throw FirebaseException(plugin: 'core', message: 'not configured');
  }
}

class _NoSessionRepo implements AuthRepository {
  @override
  Future<String> login(String identifier, String password) async => 'x';
  @override
  Future<Me> fetchMe() async => throw StateError('none');
  @override
  Future<void> logout() async {}
  @override
  Future<void> logoutAll() async {}
}

void main() {
  testWidgets('Firebase is initialised for push on native, never on the web', (
    tester,
  ) async {
    final previous = FirebasePlatform.instance;
    final firebase = _RecordingFirebase();
    FirebasePlatform.instance = firebase;
    addTearDown(() => FirebasePlatform.instance = previous);
    SharedPreferences.setMockInitialValues({});

    // The real push wiring: the router asks push for the notification that
    // opened the app as soon as it mounts.
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          tokenStoreProvider.overrideWithValue(TokenStore.memory()),
          authRepositoryProvider.overrideWithValue(_NoSessionRepo()),
        ],
        child: const LamToApp(),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Đăng nhập'), findsWidgets);
    expect(firebase.initialiseCalls, kIsWeb ? 0 : 1);
  });
}
