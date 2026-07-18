import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/authenticated_image.dart';
import '../../core/error_retry.dart';
import '../../core/failure.dart';
import '../../core/page_body.dart';
import '../../l10n/app_localizations.dart';
import '../../theme.dart';
import 'reports_repository.dart';

String workStatusLabel(String status, AppLocalizations l10n) =>
    switch (status) {
      'ASSIGNED' => l10n.workStatusAssigned,
      'IN_PROGRESS' => l10n.workStatusInProgress,
      'AWAITING_ACCEPTANCE' => l10n.workStatusAwaiting,
      'ACCEPTED' => l10n.workStatusAccepted,
      'CLOSED' => l10n.workStatusClosed,
      'CANCELLED' => l10n.workStatusCancelled,
      _ => status,
    };

String _date(DateTime value) =>
    DateFormat('dd/MM/yyyy').format(value.toLocal());

class IssueDetailScreen extends ConsumerWidget {
  const IssueDetailScreen({required this.reportId, super.key});
  final int reportId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context)!;
    final detail = ref.watch(reportDetailProvider(reportId));
    return Scaffold(
      appBar: AppBar(title: Text(l10n.issueDetailTitle(reportId))),
      body: PageBody(
        child: switch (detail) {
          AsyncData(:final value) => _body(context, ref, l10n, value),
          AsyncError(:final error) => Center(
            child: ErrorRetry(
              error: error,
              onRetry: () => ref.invalidate(reportDetailProvider(reportId)),
            ),
          ),
          _ => const Center(child: CircularProgressIndicator.adaptive()),
        },
      ),
    );
  }

  Widget _body(
    BuildContext context,
    WidgetRef ref,
    AppLocalizations l10n,
    ReportDetail report,
  ) {
    // Tone only where states differ (pending vs done); default ink elsewhere
    // so color keeps carrying meaning (DESIGN.md Separate States Rule).
    final steps = <(IconData, String, StatusTone?)>[
      (
        Icons.send_outlined,
        '${l10n.timelineSubmitted} · ${_date(report.createdAt)}',
        null,
      ),
      if (report.triageStatus == 'SUCCEEDED' ||
          report.triageStatus == 'NEEDS_MANUAL' ||
          report.cases.isNotEmpty)
        (Icons.fact_check_outlined, l10n.timelineTriageDone, null)
      else
        (Icons.hourglass_empty, l10n.timelineTriagePending, StatusTone.warning),
      for (final caseItem in report.cases) ...[
        (
          Icons.folder_open_outlined,
          l10n.timelineCase(caseItem.category),
          null,
        ),
        for (final work in caseItem.workOrders) ...[
          (
            Icons.build_outlined,
            l10n.timelineWork(
              workStatusLabel(work.status, l10n),
              _date(work.deadlineAt),
            ),
            null,
          ),
          if (work.completedAt != null)
            (
              Icons.check_circle_outline,
              '${l10n.timelineCompleted} · ${_date(work.completedAt!)}',
              StatusTone.success,
            ),
        ],
      ],
    ];
    final rateable = [
      for (final caseItem in report.cases)
        for (final work in caseItem.workOrders)
          if (work.canRate) work,
    ];

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text(report.text, style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 4),
        Text(
          '${report.locationPathSnapshot} · ${report.unitLabel}',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        if (report.photos.isNotEmpty) ...[
          const SizedBox(height: 12),
          SizedBox(
            height: 96,
            child: ListView(
              scrollDirection: Axis.horizontal,
              children: [
                for (final photo in report.photos)
                  Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(10),
                      child: AuthenticatedImage(
                        photo.downloadUrl,
                        width: 96,
                        height: 96,
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ],
        const SizedBox(height: 16),
        for (final (icon, label, tone) in steps)
          ListTile(
            minTileHeight: 48,
            contentPadding: EdgeInsets.zero,
            leading: Icon(
              icon,
              color: tone == null ? null : statusToneColors(context, tone).fg,
            ),
            title: Text(label),
          ),
        for (final work in rateable)
          Padding(
            padding: const EdgeInsets.only(top: 16),
            child: FilledButton.icon(
              icon: const Icon(Icons.star_outline),
              label: Text(l10n.rateWorkCta),
              onPressed: () => _openRateSheet(context, ref, l10n, work.id),
            ),
          ),
      ],
    );
  }

  Future<void> _openRateSheet(
    BuildContext context,
    WidgetRef ref,
    AppLocalizations l10n,
    int workOrderId,
  ) async {
    final rated = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _RateWorkSheet(workOrderId: workOrderId),
    );
    if (rated == true && context.mounted) {
      ref.invalidate(reportDetailProvider(reportId));
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(l10n.rateThanks)));
    }
  }
}

class _RateWorkSheet extends ConsumerStatefulWidget {
  const _RateWorkSheet({required this.workOrderId});
  final int workOrderId;

  @override
  ConsumerState<_RateWorkSheet> createState() => _RateWorkSheetState();
}

class _RateWorkSheetState extends ConsumerState<_RateWorkSheet> {
  int _score = 0;
  final _comment = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _comment.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    return Padding(
      padding: EdgeInsets.only(
        left: 16,
        right: 16,
        top: 16,
        bottom: 16 + MediaQuery.viewInsetsOf(context).bottom,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            l10n.rateWorkTitle,
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 8),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              for (var star = 1; star <= 5; star++)
                IconButton(
                  iconSize: 40, // >=44pt effective target with padding
                  icon: Icon(star <= _score ? Icons.star : Icons.star_border),
                  onPressed: _busy ? null : () => setState(() => _score = star),
                ),
            ],
          ),
          TextField(
            controller: _comment,
            maxLength: 500,
            decoration: InputDecoration(labelText: l10n.rateCommentLabel),
          ),
          if (_error != null) ...[
            const SizedBox(height: 8),
            Text(
              _error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ],
          const SizedBox(height: 8),
          FilledButton(
            onPressed: _busy || _score == 0 ? null : _submit,
            child: Text(l10n.rateSubmit),
          ),
        ],
      ),
    );
  }

  Future<void> _submit() async {
    final l10n = AppLocalizations.of(context)!;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref
          .read(reportsRepositoryProvider)
          .rateWork(
            workOrderId: widget.workOrderId,
            score: _score,
            comment: _comment.text.trim(),
          );
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) {
        setState(() => _error = failureMessage(Failure.fromObject(e), l10n));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
}
