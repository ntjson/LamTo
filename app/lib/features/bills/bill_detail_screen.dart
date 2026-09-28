import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/adaptive_buttons.dart';
import '../../core/adaptive_page_route.dart';
import '../../core/adaptive_scaffold.dart';
import '../../core/error_retry.dart';
import '../../core/format.dart';
import '../../core/page_body.dart';
import '../../l10n/app_localizations.dart';
import '../../theme.dart';
import '../../widgets/grouped.dart';
import '../documents/document_viewer_screen.dart';
import 'bill_scan_screen.dart';
import 'bills_repository.dart';

class BillDetailScreen extends ConsumerStatefulWidget {
  const BillDetailScreen({required this.billId, super.key});

  final int billId;

  @override
  ConsumerState<BillDetailScreen> createState() => _BillDetailScreenState();
}

class _BillDetailScreenState extends ConsumerState<BillDetailScreen> {
  bool _openingDocument = false;

  /// Outcome of the scan flow, rendered as an inline notice (a SnackBar
  /// would never appear under the iOS Cupertino shell).
  BillScanResult? _scanResult;

  /// Inline document-open failure, shown under the document row.
  bool _documentFailed = false;

  Future<void> _openDocument(BillDetail bill) async {
    if (_openingDocument) return;
    setState(() {
      _openingDocument = true;
      _documentFailed = false;
    });
    final Uint8List bytes;
    try {
      bytes = await ref
          .read(billsRepositoryProvider)
          .fetchDocument(bill.documentDownloadUrl);
    } catch (_) {
      // Fetch failures belong to this row. Render failures belong to the
      // viewer, so it is opened outside this try.
      if (mounted) setState(() => _documentFailed = true);
      return;
    } finally {
      if (mounted) setState(() => _openingDocument = false);
    }
    if (!mounted) return;
    await showDocumentViewer(
      context,
      bytes: bytes,
      filename: bill.documentFilename,
    );
  }

  Future<void> _scanPayment() async {
    final result = await Navigator.of(context).push(
      adaptivePageRoute<BillScanResult>(
        builder: (_) => BillScanScreen(billId: widget.billId),
      ),
    );
    // Back-navigation without a scan returns null: no notice.
    if (result != null && mounted) setState(() => _scanResult = result);
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final detail = ref.watch(billDetailProvider(widget.billId));
    return AdaptiveScaffold(
      title: l10n.billsTitle,
      body: PageBody(
        child: switch (detail) {
          AsyncData(:final value) => _body(context, l10n, value),
          AsyncError(:final error) => Center(
            child: ErrorRetry(
              error: error,
              onRetry: () => ref.invalidate(billDetailProvider(widget.billId)),
            ),
          ),
          _ => const Center(child: CircularProgressIndicator.adaptive()),
        },
      ),
    );
  }

  Widget _body(BuildContext context, AppLocalizations l10n, BillDetail bill) {
    final issued = bill.status == BillStatusEnum.ISSUED;
    final paid = bill.status == BillStatusEnum.PAID;
    final voided = bill.status == BillStatusEnum.VOID;
    final dueDate = bill.dueDate?.toLocal();
    // DESIGN.md deadline vocabulary: unpaid past its due day is Mismatch Red
    // with the explicit word; unpaid-but-not-due keeps the quiet treatment.
    final now = DateTime.now();
    final overdue =
        issued &&
        dueDate != null &&
        DateTime(
          now.year,
          now.month,
          now.day,
        ).isAfter(DateTime(dueDate.year, dueDate.month, dueDate.day));
    final theme = Theme.of(context);
    final palette = LamToPalette.of(context);

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
      children: [
        // Scan outcome where the eye lands on return, above the refreshed
        // status chip it explains. Only conclusive results pop the scanner.
        if (_scanResult case final scan?) ...[
          StatusNotice(
            tone: scan == BillScanResult.recorded
                ? StatusTone.success
                : StatusTone.error,
            message: scan == BillScanResult.recorded
                ? l10n.billPaymentRecorded
                : l10n.billPaymentVoided,
          ),
          const SizedBox(height: 16),
        ],
        InsetGroup(
          padding: const EdgeInsets.all(20),
          children: [
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(bill.title, style: theme.textTheme.titleMedium),
                const SizedBox(height: 6),
                Text(
                  formatVnd(bill.amountVnd),
                  style: heroAmountStyle(context),
                ),
                const SizedBox(height: 12),
                StatusChip(
                  tone: paid
                      ? StatusTone.success
                      : voided
                      ? StatusTone.error
                      : StatusTone.warning,
                  icon: paid
                      ? Icons.check_circle_outline
                      : voided
                      ? Icons.cancel_outlined
                      : Icons.schedule,
                  label: paid
                      ? l10n.billStatusPaid
                      : voided
                      ? l10n.billStatusVoid
                      : l10n.billStatusIssued,
                ),
              ],
            ),
          ],
        ),
        const SizedBox(height: 16),
        InsetGroup(
          dividerIndent: dueDate == null ? 68 : 16,
          children: [
            if (dueDate != null)
              ListTile(
                minTileHeight: 52,
                title: Text(l10n.billDueLabel),
                trailing: overdue
                    ? StatusChip(
                        tone: StatusTone.error,
                        icon: Icons.event_busy_outlined,
                        label:
                            '${DateFormat('dd/MM/yyyy').format(dueDate)}'
                            ' · ${l10n.billOverdue}',
                      )
                    : Text(
                        DateFormat('dd/MM/yyyy').format(dueDate),
                        style: theme.textTheme.bodyLarge,
                      ),
              ),
            ListTile(
              minTileHeight: 60,
              leading: const IconWell(Icons.description_outlined),
              title: Text(l10n.billViewFile),
              subtitle: Text(bill.documentFilename),
              trailing: _openingDocument
                  ? const SizedBox.square(
                      dimension: 24,
                      child: CircularProgressIndicator.adaptive(strokeWidth: 2),
                    )
                  : Icon(
                      Icons.chevron_right,
                      color: palette.muted.withValues(alpha: 0.6),
                    ),
              onTap: _openingDocument ? null : () => _openDocument(bill),
            ),
            if (bill.note.isNotEmpty)
              Padding(
                padding: const EdgeInsets.all(16),
                child: Text(bill.note),
              ),
          ],
        ),
        if (_documentFailed) ...[
          const SizedBox(height: 8),
          StatusNotice(
            tone: StatusTone.error,
            message: l10n.ledgerDocumentFailure,
          ),
        ],
        if (issued) ...[
          const SizedBox(height: 24),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 4),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(l10n.billPayExplainer, style: theme.textTheme.bodyMedium),
                const SizedBox(height: 8),
                Text(l10n.billPayStep1, style: theme.textTheme.bodySmall),
                Text(l10n.billPayStep2, style: theme.textTheme.bodySmall),
              ],
            ),
          ),
          const SizedBox(height: 16),
          AdaptiveFilledButton(
            onPressed: _scanPayment,
            icon: const Icon(Icons.qr_code_scanner),
            child: Text(l10n.billPayAction),
          ),
        ],
      ],
    );
  }
}
