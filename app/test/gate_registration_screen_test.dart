import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/features/gate/gate_registration_screen.dart';

void main() {
  test('registration statuses have Vietnamese resident copy', () {
    expect(statusText('PENDING', ''), contains('cho duyet'));
    expect(statusText('REJECTED', 'Anh mo'), contains('Anh mo'));
    expect(statusText('EXPIRED', ''), contains('gui lai'));
  });

  test('plate conflict does not leak another resident', () {
    final request = RequestOptions();
    final error = DioException(requestOptions: request, response: Response(requestOptions: request, data: {'code': 'gate_plate_already_registered'}));
    final message = gateErrorMessage(error);
    expect(message, contains('lien he ban quan ly'));
    expect(message, isNot(contains('can ho')));
  });
}
