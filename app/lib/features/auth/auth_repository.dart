import 'package:dio/dio.dart';
import 'package:lamto_api/lamto_api.dart';

/// Manual Dio paths used by this repository (clarification #4 contract tests).
abstract final class AuthApiPaths {
  static const login = '/api/v1/auth/login';
  static const me = '/api/v1/me';
}

abstract class AuthRepository {
  Future<String> login(String identifier, String password);
  Future<Me> fetchMe();
}

class DioAuthRepository implements AuthRepository {
  DioAuthRepository(this._dio);
  final Dio _dio;

  @override
  Future<String> login(String identifier, String password) async {
    final res = await _dio.post<Map<String, dynamic>>(
      AuthApiPaths.login,
      data: {'identifier': identifier, 'password': password},
    );
    final token = standardSerializers.deserializeWith(
      TokenResponse.serializer,
      res.data!,
    )!;
    return token.token;
  }

  @override
  Future<Me> fetchMe() async {
    final res = await _dio.get<Map<String, dynamic>>(AuthApiPaths.me);
    return standardSerializers.deserializeWith(Me.serializer, res.data!)!;
  }
}
