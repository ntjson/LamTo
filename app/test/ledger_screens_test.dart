import 'package:built_collection/built_collection.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto/features/ledger/ledger_detail_screen.dart';
import 'package:lamto/features/ledger/ledger_screen.dart';
import 'package:lamto/features/transparency/transparency_repository.dart';
import 'package:lamto/l10n/app_localizations.dart';
import 'package:lamto_api/lamto_api.dart';

LedgerEntryList _entry(int id, String level) => LedgerEntryList(
      (b) => b
        ..id = id
        ..contractorName = 'Acme Co'
        ..actualCostVnd = 900000
        ..publishedAt = DateTime.utc(2026, 7, 10)
        ..integrityStatus = 'VERIFIED'
        ..evidenceLevel = level,
    );

LedgerEntryDetail _detail() => LedgerEntryDetail(
      (b) => b
        ..id = 42
        ..contractorName = 'Acme Co'
        ..actualCostVnd = 900000
        ..publishedAt = DateTime.utc(2026, 7, 10)
        ..proposedAmountVnd = 950000
        ..integrityStatus = 'VERIFIED'
        ..whatWasFixed = 'Cable secured'
        ..why = 'Worn cable'
        ..approvers = ListBuilder<LedgerApprover>([
          LedgerApprover(
            (a) => a
              ..role = 'board'
              ..name = 'Ông Minh'
              ..decision = 'APPROVE',
          ),
          LedgerApprover(
            (a) => a
              ..role = 'resident_rep'
              ..name = 'Bà Hoa'
              ..decision = 'APPROVE',
          ),
        ])
        ..verification = Verification(
          (v) => v
            ..decision = 'VERIFIED'
            ..verifiedBy = 'Bà Lan'
            ..verifiedAt = DateTime.utc(2026, 7, 9),
        ).toBuilder()
        ..redactedDocuments = ListBuilder<RedactedDocument>()
        ..corrections = ListBuilder<Correction>()
        ..proof = Proof(
          (p) => p
            ..evidenceLevel = 'LOCAL_SIGNED'
            ..anchoringBackend = 'disabled'
            ..payloadHash = 'ab12cd34'
            ..events = ListBuilder<ProofEvent>([
              ProofEvent(
                (e) => e
                  ..eventId = '0xfeed'
                  ..eventType = 9
                  ..status = 'LOCAL'
                  ..evidenceLevel = 'LOCAL_SIGNED'
                  ..transactionHash = '',
              ),
            ]),
        ).toBuilder(),
    );

class _FakeRepo implements TransparencyRepository {
  final periods = <(int?, int?)>[];

  @override
  Future<PaginatedLedgerEntryListList> listLedger(
      {String? cursor, int? year, int? month}) async {
    periods.add((year, month));
    return PaginatedLedgerEntryListList(
      (b) => b
        ..results = ListBuilder<LedgerEntryList>(
            year == null ? [_entry(42, 'LOCAL_SIGNED')] : []),
    );
  }

  @override
  Future<LedgerEntryDetail> fetchLedgerEntry(int id) async => _detail();

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Widget _host(Widget child, _FakeRepo repo) => ProviderScope(
      overrides: [transparencyRepositoryProvider.overrideWithValue(repo)],
      child: MaterialApp(
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        locale: const Locale('vi'),
        home: child,
      ),
    );

void main() {
  testWidgets('list shows entries with evidence badge and period filter',
      (tester) async {
    final repo = _FakeRepo();
    await tester.pumpWidget(_host(const Scaffold(body: LedgerScreen()), repo));
    await tester.pumpAndSettle();
    expect(find.text('Acme Co'), findsOneWidget);
    expect(find.textContaining('Đã ký — chưa bật neo'), findsOneWidget);

    // Choosing a year re-queries with the filter; empty period shows copy.
    final year = DateTime.now().year;
    await tester.tap(find.text('$year'));
    await tester.pumpAndSettle();
    expect(repo.periods.last, (year, null));
    expect(find.text('Không có khoản chi nào trong kỳ này.'), findsOneWidget);
  });

  testWidgets(
      'detail leads with full plain-language story; hashes only in expansion',
      (tester) async {
    final repo = _FakeRepo();
    await tester
        .pumpWidget(_host(const LedgerDetailScreen(entryId: 42), repo));
    await tester.pumpAndSettle();

    // A1: all five story elements present.
    expect(find.text('Cable secured'), findsOneWidget); // what was fixed
    expect(find.text('Worn cable'), findsOneWidget); // why
    expect(find.textContaining('900.000 ₫'), findsOneWidget); // amount
    expect(find.textContaining('Ông Minh'), findsOneWidget); // approvers
    expect(find.textContaining('Bà Hoa'), findsOneWidget);
    expect(find.textContaining('Bà Lan'), findsOneWidget); // payment verification
    expect(find.text('ab12cd34'), findsNothing); // hash hidden until expanded

    await tester.tap(find.text('Chi tiết xác thực'));
    await tester.pumpAndSettle();
    expect(find.text('ab12cd34'), findsOneWidget);
    expect(find.textContaining('0xfeed'), findsOneWidget);
  });
}
