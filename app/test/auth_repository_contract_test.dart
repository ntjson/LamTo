import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/features/auth/auth_repository.dart';

/// Contract tests for every manually written endpoint path (clarification #4).
/// Paths must match docs/api/openapi-v1.yaml.
void main() {
  test('login path matches OpenAPI', () {
    expect(AuthApiPaths.login, '/api/v1/auth/login');
  });

  test('me path matches OpenAPI', () {
    expect(AuthApiPaths.me, '/api/v1/me');
  });
}
