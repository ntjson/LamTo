import 'dart:async';
import 'dart:io' show Platform;

import 'package:shared_preferences/shared_preferences.dart';

import '../../core/uuid.dart';
import '../transparency/transparency_repository.dart';
import 'push_token_source.dart';

/// Stable per-install id (spec 7.2 upsert key). Never the auth token.
class InstallIdStore {
  InstallIdStore([SharedPreferences? prefs]) : _prefsOverride = prefs;
  final SharedPreferences? _prefsOverride;
  static const key = 'lamto_install_id';

  Future<SharedPreferences> _prefs() async =>
      _prefsOverride ?? await SharedPreferences.getInstance();

  Future<String> get() async {
    final prefs = await _prefs();
    final existing = prefs.getString(key);
    if (existing != null && existing.isNotEmpty) return existing;
    final minted = uuidV4();
    await prefs.setString(key, minted);
    return minted;
  }
}

/// SharedPreferences keys for push hygiene (A4 / A5).
abstract final class PushPrefsKeys {
  /// OS permission was requested once for this install (A4).
  static String permissionRequested(String installId) =>
      'push_permission_requested_$installId';

  /// Install id awaiting server deactivation after a failed logout deregister
  /// (A5).
  static const pendingDeregister = 'pending_device_deregister_install_id';
}

/// Client half of spec 7.2/7.5: consent-gated registration, token-refresh
/// re-registration, logout deactivation. Every path is best-effort.
///
/// **A4:** OS permission is requested only once per install (flag keyed by
/// install id). Later submits never re-prompt; register only when permission
/// was granted and a token is available.
///
/// **A5:** failed [deregister] persists [PushPrefsKeys.pendingDeregister] so
/// the next authenticated session can [retryPendingDeregister].
class PushRegistrar {
  PushRegistrar({
    required this.tokenSource,
    required this.repository,
    required this.installIdStore,
    SharedPreferences? prefs,
  }) : _prefsOverride = prefs;

  final PushTokenSource tokenSource;
  final TransparencyRepository repository;
  final InstallIdStore installIdStore;
  final SharedPreferences? _prefsOverride;
  StreamSubscription<String>? _refreshSub;

  Future<SharedPreferences> _prefs() async =>
      _prefsOverride ?? await SharedPreferences.getInstance();

  String get _platform {
    try {
      return Platform.isIOS ? 'IOS' : 'ANDROID';
    } catch (_) {
      return 'ANDROID';
    }
  }

  /// Ask OS permission once (in context, spec 7.5 + A4) and register.
  Future<void> registerAfterConsent() async {
    try {
      final installId = await installIdStore.get();
      final prefs = await _prefs();
      final requestedKey = PushPrefsKeys.permissionRequested(installId);
      final alreadyRequested = prefs.getBool(requestedKey) ?? false;

      if (!alreadyRequested) {
        final granted = await tokenSource.requestPermission();
        await prefs.setBool(requestedKey, true);
        if (!granted) return;
      }
      // Already requested: never re-prompt (A4). Proceed only if a token is
      // available (implies permission still useful for registration).

      final token = await tokenSource.getToken();
      if (token == null || token.isEmpty) return;
      await repository.registerDevice(
        installId: installId,
        fcmToken: token,
        platform: _platform,
      );
    } catch (_) {
      // Push failure never blocks any workflow (spec 7.4).
    }
  }

  /// Re-register whenever FCM rotates the token (spec 7.2).
  void watchTokenRefresh() {
    _refreshSub ??= tokenSource.onTokenRefresh.listen((token) async {
      try {
        if (token.isEmpty) return;
        await repository.registerDevice(
          installId: await installIdStore.get(),
          fcmToken: token,
          platform: _platform,
        );
      } catch (_) {}
    });
  }

  /// Logout deactivates this install's device (spec 7.2 + A5). Best-effort:
  /// on failure, persist a pending key for the next authenticated session.
  Future<void> deregister() async {
    await _refreshSub?.cancel();
    _refreshSub = null;
    final installId = await installIdStore.get();
    try {
      await repository.deactivateDevice(installId);
      final prefs = await _prefs();
      await prefs.remove(PushPrefsKeys.pendingDeregister);
    } catch (_) {
      final prefs = await _prefs();
      await prefs.setString(PushPrefsKeys.pendingDeregister, installId);
    }
  }

  /// Retry a prior failed [deregister] (A5). No-op when nothing is pending.
  Future<void> retryPendingDeregister() async {
    try {
      final prefs = await _prefs();
      final pending = prefs.getString(PushPrefsKeys.pendingDeregister);
      if (pending == null || pending.isEmpty) return;
      await repository.deactivateDevice(pending);
      await prefs.remove(PushPrefsKeys.pendingDeregister);
    } catch (_) {
      // Leave the pending key for a later authenticated session.
    }
  }
}
