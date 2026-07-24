import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../../l10n/app_localizations.dart';
import 'bill_qr.dart';
import 'bills_repository.dart';

enum BillScanResult { invalidQr, recorded, voided, error }

void invalidateBillViews(ProviderContainer container, int billId) {
  container.invalidate(billDetailProvider(billId));
  container.invalidate(billsProvider);
  container.invalidate(newestUnpaidBillProvider);
}

Future<BillScanResult> handleScannedCode(
  ProviderContainer container,
  int billId,
  String raw,
) async {
  final reference = billReferenceFromQr(raw);
  if (reference == null) return BillScanResult.invalidQr;
  try {
    await container
        .read(billsRepositoryProvider)
        .confirmPayment(billId, reference);
    return BillScanResult.recorded;
  } on DioException catch (error) {
    return error.response?.statusCode == 409
        ? BillScanResult.voided
        : BillScanResult.error;
  } catch (_) {
    return BillScanResult.error;
  }
}

class BillScanScreen extends ConsumerStatefulWidget {
  const BillScanScreen({required this.billId, super.key});

  final int billId;

  @override
  ConsumerState<BillScanScreen> createState() => _BillScanScreenState();
}

class _BillScanScreenState extends ConsumerState<BillScanScreen> {
  bool _handling = false;

  Future<void> _onDetect(BarcodeCapture capture) async {
    if (_handling) return;
    String? raw;
    for (final barcode in capture.barcodes) {
      if (barcode.rawValue case final value?) {
        raw = value;
        break;
      }
    }
    if (raw == null) return;
    setState(() => _handling = true);

    final result = await handleScannedCode(
      ProviderScope.containerOf(context),
      widget.billId,
      raw,
    );
    if (!mounted) return;

    final l10n = AppLocalizations.of(context)!;
    final messenger = ScaffoldMessenger.of(context);
    if (result != BillScanResult.invalidQr) {
      invalidateBillViews(ProviderScope.containerOf(context), widget.billId);
    }
    switch (result) {
      case BillScanResult.invalidQr:
        messenger.showSnackBar(SnackBar(content: Text(l10n.billInvalidQr)));
        setState(() => _handling = false);
      case BillScanResult.recorded:
        Navigator.of(context).pop();
        messenger.showSnackBar(
          SnackBar(content: Text(l10n.billPaymentRecorded)),
        );
      case BillScanResult.voided:
        Navigator.of(context).pop();
        messenger.showSnackBar(SnackBar(content: Text(l10n.billPaymentVoided)));
      case BillScanResult.error:
        Navigator.of(context).pop();
        messenger.showSnackBar(
          SnackBar(content: Text(l10n.billPaymentUnknown)),
        );
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    return Scaffold(
      appBar: AppBar(title: Text(l10n.billScanTitle)),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Text(l10n.billScanInstruction, textAlign: TextAlign.center),
          ),
          Expanded(
            child: Semantics(
              label: l10n.billScanInstruction,
              child: MobileScanner(
                onDetect: _onDetect,
                errorBuilder: (context, error) => Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Text(
                      l10n.billCameraUnavailable,
                      textAlign: TextAlign.center,
                    ),
                  ),
                ),
              ),
            ),
          ),
          if (_handling)
            const Padding(
              padding: EdgeInsets.all(16),
              child: CircularProgressIndicator.adaptive(),
            ),
        ],
      ),
    );
  }
}
