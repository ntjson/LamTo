import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto_api/lamto_api.dart';
import 'package:lamto/features/bills/bill_detail_screen.dart';
import 'package:lamto/features/bills/bills_repository.dart';
import 'package:lamto/l10n/app_localizations.dart';

class _FakeRepo implements BillsRepository {
  @override
  Future<BillDetail> fetchBill(int id) async => BillDetail(
    (builder) => builder
      ..id = id
      ..title = 'Phí 07'
      ..amountVnd = 250000
      ..status = BillStatusEnum.ISSUED
      ..period = ''
      ..issuedAt = DateTime.utc(2026, 7, 1)
      ..note = ''
      ..documentFilename = 'b.pdf'
      ..documentDownloadUrl = '/api/v1/documents/t',
  );

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  testWidgets('issued bill shows its amount, status, and payment action', (
    tester,
  ) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [billsRepositoryProvider.overrideWithValue(_FakeRepo())],
        child: const MaterialApp(
          localizationsDelegates: [
            AppLocalizations.delegate,
            GlobalMaterialLocalizations.delegate,
            GlobalWidgetsLocalizations.delegate,
          ],
          supportedLocales: [Locale('en'), Locale('vi')],
          home: BillDetailScreen(billId: 1),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('250.000 ₫'), findsOneWidget);
    expect(find.text('Unpaid'), findsOneWidget);
    expect(find.text("I've paid"), findsOneWidget);
  });
}
