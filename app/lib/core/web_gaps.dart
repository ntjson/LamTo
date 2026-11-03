import 'package:flutter/foundation.dart' show kIsWeb;

/// What the web build of the Resident app leaves out (ADR 0009). Constants,
/// so the web compiler drops the code behind them. Every screen that would
/// offer one of these asks here rather than testing the platform itself.
abstract final class NativeOnly {
  /// Scanning a bill's payment QR. Its third-party decoder is never loaded
  /// on the web.
  static const billScan = !kIsWeb;

  /// Enrolling a face for the gate. Plates can still be registered.
  static const gateFaceEnrolment = !kIsWeb;

  /// Push registration, its permission prompt and Firebase. No Firebase
  /// script is fetched on the web.
  static const push = !kIsWeb;

  /// The saved API-address override. The web always calls the origin the
  /// page was loaded from.
  static const apiAddressOverride = !kIsWeb;

  /// Report photos kept as app-owned files, so a draft keeps them across a
  /// restart. On the web a photo lives only in memory and a reload drops it.
  static const durablePhotos = !kIsWeb;
}
