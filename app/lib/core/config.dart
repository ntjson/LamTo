import 'package:flutter/foundation.dart' show kIsWeb;

/// Compile-time default only. Prefer [apiBaseUrlProvider] at runtime so the
/// user can point a installed APK at a new Cloudflare tunnel without rebuild.
const String apiBaseUrl = String.fromEnvironment(
  'API_BASE_URL',
  defaultValue: 'http://10.0.2.2:8000',
);

/// The gate reader kiosk build (`--dart-define=GATE_READER_MODE=true`). A
/// native-only build mode: a web build is always the Resident app (ADR 0009).
const bool gateReaderMode = bool.fromEnvironment('GATE_READER_MODE') && !kIsWeb;
