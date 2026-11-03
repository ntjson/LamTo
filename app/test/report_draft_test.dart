import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/features/reports/report_draft.dart';
import 'package:lamto/features/reports/report_photo.dart';
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
      isPrivate: true,
    );
    await store.write(7, draft);

    final loaded = await store.read(7);
    expect(loaded!.clientRef, draft.clientRef);
    expect(loaded.text, 'Thang máy kêu to');
    expect(loaded.locationId, 3);
    expect(loaded.photoPaths, ['/tmp/a.jpg']);
    expect(loaded.isPrivate, isTrue);
    // A different occupancy has no draft.
    expect(await store.read(8), isNull);

    await store.clear(7);
    expect(await store.read(7), isNull);
  });

  test('fresh drafts mint distinct clientRefs', () {
    expect(ReportDraft.fresh().clientRef, isNot(ReportDraft.fresh().clientRef));
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

  test('hasUnsentWork sees non-empty drafts and pending reply photos', () async {
    SharedPreferences.setMockInitialValues({});
    final store = ReportDraftStore();
    expect(await store.hasUnsentWork(), isFalse);

    // An empty draft record is not work a resident would lose.
    await store.write(7, ReportDraft.fresh());
    expect(await store.hasUnsentWork(), isFalse);

    await store.write(7, ReportDraft.fresh().copyWith(text: 'bể ống nước'));
    expect(await store.hasUnsentWork(), isTrue);

    await store.clear(7);
    expect(await store.hasUnsentWork(), isFalse);

    // Pending info-reply photos count too (shared prefix, list payload).
    await InfoReplyPhotoStore().write(9, ['/owned/reply.jpg']);
    expect(await store.hasUnsentWork(), isTrue);
  });

  test(
    'serialized writes preserve last draft under concurrent autosave',
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
    },
  );

  test('write chains are shared across ReportDraftStore instances', () async {
    SharedPreferences.setMockInitialValues({});
    final a = ReportDraftStore();
    final b = ReportDraftStore();
    final base = ReportDraft.fresh();
    // Cross-instance concurrent writes must still serialize (static chains).
    final f1 = a.write(7, base.copyWith(text: 'one'));
    final f2 = b.write(7, base.copyWith(text: 'two'));
    final f3 = a.write(7, base.copyWith(text: 'three'));
    await Future.wait([f1, f2, f3]);
    expect((await b.read(7))!.text, 'three');
  });

  test(
    'clearAll on a fresh instance awaits writes from another instance',
    () async {
      SharedPreferences.setMockInitialValues({});
      final writer = ReportDraftStore();
      // Logout path constructs a new store; it must drain the shared chain.
      final logoutStore = ReportDraftStore();
      final base = ReportDraft.fresh();

      final write = writer.write(9, base.copyWith(text: 'should-not-linger'));
      await logoutStore.clearAll();
      await write;

      expect(await writer.read(9), isNull);
      expect(await logoutStore.read(9), isNull);
    },
  );

  test('writes only under the lamto_report_draft_ privacy prefix', () async {
    SharedPreferences.setMockInitialValues({'unrelated_key': 'keep-me'});
    final store = ReportDraftStore();
    await store.write(42, ReportDraft.fresh().copyWith(text: 'secret'));

    final prefs = await SharedPreferences.getInstance();
    final draftKeys = prefs
        .getKeys()
        .where((k) => k.contains('report_draft'))
        .toList();
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

    PickedPhoto jpeg(int marker) => PickedPhoto(
      Uint8List.fromList([0xff, 0xd8, 0xff, 0xe0, marker]),
      PhotoFormat.jpeg,
    );

    test('saveDraftPhoto writes bytes under the occupancy-owned root', () async {
      final photo = PickedPhoto(
        Uint8List.fromList([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 7]),
        PhotoFormat.png,
      );

      final owned = await photos.saveDraftPhoto(occupancyId: 7, photo: photo);

      expect(owned, startsWith('${root.path}/7/'));
      // The extension comes from the detected format, not from a picker name.
      expect(owned, endsWith('.png'));
      expect(await File(owned).readAsBytes(), photo.bytes);
    });

    test('load reads an owned photo back as bytes and its format', () async {
      final owned = await photos.saveDraftPhoto(
        occupancyId: 7,
        photo: jpeg(1),
      );

      final loaded = await photos.load(owned);

      expect(loaded.bytes, jpeg(1).bytes);
      expect(loaded.format, PhotoFormat.jpeg);
    });

    test('tryLoad is null for a missing file or non-image bytes', () async {
      expect(await photos.tryLoad('${root.path}/gone.jpg'), isNull);
      final notImage = File('${root.path}/note.jpg')
        ..writeAsBytesSync([1, 2, 3, 4]);
      expect(await photos.tryLoad(notImage.path), isNull);
    });

    test('deletePaths removes owned files', () async {
      final owned = await photos.saveDraftPhoto(occupancyId: 1, photo: jpeg(9));
      expect(File(owned).existsSync(), isTrue);

      await photos.deletePaths([owned]);
      expect(File(owned).existsSync(), isFalse);
    });

    test('clearOccupancy removes only that occupancy copies', () async {
      final pathA = await photos.saveDraftPhoto(occupancyId: 1, photo: jpeg(1));
      final pathB = await photos.saveDraftPhoto(occupancyId: 2, photo: jpeg(2));

      await photos.clearOccupancy(1);

      expect(File(pathA).existsSync(), isFalse);
      expect(File(pathB).existsSync(), isTrue);
    });

    test('clearAll removes every occupancy copy', () async {
      final pathA = await photos.saveDraftPhoto(occupancyId: 1, photo: jpeg(1));
      final pathB = await photos.saveDraftPhoto(occupancyId: 2, photo: jpeg(2));

      await photos.clearAll();

      expect(File(pathA).existsSync(), isFalse);
      expect(File(pathB).existsSync(), isFalse);
    });

    test('saveReplyPhoto writes under the reply dir, out of reach of '
        'clearOccupancy, wiped by clearAll', () async {
      final owned = await photos.saveReplyPhoto(reportId: 7, photo: jpeg(5));

      expect(owned, startsWith('${root.path}/reply_7/'));
      expect(await File(owned).readAsBytes(), jpeg(5).bytes);

      // Same-numbered occupancy cleanup must not touch reply copies.
      await photos.clearOccupancy(7);
      expect(File(owned).existsSync(), isTrue);

      await photos.clearAll(); // logout wipe covers reply copies
      expect(File(owned).existsSync(), isFalse);
    });
  });

  group('InfoReplyPhotoStore', () {
    setUp(() {
      SharedPreferences.setMockInitialValues({});
    });

    test('round-trips pending paths; empty write removes the record', () async {
      final store = InfoReplyPhotoStore();
      expect(await store.read(42), isEmpty);

      await store.write(42, ['/owned/reply_42/a.jpg', '/owned/reply_42/b.jpg']);
      expect(await store.read(42), [
        '/owned/reply_42/a.jpg',
        '/owned/reply_42/b.jpg',
      ]);

      await store.write(42, ['/owned/reply_42/b.jpg']);
      expect(await store.read(42), ['/owned/reply_42/b.jpg']);

      await store.write(42, []);
      expect(await store.read(42), isEmpty);
      final prefs = await SharedPreferences.getInstance();
      expect(
        prefs.getKeys().where((k) => k.contains('reply_photos')),
        isEmpty,
      );
    });

    test('logout ReportDraftStore.clearAll drops reply records too', () async {
      final store = InfoReplyPhotoStore();
      await store.write(42, ['/owned/reply_42/a.jpg']);

      await ReportDraftStore().clearAll();

      expect(await store.read(42), isEmpty);
    });
  });
}
