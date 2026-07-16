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

/// Feature providers that cache occupancy-scoped data MUST `ref.watch` this
/// so they rebuild when occupancy changes (clarification #2).
final occupancyScopedProviders = Provider<void>((ref) {});

/// True once the user has completed a successful sign-in or bootstrap in this
/// process; gates interceptor-driven session invalidation (review I2).
final sessionEstablishedProvider = Provider<bool>((ref) {
  final session = ref.watch(sessionControllerProvider);
  return switch (session) {
    AsyncData(:final value) => value is SessionAuthenticated,
    _ => false,
  };
});

final dioProvider = Provider<Dio>((ref) {
  return buildDio(
    store: ref.watch(tokenStoreProvider),
    occupancy: ref.watch(occupancyHolderProvider),
    signalSessionLoss: () => ref.read(sessionEstablishedProvider),
    onUnauthorized: () => ref.invalidate(sessionControllerProvider),
  );
});

final authRepositoryProvider = Provider<AuthRepository>(
  (ref) => DioAuthRepository(ref.watch(dioProvider)),
);
