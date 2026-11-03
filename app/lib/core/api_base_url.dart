import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'config.dart';
import 'web_gaps.dart';

/// SharedPreferences key for the resident API base URL override.
const String kApiBaseUrlPrefsKey = 'api_base_url';

/// Native: the compile-time default from `--dart-define=API_BASE_URL=...` (or
/// the emulator host). Web: the origin the page was loaded from, so a new
/// tunnel hostname needs no rebuild (ADR 0009).
String get defaultApiBaseUrl =>
    NativeOnly.apiAddressOverride ? apiBaseUrl : Uri.base.origin;

/// Normalize a user-entered API base URL.
///
/// Returns `null` if the value is not an absolute http(s) URL with a host.
/// Trailing slashes are stripped so Dio path joins stay clean.
String? normalizeApiBaseUrl(String raw) {
  final trimmed = raw.trim();
  if (trimmed.isEmpty) return null;
  final uri = Uri.tryParse(trimmed);
  if (uri == null || !uri.hasScheme || !uri.hasAuthority) return null;
  if (uri.scheme != 'http' && uri.scheme != 'https') return null;
  if (uri.host.isEmpty) return null;
  var out = uri.toString();
  while (out.endsWith('/')) {
    out = out.substring(0, out.length - 1);
  }
  return out;
}

/// Runtime API base URL: prefs override, else [defaultApiBaseUrl]. The web
/// never reads or offers the override ([NativeOnly.apiAddressOverride]).
///
/// Changing this rebuilds [dioProvider] so the next request hits the new host.
/// Prefer editing the URL while signed out (login screen); if changed while
/// signed in, call sites should invalidate the session.
class ApiBaseUrlNotifier extends Notifier<String> {
  @override
  String build() {
    if (NativeOnly.apiAddressOverride) Future.microtask(_hydrate);
    return defaultApiBaseUrl;
  }

  Future<void> _hydrate() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getString(kApiBaseUrlPrefsKey);
    final normalized = saved == null ? null : normalizeApiBaseUrl(saved);
    if (normalized != null && normalized != state) {
      state = normalized;
    }
  }

  /// Persist [raw] as the API base URL. Throws [FormatException] if invalid.
  Future<void> setUrl(String raw) async {
    _requireOverride();
    final normalized = normalizeApiBaseUrl(raw);
    if (normalized == null) {
      throw const FormatException('invalid_api_base_url');
    }
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(kApiBaseUrlPrefsKey, normalized);
    state = normalized;
  }

  /// Drop the override and return to the compile-time default.
  Future<void> clearOverride() async {
    _requireOverride();
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(kApiBaseUrlPrefsKey);
    state = defaultApiBaseUrl;
  }

  void _requireOverride() {
    if (!NativeOnly.apiAddressOverride) {
      throw UnsupportedError('The web always calls its own origin.');
    }
  }
}

final apiBaseUrlProvider = NotifierProvider<ApiBaseUrlNotifier, String>(
  ApiBaseUrlNotifier.new,
);
