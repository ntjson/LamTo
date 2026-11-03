import 'dart:typed_data';

import 'package:image_picker/image_picker.dart';
import 'package:lamto/features/reports/report_photo.dart';
import 'package:lamto/features/reports/report_photo_files.dart';

/// Leading bytes are what matter: detection never looks past the signature.
final jpegBytes = Uint8List.fromList([0xff, 0xd8, 0xff, 0xe0, 0, 0x10, 1, 2]);
final pngBytes = Uint8List.fromList([
  0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 0x0d, //
]);
final gifBytes = Uint8List.fromList([0x47, 0x49, 0x46, 0x38, 0x39, 0x61, 0, 0]);

/// A picked file the way the web and native pickers hand it over: bytes behind
/// a name that may say nothing (or lie) about the format.
XFile pickedFile(Uint8List bytes, {String name = 'photo'}) =>
    XFile.fromData(bytes, name: name);

/// In-memory picker: no native picker can run under `flutter test`.
class FakeImagePicker extends ImagePicker {
  FakeImagePicker(this.files);
  final List<XFile> files;

  @override
  Future<List<XFile>> pickMultiImage({
    double? maxWidth,
    double? maxHeight,
    int? imageQuality,
    int? limit,
    bool requestFullMetadata = true,
  }) async => files;

  @override
  Future<XFile?> pickImage({
    required ImageSource source,
    double? maxWidth,
    double? maxHeight,
    int? imageQuality,
    CameraDevice preferredCameraDevice = CameraDevice.rear,
    bool requestFullMetadata = true,
  }) async => files.isEmpty ? null : files.first;
}

/// No real file IO in widget tests (fake-async cannot drive dart:io futures).
/// [files] stands in for the app-owned directory: seed it to simulate photos
/// that survived a restart.
class FakePhotoFileStore extends ReportPhotoFileStore {
  final files = <String, PickedPhoto>{};
  final deleted = <String>[];
  int _n = 0;

  String _save(String dir, PickedPhoto photo) {
    final path = '/owned/$dir/photo${++_n}.${photo.format.extension}';
    files[path] = photo;
    return path;
  }

  @override
  Future<String> saveDraftPhoto({
    required int occupancyId,
    required PickedPhoto photo,
  }) async => _save('report_$occupancyId', photo);

  @override
  Future<String> saveReplyPhoto({
    required int reportId,
    required PickedPhoto photo,
  }) async => _save('reply_$reportId', photo);

  @override
  Future<PickedPhoto> load(String path) async =>
      files[path] ?? (throw StateError('no such file: $path'));

  @override
  Future<void> deletePaths(Iterable<String> paths) async {
    deleted.addAll(paths);
    paths.forEach(files.remove);
  }
}
