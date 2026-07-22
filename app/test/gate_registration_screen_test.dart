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
    final error = DioException(
      requestOptions: request,
      response: Response(
        requestOptions: request,
        data: {'code': 'gate_plate_already_registered'},
      ),
    );
    final message = gateErrorMessage(error);
    expect(message, contains('lien he ban quan ly'));
    expect(message, isNot(contains('can ho')));
  });

  test('every stable face enrollment error has distinct Vietnamese copy', () {
    final codes = [
      'gate_no_face_detected',
      'gate_multiple_faces',
      'gate_face_too_small',
      'gate_face_too_blurry',
      'gate_face_unusable',
      'gate_photo_rejected',
      'gate_face_upload_too_large',
      'gate_model_unavailable',
    ];
    final messages = codes.map((code) {
      final request = RequestOptions();
      return gateErrorMessage(
        DioException(
          requestOptions: request,
          response: Response(requestOptions: request, data: {'code': code}),
        ),
      );
    });
    expect(messages.toSet(), hasLength(codes.length));
  });
}
