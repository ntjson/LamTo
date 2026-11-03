import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/features/reports/report_photo.dart';
import 'package:lamto/features/reports/reports_repository.dart';
import 'package:mocktail/mocktail.dart';

class _MockAdapter extends Mock implements HttpClientAdapter {}

ResponseBody _json(int status, Object body) => ResponseBody.fromString(
  jsonEncode(body),
  status,
  headers: {
    Headers.contentTypeHeader: [Headers.jsonContentType],
  },
);

void main() {
  setUpAll(() => registerFallbackValue(RequestOptions(path: '/')));

  late _MockAdapter adapter;
  late DioReportsRepository repo;
  late RequestOptions lastRequest;

  setUp(() {
    adapter = _MockAdapter();
    final dio = Dio(BaseOptions(baseUrl: 'http://x'));
    dio.httpClientAdapter = adapter;
    repo = DioReportsRepository(dio);
  });

  void answerWith(int status, Object body) {
    when(() => adapter.fetch(any(), any(), any())).thenAnswer((inv) async {
      lastRequest = inv.positionalArguments[0] as RequestOptions;
      return _json(status, body);
    });
  }

  test(
    'createReport posts client_ref/text/location_id and parses summary',
    () async {
      answerWith(201, {
        'id': 5,
        'text': 'Leak',
        'status': 'SUBMITTED',
        'is_private': false,
        'location_path_snapshot': 'B / Hall',
        'created_at': '2026-07-17T00:00:00Z',
      });
      final summary = await repo.createReport(
        clientRef: 'ref-1',
        text: 'Leak',
        locationId: 3,
      );
      expect(summary.id, 5);
      expect(lastRequest.path, '/api/v1/reports');
      final sent = lastRequest.data;
      final map = sent is String ? jsonDecode(sent) : sent;
      expect(map['client_ref'], 'ref-1');
      expect(map['text'], 'Leak');
      expect(map['location_id'], 3);
    },
  );

  group('uploadPhoto', () {
    final jpegBytes = Uint8List.fromList([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3]);
    final pngBytes = Uint8List.fromList([
      0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 4, 5, 6, //
    ]);

    /// Answers 201 and captures the multipart body exactly as the adapter
    /// receives it, i.e. what goes over the wire.
    Future<List<int>> uploadAndCaptureBody(
      Uint8List bytes,
      PhotoFormat format,
    ) async {
      List<int> body = const [];
      when(() => adapter.fetch(any(), any(), any())).thenAnswer((inv) async {
        lastRequest = inv.positionalArguments[0] as RequestOptions;
        final stream = inv.positionalArguments[1] as Stream<Uint8List>?;
        body = [for (final chunk in await stream!.toList()) ...chunk];
        return _json(201, {
          'id': 9,
          'filename': 'photo',
          'sha256': 'aa',
          'download_url': '/api/v1/documents/tok',
        });
      });
      final photo = await repo.uploadPhoto(
        reportId: 5,
        bytes: bytes,
        format: format,
      );
      expect(photo.id, 9);
      expect(lastRequest.path, '/api/v1/reports/5/photos');
      return body;
    }

    bool containsSequence(List<int> haystack, List<int> needle) {
      for (var i = 0; i + needle.length <= haystack.length; i++) {
        var hit = true;
        for (var j = 0; j < needle.length; j++) {
          if (haystack[i + j] != needle[j]) {
            hit = false;
            break;
          }
        }
        if (hit) return true;
      }
      return false;
    }

    test('sends the photo bytes as image/jpeg for a JPEG', () async {
      final body = await uploadAndCaptureBody(jpegBytes, PhotoFormat.jpeg);
      final text = latin1.decode(body).toLowerCase();
      expect(text, contains('name="photo"'));
      expect(text, contains('content-type: image/jpeg'));
      expect(containsSequence(body, jpegBytes), isTrue);
    });

    test('sends image/png for a PNG whatever the filename', () async {
      final body = await uploadAndCaptureBody(pngBytes, PhotoFormat.png);
      final text = latin1.decode(body).toLowerCase();
      expect(text, contains('name="photo"'));
      expect(text, contains('content-type: image/png'));
      expect(text, isNot(contains('image/jpeg')));
      expect(containsSequence(body, pngBytes), isTrue);
    });
  });

  test('cursorFromNext extracts the DRF cursor param', () {
    expect(cursorFromNext(null), isNull);
    expect(
      cursorFromNext('http://x/api/v1/reports?cursor=cD0yMDI2'),
      'cD0yMDI2',
    );
  });

  // Amendment 13: adapter-level HTTP 200 idempotent create replay (not a fake repo).
  test(
    'createReport accepts HTTP 200 idempotent replay of same client_ref',
    () async {
      var calls = 0;
      when(() => adapter.fetch(any(), any(), any())).thenAnswer((inv) async {
        lastRequest = inv.positionalArguments[0] as RequestOptions;
        calls++;
        final body = {
          'id': 5,
          'text': 'Leak',
          'status': 'SUBMITTED',
          'is_private': false,
          'location_path_snapshot': 'B / Hall',
          'created_at': '2026-07-17T00:00:00Z',
        };
        return _json(calls == 1 ? 201 : 200, body);
      });
      final first = await repo.createReport(
        clientRef: 'ref-1',
        text: 'Leak',
        locationId: 3,
      );
      final second = await repo.createReport(
        clientRef: 'ref-1',
        text: 'Leak',
        locationId: 3,
      );
      expect(first.id, 5);
      expect(second.id, 5);
      expect(calls, 2);
    },
  );
}
