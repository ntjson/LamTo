import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Riverpod retry policy for API-backed providers.
///
/// Riverpod retries every failure by default (10 times, backing off to 6.4 s),
/// so a permanent answer like 404 kept a screen loading for about half a
/// minute before its error and Retry button appeared. Only failures that can
/// heal on their own are retried: no response (offline, timeout), 408, 429
/// and 5xx. Any other 4xx fails at once and the screen offers an explicit retry.
Duration? retryTransientFailures(int retryCount, Object error) {
  if (error is DioException) {
    final status = error.response?.statusCode;
    final transient =
        status == null || status == 408 || status == 429 || status >= 500;
    if (!transient) return null;
  }
  return ProviderContainer.defaultRetry(retryCount, error);
}
