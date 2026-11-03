@Tags(['web'])
library;

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/core/failure.dart';
import 'package:lamto/features/gate/gate_registration_screen.dart';
import 'package:lamto/features/gate/gate_repository.dart';
import 'package:lamto/l10n/app_localizations.dart';
import 'package:lamto/l10n/app_localizations_vi.dart';

/// A resident with one plate and a face already on file.
class _FakeGateRepository implements GateRepository {
  @override
  Future<Map<String, dynamic>> registrations() async => {
    'plates': [
      {'id': 1, 'plate': '30A-12345', 'status': 'APPROVED'},
    ],
    'face': {'status': 'APPROVED'},
  };

  @override
  Future<void> addPlate(String plate) async {}
  @override
  Future<void> deletePlate(int id) async {}
  @override
  Future<void> submitFace(String path) async {}
  @override
  Future<void> deleteFace() async {}
}

void main() {
  final l10n = AppLocalizationsVi();

  test('plate conflict does not leak another resident', () {
    final request = RequestOptions();
    final error = DioException(
      requestOptions: request,
      response: Response(
        requestOptions: request,
        data: {'code': 'gate_plate_already_registered'},
      ),
    );
    final message = failureMessage(Failure.fromObject(error), l10n);
    expect(message, contains('liên hệ ban quản lý'));
    expect(message, isNot(contains('căn hộ')));
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
      return failureMessage(
        Failure.fromObject(
          DioException(
            requestOptions: request,
            response: Response(requestOptions: request, data: {'code': code}),
          ),
        ),
        l10n,
      );
    });
    expect(messages.toSet(), hasLength(codes.length));
  });

  testWidgets('plates register on every platform; face enrolment only on '
      'native', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        locale: const Locale('vi'),
        home: GateRegistrationScreen(repository: _FakeGateRepository()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('30A-12345'), findsOneWidget);
    expect(find.text('Gửi biển số để duyệt'), findsOneWidget);
    // The web has no gate face enrolment (ADR 0009): no face section at all.
    final faceOffered = kIsWeb ? findsNothing : findsOneWidget;
    expect(find.text('Chụp ảnh đăng ký'), faceOffered);
    expect(find.text('Thu hồi khuôn mặt'), faceOffered);
    expect(find.byIcon(Icons.face_outlined), faceOffered);
  });
}
