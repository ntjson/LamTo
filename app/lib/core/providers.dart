import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../features/auth/auth_repository.dart';
import '../features/auth/session_controller.dart';
import 'api_client.dart';
import 'occupancy.dart';
import 'occupancy_store.dart';
import 'token_store.dart';

final tokenStoreProvider = Provider<TokenStore>((ref) => TokenStore());
final occupancyHolderProvider =
    Provider<OccupancyHolder>((ref) => OccupancyHolder());
final occupancyStoreProvider = Provider<OccupancyStore>((ref) => OccupancyStore());

/// Marker provider invalidated when occupancy changes (scoped caches).
final occupancyScopedProviders = Provider<void>((ref) {});

final dioProvider = Provider<Dio>((ref) {
  return buildDio(
    store: ref.watch(tokenStoreProvider),
    occupancy: ref.watch(occupancyHolderProvider),
    onUnauthorized: () => ref.invalidate(sessionControllerProvider),
  );
});

final authRepositoryProvider = Provider<AuthRepository>(
  (ref) => DioAuthRepository(ref.watch(dioProvider)),
);
