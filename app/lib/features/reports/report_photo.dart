import 'dart:typed_data';

/// The two image formats the report API accepts.
enum PhotoFormat {
  jpeg('image/jpeg', 'jpg'),
  png('image/png', 'png');

  const PhotoFormat(this.contentType, this.extension);

  final String contentType;
  final String extension;
}

/// Reads the format from the photo's leading bytes, never from a filename
/// (the rule ADR 0006 set for documents, extended to photos by ADR 0009).
/// Returns null for anything that is not a JPEG or a PNG.
PhotoFormat? detectPhotoFormat(Uint8List bytes) {
  if (bytes.length >= 3 &&
      bytes[0] == 0xff &&
      bytes[1] == 0xd8 &&
      bytes[2] == 0xff) {
    return PhotoFormat.jpeg;
  }
  const pngSignature = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
  if (bytes.length >= pngSignature.length) {
    var matches = true;
    for (var i = 0; i < pngSignature.length; i++) {
      if (bytes[i] != pngSignature[i]) {
        matches = false;
        break;
      }
    }
    if (matches) return PhotoFormat.png;
  }
  return null;
}

/// The picked bytes are not a JPEG or a PNG; they are never sent.
class UnsupportedPhotoException implements Exception {
  const UnsupportedPhotoException();

  @override
  String toString() => 'UnsupportedPhotoException';
}

/// A report photo held as bytes, with the format its bytes declare. The one
/// shape every platform uploads and every thumbnail draws from.
class PickedPhoto {
  const PickedPhoto(this.bytes, this.format);

  /// Throws [UnsupportedPhotoException] when [bytes] are not a JPEG or PNG.
  factory PickedPhoto.detect(Uint8List bytes) {
    final format = detectPhotoFormat(bytes);
    if (format == null) throw const UnsupportedPhotoException();
    return PickedPhoto(bytes, format);
  }

  final Uint8List bytes;
  final PhotoFormat format;
}
