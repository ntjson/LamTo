import 'dart:io';

import 'package:path_provider/path_provider.dart';

import '../../core/uuid.dart';
import 'report_photo.dart';

/// App-owned durable copies of report draft photos (plan amendment 8).
///
/// Picker/cache paths alone do not survive process death. Before a path is
/// stored on a [ReportDraft], write the picked photo's bytes into application
/// documents under `report_draft_photos/<occupancyId>/` via [saveDraftPhoto]
/// (or `reply_<reportId>/` via [saveReplyPhoto]).
/// Delete owned files when a photo is removed, a draft is cleared/committed,
/// reminted without photos, abandoned, or wiped on logout.
///
/// The photo is held as bytes everywhere else (ADR 0009); this store is only
/// the native durable copy that lets a draft keep its photos across restarts.
/// File names carry the extension of the detected format, never the picker's.
class ReportPhotoFileStore {
  /// [rootOverride] is for tests (temp dir). Production uses
  /// `getApplicationDocumentsDirectory()/report_draft_photos`.
  ReportPhotoFileStore({this._rootOverride});

  final Directory? _rootOverride;

  static const relativeRootName = 'report_draft_photos';

  String _join(String a, String b) => '$a${Platform.pathSeparator}$b';

  Future<Directory> _root() async {
    final override = _rootOverride;
    if (override != null) {
      if (!await override.exists()) {
        await override.create(recursive: true);
      }
      return override;
    }
    final docs = await getApplicationDocumentsDirectory();
    final root = Directory(_join(docs.path, relativeRootName));
    if (!await root.exists()) {
      await root.create(recursive: true);
    }
    return root;
  }

  Future<Directory> _occupancyDir(int occupancyId) async {
    final root = await _root();
    final dir = Directory(_join(root.path, '$occupancyId'));
    if (!await dir.exists()) {
      await dir.create(recursive: true);
    }
    return dir;
  }

  /// Writes [photo] into app-owned storage for [occupancyId] and returns the
  /// durable absolute path to store on the draft.
  Future<String> saveDraftPhoto({
    required int occupancyId,
    required PickedPhoto photo,
  }) async {
    final dir = await _occupancyDir(occupancyId);
    return _write(dir, photo);
  }

  /// Writes [photo] into app-owned storage for a needs-info reply on
  /// [reportId] and returns the durable absolute path. Lives under
  /// `report_draft_photos/reply_<reportId>/` — the `reply_` prefix cannot
  /// collide with occupancy int dirs, and the logout [clearAll] wipe covers it.
  Future<String> saveReplyPhoto({
    required int reportId,
    required PickedPhoto photo,
  }) async {
    final root = await _root();
    final dir = Directory(_join(root.path, 'reply_$reportId'));
    if (!await dir.exists()) {
      await dir.create(recursive: true);
    }
    return _write(dir, photo);
  }

  Future<String> _write(Directory dir, PickedPhoto photo) async {
    final destPath = _join(dir.path, '${uuidV4()}.${photo.format.extension}');
    await File(destPath).writeAsBytes(photo.bytes, flush: true);
    return destPath;
  }

  /// Reads an app-owned photo back as bytes. Throws when the file is gone
  /// ([FileSystemException]) or is not a JPEG/PNG ([UnsupportedPhotoException]).
  Future<PickedPhoto> load(String path) async =>
      PickedPhoto.detect(await File(path).readAsBytes());

  /// [load], or null when the photo cannot be read.
  Future<PickedPhoto?> tryLoad(String path) async {
    try {
      return await load(path);
    } on Object {
      return null;
    }
  }

  /// Best-effort delete of individual owned (or any) file paths.
  Future<void> deletePaths(Iterable<String> paths) async {
    for (final path in paths) {
      final file = File(path);
      if (await file.exists()) {
        await file.delete();
      }
    }
  }

  /// Deletes all app-owned photo copies for one occupancy.
  Future<void> clearOccupancy(int occupancyId) async {
    final root = await _root();
    final dir = Directory(_join(root.path, '$occupancyId'));
    if (await dir.exists()) {
      await dir.delete(recursive: true);
    }
  }

  /// Deletes every occupancy's photo copies (logout / full wipe).
  Future<void> clearAll() async {
    final root = await _root();
    if (await root.exists()) {
      await root.delete(recursive: true);
    }
  }
}
