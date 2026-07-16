import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/features/reports/report_draft.dart';
import 'package:lamto/features/reports/report_photo_files.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('round-trips a draft per occupancy and clears it', () async {
    SharedPreferences.setMockInitialValues({});
    final store = ReportDraftStore();
    expect(await store.read(7), isNull);

    final draft = ReportDraft.fresh().copyWith(
      text: 'Thang máy kêu to',
      locationId: 3,
      locationLabel: 'Tòa A / Thang máy 2',
      photoPaths: ['/tmp/a.jpg'],
    );
    await store.write(7, draft);

    final loaded = await store.read(7);
    expect(loaded!.clientRef, draft.clientRef);
    expect(loaded.text, 'Thang máy kêu to');
    expect(loaded.locationId, 3);
    expect(loaded.photoPaths, ['/tmp/a.jpg']);
    // A different occupancy has no draft.
    expect(await store.read(8), isNull);

    await store.clear(7);
    expect(await store.read(7), isNull);
  });

  test('fresh drafts mint distinct clientRefs', () {
    expect(ReportDraft.fresh().clientRef,
        isNot(ReportDraft.fresh().clientRef));
  });

  test('clearAll removes every occupancy draft (logout privacy)', () async {
    SharedPreferences.setMockInitialValues({});
    final store = ReportDraftStore();
    await store.write(1, ReportDraft.fresh().copyWith(text: 'a'));
    await store.write(2, ReportDraft.fresh().copyWith(text: 'b'));
    await store.clearAll();
    expect(await store.read(1), isNull);
    expect(await store.read(2), isNull);
  });

  test('serialized writes preserve last draft under concurrent autosave',
      () async {
    SharedPreferences.setMockInitialValues({});
    final store = ReportDraftStore();
    final base = ReportDraft.fresh();
    // Fire writes without awaiting between starts; store must serialize.
    final f1 = store.write(7, base.copyWith(text: 'one'));
    final f2 = store.write(7, base.copyWith(text: 'two'));
    final f3 = store.write(7, base.copyWith(text: 'three'));
    await Future.wait([f1, f2, f3]);
    expect((await store.read(7))!.text, 'three');
  });

  test('writes only under the lamto_report_draft_ privacy prefix', () async {
    SharedPreferences.setMockInitialValues({
      'unrelated_key': 'keep-me',
    });
    final store = ReportDraftStore();
    await store.write(42, ReportDraft.fresh().copyWith(text: 'secret'));

    final prefs = await SharedPreferences.getInstance();
    final draftKeys =
        prefs.getKeys().where((k) => k.contains('report_draft')).toList();
    expect(draftKeys, isNotEmpty);
    for (final key in draftKeys) {
      expect(key.startsWith('lamto_report_draft_'), isTrue, reason: key);
    }
    expect(prefs.getString('unrelated_key'), 'keep-me');

    await store.clearAll();
    expect(
      prefs.getKeys().where((k) => k.startsWith('lamto_report_draft_')),
      isEmpty,
    );
    expect(prefs.getString('unrelated_key'), 'keep-me');
  });

  group('ReportPhotoFileStore', () {
    late Directory root;
    late ReportPhotoFileStore photos;

    setUp(() async {
      root = await Directory.systemTemp.createTemp('report_photos_');
      photos = ReportPhotoFileStore(rootOverride: root);
    });

    tearDown(() async {
      if (await root.exists()) {
        await root.delete(recursive: true);
      }
    });

    test('importPickerPath copies under occupancy-owned root', () async {
      final source = File('${root.path}/picker_source.jpg');
      await source.writeAsBytes([1, 2, 3, 4]);

      final owned = await photos.importPickerPath(
        occupancyId: 7,
        sourcePath: source.path,
      );

      expect(owned, startsWith('${root.path}/7/'));
      expect(File(owned).existsSync(), isTrue);
      expect(await File(owned).readAsBytes(), [1, 2, 3, 4]);
      expect(owned, isNot(source.path));
    });

    test('deletePaths removes owned files', () async {
      final source = File('${root.path}/src.png');
      await source.writeAsBytes([9]);
      final owned = await photos.importPickerPath(
        occupancyId: 1,
        sourcePath: source.path,
      );
      expect(File(owned).existsSync(), isTrue);

      await photos.deletePaths([owned]);
      expect(File(owned).existsSync(), isFalse);
    });

    test('clearOccupancy removes only that occupancy copies', () async {
      final sourceA = File('${root.path}/a.jpg')..writeAsBytesSync([1]);
      final sourceB = File('${root.path}/b.jpg')..writeAsBytesSync([2]);
      final pathA = await photos.importPickerPath(
        occupancyId: 1,
        sourcePath: sourceA.path,
      );
      final pathB = await photos.importPickerPath(
        occupancyId: 2,
        sourcePath: sourceB.path,
      );

      await photos.clearOccupancy(1);

      expect(File(pathA).existsSync(), isFalse);
      expect(File(pathB).existsSync(), isTrue);
    });

    test('clearAll removes every occupancy copy', () async {
      final sourceA = File('${root.path}/a.jpg')..writeAsBytesSync([1]);
      final sourceB = File('${root.path}/b.jpg')..writeAsBytesSync([2]);
      final pathA = await photos.importPickerPath(
        occupancyId: 1,
        sourcePath: sourceA.path,
      );
      final pathB = await photos.importPickerPath(
        occupancyId: 2,
        sourcePath: sourceB.path,
      );

      await photos.clearAll();

      expect(File(pathA).existsSync(), isFalse);
      expect(File(pathB).existsSync(), isFalse);
    });
  });
}
