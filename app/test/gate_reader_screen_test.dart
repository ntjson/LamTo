import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/features/gate/reader/gate_reader_screen.dart';
import 'package:lamto/features/gate/reader/reader_repository.dart';
import 'package:lamto/features/gate/reader/reader_credential_store.dart';

class FakeReader implements ReaderApi {
  @override Future<ReaderResult> recognizeFace(String path) => throw UnimplementedError();
  @override Future<ReaderResult> recognizePlate(String plate) => throw UnimplementedError();
}
class MemoryStore extends ReaderCredentialStore {
  @override Future<String?> read() async => null;
  @override Future<void> write(String value) async {}
  @override Future<void> clear() async {}
}

void main() {
  testWidgets('prompts for a device credential', (tester) async {
    await tester.pumpWidget(MaterialApp(home: GateReaderScreen(repositoryFor: (_) => FakeReader(), store: MemoryStore())));
    await tester.pump();
    expect(find.text('Ma thiet bi'), findsOneWidget);
    expect(find.text('Kich hoat dau doc'), findsOneWidget);
  });

  test('reader errors distinguish revoked and expired credentials', () {
    expect(readerError(_problem('gate_device_revoked')), contains('thu hoi'));
    expect(readerError(_problem('gate_device_expired')), contains('het han'));
  });
}

DioException _problem(String code) => DioException(requestOptions: RequestOptions(), response: Response(requestOptions: RequestOptions(), data: {'code': code}));
