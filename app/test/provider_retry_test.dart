import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/core/provider_retry.dart';

DioException _status(int status) {
  final req = RequestOptions(path: '/api/v1/ledger/1');
  return DioException(
    requestOptions: req,
    response: Response(requestOptions: req, statusCode: status, data: {}),
    type: DioExceptionType.badResponse,
  );
}

void main() {
  test('a 404 fails at once instead of retrying', () async {
    var calls = 0;
    final provider = FutureProvider<int>((ref) async {
      calls++;
      throw _status(404);
    });
    final container = ProviderContainer.test(retry: retryTransientFailures);

    await expectLater(container.read(provider.future), throwsA(isA<DioException>()));
    await Future<void>.delayed(const Duration(milliseconds: 500));

    expect(calls, 1);
  });

  test('client errors do not retry; transient failures back off', () {
    for (final status in [400, 401, 403, 404, 409, 422]) {
      expect(retryTransientFailures(0, _status(status)), isNull, reason: '$status');
    }
    for (final status in [408, 429, 500, 502, 503]) {
      expect(retryTransientFailures(0, _status(status)), isNotNull, reason: '$status');
    }
    final offline = DioException(
      requestOptions: RequestOptions(path: '/x'),
      type: DioExceptionType.connectionError,
    );
    expect(retryTransientFailures(0, offline), isNotNull);
    expect(retryTransientFailures(10, offline), isNull);
  });
}
