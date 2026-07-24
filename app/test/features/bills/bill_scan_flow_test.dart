import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/features/bills/bill_scan_screen.dart';
import 'package:lamto/features/bills/bills_repository.dart';
import 'package:lamto_api/lamto_api.dart';

class _Repo implements BillsRepository {
  _Repo({this.error});

  final Object? error;
  String? confirmedReference;

  @override
  Future<BillDetail> confirmPayment(int id, String reference) async {
    confirmedReference = reference;
    if (error case final error?) throw error;
    return BillDetail(
      (builder) => builder
        ..id = id
        ..title = 'Bill'
        ..amountVnd = 1
        ..status = BillStatusEnum.PAID
        ..period = ''
        ..issuedAt = DateTime.utc(2026, 7, 24)
        ..note = ''
        ..documentFilename = 'bill.pdf'
        ..documentDownloadUrl = '/api/v1/documents/token',
    );
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

ProviderContainer _container(_Repo repo) => ProviderContainer(
  overrides: [billsRepositoryProvider.overrideWithValue(repo)],
);

void main() {
  test(
    'refreshes detail, list, and Home bill state before leaving scan',
    () async {
      var detailLoads = 0;
      var listLoads = 0;
      var homeLoads = 0;
      final container = ProviderContainer(
        overrides: [
          billDetailProvider(1).overrideWith((ref) async {
            detailLoads++;
            return _Repo().confirmPayment(1, 'ref');
          }),
          billsProvider.overrideWith((ref) async {
            listLoads++;
            return [];
          }),
          newestUnpaidBillProvider.overrideWith((ref) async {
            homeLoads++;
            return null;
          }),
        ],
      );
      addTearDown(container.dispose);
      final subscriptions = [
        container.listen(billDetailProvider(1), (_, _) {}),
        container.listen(billsProvider, (_, _) {}),
        container.listen(newestUnpaidBillProvider, (_, _) {}),
      ];
      addTearDown(() {
        for (final subscription in subscriptions) {
          subscription.close();
        }
      });
      await Future.wait([
        container.read(billDetailProvider(1).future),
        container.read(billsProvider.future),
        container.read(newestUnpaidBillProvider.future),
      ]);

      invalidateBillViews(container, 1);
      await Future.wait([
        container.read(billDetailProvider(1).future),
        container.read(billsProvider.future),
        container.read(newestUnpaidBillProvider.future),
      ]);

      expect((detailLoads, listLoads, homeLoads), (2, 2, 2));
    },
  );

  test('rejects a non-LamTo QR without confirming payment', () async {
    final repo = _Repo();
    final container = _container(repo);
    addTearDown(container.dispose);

    expect(
      await handleScannedCode(container, 1, 'https://example.test'),
      BillScanResult.invalidQr,
    );
    expect(repo.confirmedReference, isNull);
  });

  test('confirms a LamTo QR using only its bill reference', () async {
    final repo = _Repo();
    final container = _container(repo);
    addTearDown(container.dispose);

    expect(
      await handleScannedCode(container, 7, 'lamto-bill:ref-9'),
      BillScanResult.recorded,
    );
    expect(repo.confirmedReference, 'ref-9');
  });

  test(
    'distinguishes a voided bill from an unknown confirmation result',
    () async {
      final request = RequestOptions(path: '/bills/1/confirm-payment');
      final voided = _Repo(
        error: DioException(
          requestOptions: request,
          response: Response<void>(requestOptions: request, statusCode: 409),
        ),
      );
      final failed = _Repo(error: DioException(requestOptions: request));
      final voidedContainer = _container(voided);
      final failedContainer = _container(failed);
      addTearDown(voidedContainer.dispose);
      addTearDown(failedContainer.dispose);

      expect(
        await handleScannedCode(voidedContainer, 1, 'lamto-bill:void'),
        BillScanResult.voided,
      );
      expect(
        await handleScannedCode(failedContainer, 1, 'lamto-bill:retry'),
        BillScanResult.error,
      );
    },
  );
}
