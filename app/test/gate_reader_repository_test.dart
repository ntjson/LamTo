import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/features/gate/reader/reader_repository.dart';

void main() {
  test('reader sends auth header, plate JSON, and face multipart', () async {
    final requests = <RequestOptions>[];
    final dio = Dio();
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          requests.add(options);
          handler.resolve(
            Response(
              requestOptions: options,
              data: {'matched': false, 'direction': 'ENTRY'},
            ),
          );
        },
      ),
    );
    final repository = ReaderRepository(dio, 'secret');
    await repository.recognizePlate('51F12345');
    final file = File('${Directory.systemTemp.path}/gate-reader-repository.jpg')
      ..writeAsBytesSync([1]);
    await repository.recognizeFace(file.path);
    file.deleteSync();
    expect(
      requests.every(
        (request) => request.headers['Authorization'] == 'GateDevice secret',
      ),
      isTrue,
    );
    expect(requests.first.data, {'plate': '51F12345'});
    expect(requests.last.data, isA<FormData>());
  });
}
