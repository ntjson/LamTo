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
        for (final update in caseItem.updates)
          (
            Icons.build_outlined,
            l10n.timelineWork(update.result, _date(caseItem.deadlineAt)),
            null,
          ),
        if (caseItem.completedAt != null)
          (
            Icons.check_circle_outline,
            '${l10n.timelineCompleted} · ${_date(caseItem.completedAt!)}',
            StatusTone.success,
          ),
      ],
    ];
    final rateable = report.cases.where((caseItem) => caseItem.canRate);
    final infoRequestMessage = report.openInfoRequest?['message']?.value;

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text(report.text, style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 4),
        Text(
          '${report.locationPathSnapshot} · ${report.unitLabel}',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        if (report.status == StatusEnum.NEEDS_INFO &&
            infoRequestMessage is String) ...[
          const SizedBox(height: 16),
          _InfoRequestBanner(
            message: infoRequestMessage,
            onReply: () => _showReplySheet(context, ref, report.id),
          ),
        ],
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
        for (final caseItem in rateable)
          Padding(
            padding: const EdgeInsets.only(top: 16),
            child: FilledButton.icon(
              icon: const Icon(Icons.star_outline),
              label: Text(l10n.rateWorkCta),
              onPressed: () => _openRateSheet(context, ref, l10n, caseItem.id),
            ),
          ),
      ],
    );
  }

  Future<void> _openRateSheet(
    BuildContext context,
    WidgetRef ref,
    AppLocalizations l10n,
    int caseId,
  ) async {
    final rated = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _RateCaseSheet(caseId: caseId),
    );
    if (rated == true && context.mounted) {
      ref.invalidate(reportDetailProvider(reportId));
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(l10n.rateThanks)));
    }
  }

  Future<void> _showReplySheet(
    BuildContext context,
    WidgetRef ref,
    int reportId,
  ) async {
    final replied = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _InfoReplySheet(reportId: reportId),
    );
    if (replied == true && context.mounted) {
      ref.invalidate(reportDetailProvider(reportId));
    }
  }
}

class _InfoRequestBanner extends StatelessWidget {
  const _InfoRequestBanner({required this.message, required this.onReply});

  final String message;
  final VoidCallback onReply;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final colors = statusToneColors(context, StatusTone.warning);
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: colors.bg,
        border: Border.all(color: colors.fg),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.info_outline, color: colors.fg),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  l10n.infoRequestTitle,
                  style: Theme.of(context).textTheme.titleSmall,
                ),
                const SizedBox(height: 4),
                Text(message),
                const SizedBox(height: 8),
                FilledButton(
                  onPressed: onReply,
                  child: Text(l10n.infoReplySubmit),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _InfoReplySheet extends ConsumerStatefulWidget {
  const _InfoReplySheet({required this.reportId});

  final int reportId;

  @override
  ConsumerState<_InfoReplySheet> createState() => _InfoReplySheetState();
}

class _InfoReplySheetState extends ConsumerState<_InfoReplySheet> {
  final _text = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _text.dispose();
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
            l10n.infoRequestTitle,
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 8),
          TextField(
            controller: _text,
            minLines: 3,
            maxLines: 5,
            enabled: !_busy,
            onChanged: (_) => setState(() {}),
            decoration: InputDecoration(hintText: l10n.infoReplyHint),
          ),
          const SizedBox(height: 8),
          Text(l10n.infoReplyPhotosHint),
          if (_error != null) ...[
            const SizedBox(height: 8),
            Text(
              _error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ],
          const SizedBox(height: 8),
          FilledButton(
            onPressed: _busy || _text.text.trim().isEmpty ? null : _submit,
            child: Text(l10n.infoReplySubmit),
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
          .replyInfo(reportId: widget.reportId, text: _text.text.trim());
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

class _RateCaseSheet extends ConsumerStatefulWidget {
  const _RateCaseSheet({required this.caseId});
  final int caseId;

  @override
  ConsumerState<_RateCaseSheet> createState() => _RateCaseSheetState();
}

class _RateCaseSheetState extends ConsumerState<_RateCaseSheet> {
  bool _satisfied = true;
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
          SegmentedButton<bool>(
            segments: [
              ButtonSegment(value: true, label: Text(l10n.rateSatisfied)),
              ButtonSegment(value: false, label: Text(l10n.rateNotSatisfied)),
            ],
            selected: {_satisfied},
            onSelectionChanged: _busy
                ? null
                : (selection) => setState(() => _satisfied = selection.first),
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
            onPressed: _busy ? null : _submit,
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
          .rateCase(
            caseId: widget.caseId,
            satisfied: _satisfied,
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
