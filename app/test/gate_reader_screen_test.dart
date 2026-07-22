import 'dart:io';

import 'package:camera/camera.dart';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/features/gate/reader/gate_reader_screen.dart';
import 'package:lamto/features/gate/reader/reader_credential_store.dart';
import 'package:lamto/features/gate/reader/reader_repository.dart';

class FakeReader implements ReaderApi {
  FakeReader({this.matched = true, this.error});
  final bool matched;
  final Object? error;
  String? plate;
  String? facePath;
  @override
  Future<ReaderResult> recognizeFace(String path) async {
    facePath = path;
    if (error != null) throw error!;
    return ReaderResult.fromJson({
      'matched': matched,
      'display_name': 'An',
      'unit_label': '101',
      'direction': 'ENTRY',
    });
  }

  @override
  Future<ReaderResult> recognizePlate(String value) async {
    plate = value;
    if (error != null) throw error!;
    return ReaderResult.fromJson({
      'matched': matched,
      'display_name': 'An',
      'unit_label': '101',
      'direction': 'ENTRY',
    });
  }
}

class MemoryStore extends ReaderCredentialStore {
  MemoryStore([this.value]);
  String? value;
  @override
  Future<String?> read() async => value;
  @override
  Future<void> write(String value) async => this.value = value;
  @override
  Future<void> clear() async => value = null;
}

class FakeCamera implements ReaderCamera {
  FakeCamera(this.path);
  final String path;
  int captures = 0;
  @override
  Widget get preview =>
      const ColoredBox(key: Key('camera-preview'), color: Colors.black);
  @override
  Future<XFile> capture() async {
    captures++;
    return XFile(path);
  }

  @override
  Future<void> dispose() async {}
}

void main() {
  testWidgets('secure credential is persisted and can be cleared', (
    tester,
  ) async {
    final store = MemoryStore();
    await tester.pumpWidget(
      MaterialApp(
        home: GateReaderScreen(
          repositoryFor: (_) => FakeReader(),
          camera: FakeCamera('/tmp/unused'),
          direction: 'ENTRY',
          store: store,
        ),
      ),
    );
    await tester.pump();
    await tester.enterText(find.byType(TextField), ' secret ');
    await tester.tap(find.text('Kich hoat dau doc'));
    await tester.pump();
    expect(store.value, 'secret');
    expect(find.byKey(const Key('camera-preview')), findsOneWidget);
    expect(find.text('ENTRY'), findsOneWidget);
    await tester.tap(find.text('Xoa ma thiet bi'));
    await tester.pump();
    expect(store.value, isNull);
  });

  testWidgets('OCR submission shows matched result and deletes capture', (
    tester,
  ) async {
    final file = File('${Directory.systemTemp.path}/gate-reader-plate.jpg')
      ..writeAsBytesSync([1]);
    final camera = FakeCamera(file.path);
    final reader = FakeReader();
    await tester.pumpWidget(
      MaterialApp(
        home: GateReaderScreen(
          repositoryFor: (_) => reader,
          camera: camera,
          direction: 'ENTRY',
          store: MemoryStore('token'),
          ocr: (_) async => '51F12345',
        ),
      ),
    );
    await tester.pump();
    await tester.tap(find.text('Quet bien so'));
    await tester.pumpAndSettle();
    expect(reader.plate, '51F12345');
    expect(find.textContaining('An'), findsOneWidget);
    expect(file.existsSync(), isFalse);
  });

  testWidgets('unmatched face is shown and network failure is never queued', (
    tester,
  ) async {
    final file = File('${Directory.systemTemp.path}/gate-reader-face.jpg')
      ..writeAsBytesSync([1]);
    final camera = FakeCamera(file.path);
    final reader = FakeReader(
      error: DioException(requestOptions: RequestOptions()),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: GateReaderScreen(
          repositoryFor: (_) => reader,
          camera: camera,
          direction: 'EXIT',
          store: MemoryStore('token'),
        ),
      ),
    );
    await tester.pump();
    await tester.tap(find.text('Quet khuon mat'));
    await tester.pumpAndSettle();
    expect(find.textContaining('khong duoc luu'), findsOneWidget);
    expect(camera.captures, 1);
    expect(file.existsSync(), isFalse);
  });

  testWidgets('unmatched recognition is shown', (tester) async {
    final file = File('${Directory.systemTemp.path}/gate-reader-unmatched.jpg')
      ..writeAsBytesSync([1]);
    await tester.pumpWidget(
      MaterialApp(
        home: GateReaderScreen(
          repositoryFor: (_) => FakeReader(matched: false),
          camera: FakeCamera(file.path),
          direction: 'EXIT',
          store: MemoryStore('token'),
        ),
      ),
    );
    await tester.pump();
    await tester.tap(find.text('Quet khuon mat'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Khong nhan dien duoc'), findsOneWidget);
    expect(file.existsSync(), isFalse);
  });

  test('reader errors map every stable face code distinctly', () {
    final codes = [
      'gate_no_face_detected',
      'gate_multiple_faces',
      'gate_face_too_small',
      'gate_face_too_blurry',
      'gate_face_unusable',
      'gate_photo_rejected',
      'gate_face_upload_too_large',
    ];
    expect(
      codes.map((code) => readerError(_problem(code))).toSet(),
      hasLength(codes.length),
    );
  });
}

DioException _problem(String code) => DioException(
  requestOptions: RequestOptions(),
  response: Response(requestOptions: RequestOptions(), data: {'code': code}),
);
