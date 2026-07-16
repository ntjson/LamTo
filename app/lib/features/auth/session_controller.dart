import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/failure.dart';
import '../../core/occupancy.dart';
import '../../core/occupancy_store.dart';
import '../../core/providers.dart';
import '../../core/token_store.dart';
import 'auth_repository.dart';

sealed class SessionState {
  const SessionState();
}

class SessionUnauthenticated extends SessionState {
  const SessionUnauthenticated();
}

class SessionAuthenticated extends SessionState {
  const SessionAuthenticated(this.me);
  final Me me;
}

/// Retryable bootstrap failure — never route this to Login (clarification #1).
class SessionBootstrapError extends SessionState {
  const SessionBootstrapError(this.failure);
  final Failure failure;
}

class SessionController extends AsyncNotifier<SessionState> {
  AuthRepository get _repo => ref.read(authRepositoryProvider);
  TokenStore get _store => ref.read(tokenStoreProvider);
  OccupancyHolder get _holder => ref.read(occupancyHolderProvider);
  OccupancyStore get _occupancyStore => ref.read(occupancyStoreProvider);

  @override
  Future<SessionState> build() => _bootstrap();

  Future<SessionState> _bootstrap() async {
    // 1. Secure storage first.
    final token = await _store.read();
    if (token == null || token.isEmpty) {
      return const SessionUnauthenticated();
    }

    try {
      final me = await _repo.fetchMe();
      await _restoreOccupancy(me);
      return SessionAuthenticated(me);
    } on DioException catch (e) {
      final failure = Failure.fromDio(e);
      final isAuth = e.response?.statusCode == 401 ||
          failure.code == 'authentication_failed' ||
          failure.code == 'not_authenticated';
      if (isAuth) {
        await _store.clear();
        return const SessionUnauthenticated();
      }
      return SessionBootstrapError(failure);
    } catch (_) {
      return SessionBootstrapError(Failure(code: 'schema_error'));
    }
  }

  Future<void> _restoreOccupancy(Me me) async {
    final userKey = _userKey(me);
    final stored = await _occupancyStore.read(userKey);
    if (stored != null && me.occupancies.any((o) => o.id == stored)) {
      _holder.occupancyId = stored;
      return;
    }
    if (stored != null) {
      await _occupancyStore.clear(userKey);
    }
    if (me.occupancies.length == 1) {
      final id = me.occupancies.first.id;
      _holder.occupancyId = id;
      await _occupancyStore.write(userKey, id);
    } else {
      _holder.occupancyId = null;
    }
  }

  String _userKey(Me me) {
    if (me.email.isNotEmpty) return me.email;
    final phone = me.phone;
    if (phone != null && phone.isNotEmpty) return phone;
    return 'install';
  }

  Future<void> signIn(String identifier, String password) async {
    final token = await _repo.login(identifier, password);
    await _store.write(token);
    final me = await _repo.fetchMe();
    await _restoreOccupancy(me);
    state = AsyncData(SessionAuthenticated(me));
  }

  Future<void> signOut() async {
    await _store.clear();
    _holder.occupancyId = null;
    state = const AsyncData(SessionUnauthenticated());
  }

  /// Persist selection, update holder, clear occupancy-scoped providers.
  Future<void> selectOccupancy(Me me, int occupancyId) async {
    final previous = _holder.occupancyId;
    _holder.occupancyId = occupancyId;
    await _occupancyStore.write(_userKey(me), occupancyId);
    if (previous != occupancyId) {
      ref.invalidate(occupancyScopedProviders);
    }
  }
}

final sessionControllerProvider =
    AsyncNotifierProvider<SessionController, SessionState>(SessionController.new);
