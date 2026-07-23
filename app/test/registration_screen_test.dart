import 'dart:async';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto/core/providers.dart';
import 'package:lamto/core/token_store.dart';
import 'package:lamto/features/auth/login_screen.dart';
import 'package:lamto/features/auth/registration_screen.dart';
import 'package:lamto/features/auth/registration_status_store.dart';
import 'package:lamto/l10n/app_localizations.dart';

class _Store implements TokenStore {
  _Store([this.value]);
  String? value;

  @override
  Future<void> clear() async => value = null;
  @override
  Future<String?> read() async => value;
  @override
  Future<void> write(String value) async => this.value = value;
}

class _Adapter implements HttpClientAdapter {
  _Adapter(this.handler);
  final FutureOr<Map<String, Object?>> Function(RequestOptions) handler;
  int statusCalls = 0;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    if (options.path.endsWith('/status')) statusCalls++;
    final response = await handler(options);
    return ResponseBody.fromString(
      response.remove('_body')! as String,
      response.remove('_status')! as int,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

Map<String, Object?> _json(String body, [int status = 200]) => {
  '_body': body,
  '_status': status,
};

const _options = '''[
  {"id":1,"name":"Tower A","units":[{"id":11,"label":"A-101"}]},
  {"id":2,"name":"Tower B","units":[{"id":21,"label":"B-201"}]}
]''';

Widget _app(_Store store, _Adapter adapter, {Widget? home}) {
  final dio = Dio(BaseOptions(baseUrl: 'https://example.test'))
    ..httpClientAdapter = adapter;
  return ProviderScope(
    overrides: [
      dioProvider.overrideWithValue(dio),
      registrationTokenStoreProvider.overrideWithValue(store),
    ],
    child: MaterialApp(
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      locale: const Locale('en'),
      home: home ?? const LoginScreen(),
    ),
  );
}

void main() {
  testWidgets('login offers registration', (tester) async {
    final store = _Store();
    final adapter = _Adapter((_) => _json(_options));
    await tester.pumpWidget(_app(store, adapter));

    await tester.tap(find.text('Register as a resident'));
    await tester.pumpAndSettle();

    expect(find.byType(RegistrationScreen), findsOneWidget);
  });

  testWidgets('stored status opens directly and refreshes once', (
    tester,
  ) async {
    final store = _Store('{"token":"secret","phone":"0901"}');
    final adapter = _Adapter((request) {
      expect(request.headers['X-Registration-Status-Token'], 'secret');
      return _json(
        '{"status":"PENDING","phone":"0901","building":"Tower A","unit":"A-101"}',
      );
    });
    await tester.pumpWidget(_app(store, adapter));
    await tester.tap(find.text('Register as a resident'));
    await tester.pumpAndSettle();

    expect(find.text('Tower A · A-101'), findsOneWidget);
    expect(adapter.statusCalls, 1);
  });

  testWidgets('building filters units and changing it resets unit', (
    tester,
  ) async {
    final adapter = _Adapter((_) => _json(_options));
    await tester.pumpWidget(
      _app(_Store(), adapter, home: const RegistrationScreen()),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('registration_building')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Tower A').last);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('registration_unit')));
    await tester.pumpAndSettle();
    expect(find.text('A-101'), findsWidgets);
    expect(find.text('B-201'), findsNothing);
    await tester.tap(find.text('A-101').last);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('registration_building')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Tower B').last);
    await tester.pumpAndSettle();
    expect(
      tester
          .widget<DropdownButtonFormField<int>>(
            find.byKey(const Key('registration_unit')),
          )
          .initialValue,
      isNull,
    );
  });

  testWidgets('validates required fields while email remains optional', (
    tester,
  ) async {
    var submitted = false;
    final adapter = _Adapter((request) {
      if (request.path.endsWith('/options')) return _json(_options);
      submitted = true;
      return _json(
        '{"status":"PENDING","status_token":"new","phone":"0901"}',
        201,
      );
    });
    await tester.pumpWidget(
      _app(_Store(), adapter, home: const RegistrationScreen()),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('Submit request'));
    await tester.pump();
    expect(find.text('Required'), findsNWidgets(5));
    expect(submitted, isFalse);

    await tester.enterText(
      find.byKey(const Key('registration_name')),
      'Resident A',
    );
    await tester.enterText(find.byKey(const Key('registration_phone')), '0901');
    await tester.enterText(
      find.byKey(const Key('registration_password')),
      'secret123',
    );
    await tester.tap(find.byKey(const Key('registration_building')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Tower A').last);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('registration_unit')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('A-101').last);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Submit request'));
    await tester.pumpAndSettle();
    expect(submitted, isTrue);
  });

  testWidgets('successful submit stores normalized phone and shows pending', (
    tester,
  ) async {
    final store = _Store();
    final adapter = _Adapter((request) {
      if (request.path.endsWith('/options')) return _json(_options);
      if (request.path.endsWith('/status')) {
        return _json(
          '{"status":"PENDING","phone":"+84901","building":"Tower A","unit":"A-101"}',
        );
      }
      return _json(
        '{"status":"PENDING","status_token":"new-token","phone":"+84901"}',
        201,
      );
    });
    await tester.pumpWidget(
      _app(store, adapter, home: const RegistrationScreen()),
    );
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('registration_name')),
      'Resident A',
    );
    await tester.enterText(find.byKey(const Key('registration_phone')), '0901');
    await tester.enterText(
      find.byKey(const Key('registration_password')),
      'secret123',
    );
    await tester.tap(find.byKey(const Key('registration_building')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Tower A').last);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('registration_unit')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('A-101').last);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Submit request'));
    await tester.pumpAndSettle();

    expect(
      await RegistrationStatusStore(store).read(),
      const RegistrationStatusSecret(token: 'new-token', phone: '+84901'),
    );
    expect(find.text('Registration pending'), findsOneWidget);
  });

  testWidgets('pending refreshes only on open, resume, and manual action', (
    tester,
  ) async {
    final adapter = _Adapter(
      (_) => _json(
        '{"status":"PENDING","phone":"0901","building":"Tower A","unit":"A-101"}',
      ),
    );
    await tester.pumpWidget(
      _app(
        _Store('{"token":"secret","phone":"0901"}'),
        adapter,
        home: const RegistrationScreen(),
      ),
    );
    await tester.pumpAndSettle();
    expect(adapter.statusCalls, 1);

    await tester.pump(const Duration(minutes: 5));
    expect(adapter.statusCalls, 1);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    expect(adapter.statusCalls, 2);
    await tester.tap(find.text('Refresh'));
    await tester.pumpAndSettle();
    expect(adapter.statusCalls, 3);
  });

  testWidgets('rejected shows reason and clears secret for a new request', (
    tester,
  ) async {
    final store = _Store('{"token":"secret","phone":"0901"}');
    final adapter = _Adapter(
      (_) => _json(
        '{"status":"REJECTED","phone":"0901","building":"Tower A","unit":"A-101","rejection_reason":"Lease could not be verified"}',
      ),
    );
    await tester.pumpWidget(
      _app(store, adapter, home: const RegistrationScreen()),
    );
    await tester.pumpAndSettle();
    expect(find.text('Lease could not be verified'), findsOneWidget);

    await tester.tap(find.text('Submit a new request'));
    await tester.pumpAndSettle();
    expect(store.value, isNull);
    expect(find.byKey(const Key('registration_name')), findsOneWidget);
  });

  testWidgets('approved clears secret and prefills only login phone', (
    tester,
  ) async {
    final store = _Store('{"token":"secret","phone":"0901"}');
    final adapter = _Adapter(
      (_) => _json(
        '{"status":"APPROVED","phone":"0901","building":"Tower A","unit":"A-101"}',
      ),
    );
    await tester.pumpWidget(
      _app(store, adapter, home: const RegistrationScreen()),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Continue to sign in'));
    await tester.pumpAndSettle();

    expect(store.value, isNull);
    final fields = tester
        .widgetList<TextField>(find.byType(TextField))
        .toList();
    expect(fields[0].controller!.text, '0901');
    expect(fields[1].controller!.text, isEmpty);
  });

  testWidgets('expired clears secret and offers a new request', (tester) async {
    final store = _Store('{"token":"secret","phone":"0901"}');
    final adapter = _Adapter(
      (_) => _json(
        '{"status":"EXPIRED","phone":"0901","building":"Tower A","unit":"A-101"}',
      ),
    );
    await tester.pumpWidget(
      _app(store, adapter, home: const RegistrationScreen()),
    );
    await tester.pumpAndSettle();

    expect(store.value, isNull);
    expect(find.text('This registration request has expired.'), findsOneWidget);
    expect(find.text('Submit a new request'), findsOneWidget);
  });
}
