import 'package:dio/dio.dart';

import 'config.dart';
import 'occupancy.dart';
import 'token_store.dart';

/// One interceptor owns auth (spec 6.4): attach the knox token; on any 401
/// clear secure storage and signal the session is lost. Occupancy header is
/// injected only on building-scoped paths (clarification #3).
Dio buildDio({
  required TokenStore store,
  required OccupancyHolder occupancy,
  required void Function() onUnauthorized,
  String? baseUrl,
}) {
  final dio = Dio(BaseOptions(baseUrl: baseUrl ?? apiBaseUrl));
  dio.interceptors.add(
    InterceptorsWrapper(
      onRequest: (options, handler) async {
        final token = await store.read();
        if (token != null && token.isNotEmpty) {
          options.headers['Authorization'] = 'Token $token';
          options.extra['had_token'] = true;
        }
        final occ = occupancy.occupancyId;
        if (occ != null && isBuildingScopedPath(options.path)) {
          options.headers['X-LamTo-Occupancy'] = occ;
        }
        handler.next(options);
      },
      onError: (error, handler) async {
        // Only a 401 on a request that CARRIED a token is a session expiry.
        if (error.response?.statusCode == 401 &&
            error.requestOptions.extra['had_token'] == true) {
          await store.clear();
          onUnauthorized();
        }
        handler.next(error);
      },
    ),
  );
  return dio;
}
