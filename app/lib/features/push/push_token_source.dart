import 'dart:async';
import 'dart:io' show Platform;

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart' show debugPrint, kReleaseMode;

abstract class PushTokenSource {
  Future<bool> requestPermission();
  Future<String?> getToken();
  Stream<String> get onTokenRefresh;
  Future<Map<String, String>?> initialMessageData();
  Stream<Map<String, String>> get onMessageOpened;
}

/// Real source. Without platform config [Firebase.initializeApp] throws and
/// every call degrades to unsupported (push is best-effort, spec 7.4).
///
/// **A6:** dev/test no-op silently; production (`kReleaseMode`) surfaces a
/// clear diagnostic operators can see in logs. Never commit platform config.
class FirebasePushTokenSource implements PushTokenSource {
  FirebasePushTokenSource({void Function(String message)? this._onDiagnostic});

  final void Function(String message)? _onDiagnostic;
  bool? _available;
  bool _productionDiagnosticEmitted = false;

  Future<bool> _ensure() async {
    if (_available != null) return _available!;
    try {
      await Firebase.initializeApp();
      _available = true;
    } catch (_) {
      _available = false;
      _emitMissingConfigDiagnostic();
    }
    return _available!;
  }

  void _emitMissingConfigDiagnostic() {
    if (!kReleaseMode || _productionDiagnosticEmitted) return;
    _productionDiagnosticEmitted = true;
    const message =
        'LamTo: Firebase is not configured in this production build; '
        'push notifications are disabled. Deploy google-services.json / '
        'GoogleService-Info.plist (do not commit them to source control).';
    final log = _onDiagnostic ?? debugPrint;
    log(message);
  }

  @override
  Future<bool> requestPermission() async {
    if (!await _ensure()) return false;
    try {
      final settings = await FirebaseMessaging.instance.requestPermission();
      return settings.authorizationStatus == AuthorizationStatus.authorized ||
          settings.authorizationStatus == AuthorizationStatus.provisional;
    } catch (_) {
      return false;
    }
  }

  @override
  Future<String?> getToken() async {
    if (!await _ensure()) return null;
    try {
      if (Platform.isIOS) {
        final apns = await FirebaseMessaging.instance.getAPNSToken();
        if (apns == null) return null; // APNS not ready: try again later
      }
      return await FirebaseMessaging.instance.getToken();
    } catch (_) {
      return null;
    }
  }

  @override
  Stream<String> get onTokenRefresh async* {
    if (!await _ensure()) return;
    yield* FirebaseMessaging.instance.onTokenRefresh;
  }

  @override
  Future<Map<String, String>?> initialMessageData() async {
    if (!await _ensure()) return null;
    try {
      final message = await FirebaseMessaging.instance.getInitialMessage();
      return message?.data.map((k, v) => MapEntry(k, '$v'));
    } catch (_) {
      return null;
    }
  }

  @override
  Stream<Map<String, String>> get onMessageOpened async* {
    if (!await _ensure()) return;
    yield* FirebaseMessaging.onMessageOpenedApp
        .map((m) => m.data.map((k, v) => MapEntry(k, '$v')));
  }
}
