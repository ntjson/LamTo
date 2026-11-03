@Tags(['web'])
library;

import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/app.dart';
import 'package:lamto/core/failure.dart';
import 'package:lamto/core/providers.dart';
import 'package:lamto/core/token_store.dart';
import 'package:lamto/features/auth/login_screen.dart';
import 'package:lamto/l10n/app_localizations.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Answers every request with `{}` and remembers where each one went.
class _CapturingAdapter implements HttpClientAdapter {
  final requested = <Uri>[];

  @override
  void close({bool force = false}) {}

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    requested.add(options.uri);
    return ResponseBody.fromString(
      jsonEncode({}),
      200,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }
}

const _savedOverride = 'https://saved-tunnel.trycloudflare.com';

Widget _screen(Widget home) => ProviderScope(
  overrides: [tokenStoreProvider.overrideWithValue(TokenStore.memory())],
  child: MaterialApp(
    localizationsDelegates: AppLocalizations.localizationsDelegates,
    supportedLocales: AppLocalizations.supportedLocales,
    locale: const Locale('vi'),
    home: home,
  ),
);

final _overrideTile = find.byKey(const Key('api_base_url_tile'));

void main() {
  group('normalizeApiBaseUrl', () {
    test('accepts https tunnel and strips trailing slash', () {
      expect(
        normalizeApiBaseUrl(
          ' https://jurisdiction-photographer-absence-mystery.trycloudflare.com/ ',
        ),
        'https://jurisdiction-photographer-absence-mystery.trycloudflare.com',
      );
    });

    test('accepts emulator host', () {
      expect(
        normalizeApiBaseUrl('http://10.0.2.2:8000'),
        'http://10.0.2.2:8000',
      );
    });

    test('rejects empty and non-http schemes', () {
      expect(normalizeApiBaseUrl(''), isNull);
      expect(normalizeApiBaseUrl('ftp://x'), isNull);
      expect(normalizeApiBaseUrl('not a url'), isNull);
    });
  });

  test('the API is called at the page origin on the web, at the saved override '
      'on native', () async {
    SharedPreferences.setMockInitialValues({
      kApiBaseUrlPrefsKey: _savedOverride,
    });
    final container = ProviderContainer(
      overrides: [tokenStoreProvider.overrideWithValue(TokenStore.memory())],
    );
    addTearDown(container.dispose);
    container.read(apiBaseUrlProvider);
    await Future<void>.delayed(Duration.zero); // saved override hydrates

    final adapter = _CapturingAdapter();
    final dio = container.read(dioProvider)..httpClientAdapter = adapter;
    await dio.get<Object?>('/api/v1/me/');

    final requested = adapter.requested.single;
    if (kIsWeb) {
      // The origin this page was loaded from, never a build-time address,
      // so a new tunnel hostname needs no rebuild (ADR 0009).
      expect(requested.origin, Uri.base.origin);
    } else {
      expect(requested.origin, _savedOverride);
    }
    expect(requested.path, '/api/v1/me/');
  });

  testWidgets('the login screen offers the API address override only on '
      'native', (tester) async {
    SharedPreferences.setMockInitialValues({});
    await tester.pumpWidget(_screen(const LoginScreen()));
    await tester.pumpAndSettle();

    expect(_overrideTile, kIsWeb ? findsNothing : findsOneWidget);
  });

  testWidgets('the bootstrap error screen offers the API address override '
      'only on native', (tester) async {
    SharedPreferences.setMockInitialValues({});
    await tester.pumpWidget(
      _screen(
        BootstrapErrorScreen(
          failure: Failure(code: 'network_error'),
          onRetry: () {},
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Đăng xuất'), findsOneWidget);
    expect(_overrideTile, kIsWeb ? findsNothing : findsOneWidget);
  });
}
