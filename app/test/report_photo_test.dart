import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/features/reports/report_photo.dart';

final _jpeg = Uint8List.fromList([0xff, 0xd8, 0xff, 0xe0, 0, 0x10]);
final _png = Uint8List.fromList([
  0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 0x0d, //
]);

void main() {
  group('detectPhotoFormat', () {
    test('recognises a JPEG by its leading bytes', () {
      expect(detectPhotoFormat(_jpeg), PhotoFormat.jpeg);
      expect(PhotoFormat.jpeg.contentType, 'image/jpeg');
    });

    test('recognises a PNG by its leading bytes', () {
      expect(detectPhotoFormat(_png), PhotoFormat.png);
      expect(PhotoFormat.png.contentType, 'image/png');
    });

    test('refuses anything else', () {
      expect(
        detectPhotoFormat(Uint8List.fromList([0x47, 0x49, 0x46, 0x38])),
        isNull,
      ); // GIF
      expect(
        detectPhotoFormat(Uint8List.fromList([0x25, 0x50, 0x44, 0x46])),
        isNull,
      ); // PDF
      expect(detectPhotoFormat(Uint8List(0)), isNull);
      expect(detectPhotoFormat(Uint8List.fromList([0xff, 0xd8])), isNull);
    });
  });

  test('PickedPhoto.detect throws UnsupportedPhotoException on bad bytes', () {
    expect(PickedPhoto.detect(_png).format, PhotoFormat.png);
    expect(
      () => PickedPhoto.detect(Uint8List.fromList([1, 2, 3, 4])),
      throwsA(isA<UnsupportedPhotoException>()),
    );
  });
}
