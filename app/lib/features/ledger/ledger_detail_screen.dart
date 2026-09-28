import 'dart:typed_data';

import 'package:built_value/json_object.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/error_retry.dart';
import '../../core/adaptive_buttons.dart';
import '../../core/adaptive_page_route.dart';
import '../../core/adaptive_scaffold.dart';
import '../../core/failure.dart';
import '../../core/format.dart';
import '../../core/page_body.dart';
import '../../l10n/app_localizations.dart';
import '../../theme.dart';
import '../../widgets/grouped.dart';
import '../documents/document_viewer_screen.dart';
import '../proposals/proposal_detail_screen.dart';
import '../transparency/transparency_repository.dart';
import 'evidence_explorer_tile.dart';
import 'evidence_labels.dart';

String _jsonField(JsonObject? object, String key) =>
    ((object?.value as Map?)?[key] ?? '').toString();

/// Ledger entry detail (spec 6.3(6) / A1): plain language first — what was
/// fixed, why, amount, who approved, payment verification — then expandable
/// proof. Mono identifiers appear ONLY inside the expansion.
class LedgerDetailScreen extends ConsumerWidget {
  const LedgerDetailScreen({required this.entryId, super.key});
  final int entryId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context)!;
    final detail = ref.watch(ledgerDetailProvider(entryId));
    return AdaptiveScaffold(
      title: l10n.ledgerDetailTitle,
      body: PageBody(
        child: switch (detail) {
          AsyncData(:final value) => _body(context, l10n, value),
          AsyncError(:final error) => Center(
            child: ErrorRetry(
              error: error,
              onRetry: () => ref.invalidate(ledgerDetailProvider(entryId)),
            ),
          ),
          _ => const Center(child: CircularProgressIndicator.adaptive()),
        },
      ),
    );
  }

  Widget _body(
    BuildContext context,
    AppLocalizations l10n,
    LedgerEntryDetail entry,
  ) {
    final date = DateFormat('dd/MM/yyyy').format(entry.publishedAt.toLocal());
    final verification = entry.verification;
    // Wire values (serializers.py effective_integrity_status): VERIFIED,
    // MISMATCH, UNAVAILABLE, UNCHECKED. Tampering (MISMATCH) must not dress
    // as routine pending, so it gets its own red conclusion; the amber branch
    // keeps the genuinely-pending states.
    final verified = entry.integrityStatus == 'VERIFIED';
    final mismatch = entry.integrityStatus == 'MISMATCH';
    final theme = Theme.of(context);
    final palette = LamToPalette.of(context);
    final mono = theme.textTheme.bodySmall?.copyWith(
      fontFamily: 'SFMono-Regular',
      fontFamilyFallback: const ['Menlo', 'Roboto Mono', 'monospace'],
    );
    final proposalId = (entry.payload?.value as Map?)?['proposal_id'] as int?;
    final tone = verified
        ? StatusTone.success
        : mismatch
        ? StatusTone.error
        : StatusTone.warning;
    final toneColors = statusToneColors(context, tone);

    final chain = [
      (title: l10n.ledgerChainReports, body: entry.why, child: null),
      (title: l10n.ledgerChainWork, body: entry.whatWasFixed, child: null),
      (
        title: l10n.ledgerChainApprovals,
        body: entry.approvers
            .map(
              (a) => approverLine(
                _jsonField(a, 'role'),
                _jsonField(a, 'name'),
                l10n,
              ),
            )
            .join('\n'),
        child: null,
      ),
      (
        title: l10n.ledgerChainPayment,
        body:
            '${l10n.ledgerAmount}: ${formatVnd(entry.actualCostVnd)}\n'
            '${l10n.ledgerContractor}: ${entry.contractorName}\n'
            '${l10n.ledgerPublishedOn(date)}',
        child: null,
      ),
      (
        title: l10n.ledgerChainVerification,
        body: [
          if (verification != null)
            l10n.ledgerVerifiedBy(verification.verifiedBy),
          integrityStatusLabel(entry.integrityStatus, l10n),
        ].join('\n'),
        child: Padding(
          padding: const EdgeInsets.only(top: 8),
          child: EvidenceBadge(level: entry.proof.evidenceLevel),
        ),
      ),
    ];

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 40),
      children: [
        // The verdict first: what a resident needs to know before any proof.
        Semantics(
          container: true,
          child: InsetGroup(
            padding: const EdgeInsets.all(20),
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    width: 48,
                    height: 48,
                    decoration: BoxDecoration(
                      color: toneColors.bg,
                      shape: BoxShape.circle,
                    ),
                    child: Icon(
                      verified
                          ? Icons.verified_outlined
                          : mismatch
                          ? Icons.error_outline
                          : Icons.pending_outlined,
                      color: toneColors.fg,
                      size: 28,
                    ),
                  ),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          verified
                              ? l10n.ledgerConclusionVerified
                              : mismatch
                              ? l10n.ledgerConclusionMismatch
                              : l10n.ledgerConclusionUnverified,
                          style: theme.textTheme.titleLarge?.copyWith(
                            color: toneColors.fg,
                          ),
                        ),
                        const SizedBox(height: 6),
                        Text(
                          verified
                              ? l10n.ledgerConclusionVerifiedBody
                              : mismatch
                              ? l10n.ledgerConclusionMismatchBody
                              : l10n.ledgerConclusionUnverifiedBody,
                          style: theme.textTheme.bodyMedium,
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        InsetGroup(
          children: [
            InfoRow(
              label: l10n.ledgerAmount,
              value: formatVnd(entry.actualCostVnd),
              valueStyle: heroAmountStyle(context)?.copyWith(fontSize: 26),
            ),
            InfoRow(label: l10n.ledgerContractor, value: entry.contractorName),
            if (proposalId != null)
              ListTile(
                minTileHeight: 52,
                title: Text(l10n.proposalViewFromLedger),
                trailing: Icon(
                  Icons.chevron_right,
                  color: palette.muted.withValues(alpha: 0.6),
                ),
                onTap: () => Navigator.push(
                  context,
                  adaptivePageRoute(
                    builder: (_) =>
                        ProposalDetailScreen(proposalId: proposalId),
                  ),
                ),
              ),
          ],
        ),
        const SizedBox(height: 28),
        SectionHeader(l10n.ledgerChainTitle),
        Padding(
          padding: const EdgeInsets.fromLTRB(4, 0, 4, 12),
          child: Text(
            l10n.ledgerChainHint,
            style: theme.textTheme.bodyMedium?.copyWith(color: palette.muted),
          ),
        ),
        InsetGroup(
          padding: const EdgeInsets.all(16),
          children: [
            Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                for (final (index, step) in chain.indexed)
                  _ChainStep(
                    number: index + 1,
                    title: step.title,
                    body: step.body,
                    isLast: index == chain.length - 1,
                    child: step.child,
                  ),
              ],
            ),
          ],
        ),
        const SizedBox(height: 28),
        SectionHeader(l10n.ledgerDocuments),
        if (entry.documents.isNotEmpty)
          InsetGroup(
            dividerIndent: 68,
            children: [
              for (final doc in entry.documents) _DocumentTile(document: doc),
            ],
          ),
        const SizedBox(height: 16),
        if (entry.explorerUrl != null && entry.explorerUrl!.isNotEmpty)
          InsetGroup(children: [EvidenceExplorerTile(url: entry.explorerUrl!)])
        else
          InsetGroup(
            children: [
              ExpansionTile(
                title: Text(
                  l10n.ledgerProofTitle,
                  style: theme.textTheme.bodyLarge,
                ),
                childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                expandedCrossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(l10n.ledgerProofHash, style: theme.textTheme.bodySmall),
                  const SizedBox(height: 2),
                  Text(entry.proof.payloadHash, style: mono),
                  const SizedBox(height: 12),
                  Text(
                    l10n.ledgerProofEvents,
                    style: theme.textTheme.labelLarge,
                  ),
                  for (final event in entry.proof.events)
                    Padding(
                      padding: const EdgeInsets.only(top: 8),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(event.eventId, style: mono),
                          if (event.transactionHash.isNotEmpty)
                            Text(event.transactionHash, style: mono),
                          const SizedBox(height: 4),
                          EvidenceBadge(level: event.evidenceLevel),
                        ],
                      ),
                    ),
                ],
              ),
            ],
          ),
        if (entry.corrections.isNotEmpty) ...[
          const SizedBox(height: 28),
          SectionHeader(l10n.ledgerCorrections),
          InsetGroup(
            children: [
              for (final correction in entry.corrections)
                ListTile(
                  minTileHeight: 52,
                  leading: const Icon(Icons.change_circle_outlined),
                  title: Text(_jsonField(correction, 'reason')),
                  subtitle: Text(l10n.ledgerCorrectionRecorded),
                ),
            ],
          ),
        ],
      ],
    );
  }
}

class _ChainStep extends StatelessWidget {
  const _ChainStep({
    required this.number,
    required this.title,
    required this.body,
    required this.isLast,
    this.child,
  });

  final int number;
  final String title;
  final String body;
  final bool isLast;
  final Widget? child;

  @override
  Widget build(BuildContext context) {
    final palette = LamToPalette.of(context);
    final theme = Theme.of(context);
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            width: 28,
            child: Column(
              children: [
                Container(
                  width: 28,
                  height: 28,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    color: palette.primarySoft,
                    shape: BoxShape.circle,
                  ),
                  child: Text(
                    '$number',
                    style: theme.textTheme.labelLarge?.copyWith(
                      color: palette.primary,
                    ),
                  ),
                ),
                if (!isLast)
                  Expanded(
                    child: Container(
                      width: 2,
                      margin: const EdgeInsets.symmetric(vertical: 4),
                      color: palette.border,
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Padding(
              padding: EdgeInsets.only(top: 3, bottom: isLast ? 0 : 20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: theme.textTheme.bodyLarge?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  if (body.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(body, style: theme.textTheme.bodyMedium),
                  ],
                  ?child,
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _DocumentTile extends ConsumerStatefulWidget {
  const _DocumentTile({required this.document});
  final LedgerDocument document;

  @override
  ConsumerState<_DocumentTile> createState() => _DocumentTileState();
}

class _DocumentTileState extends ConsumerState<_DocumentTile> {
  bool _loading = false;
  Object? _error;

  String _errorMessage(AppLocalizations l10n) {
    final failure = Failure.fromObject(_error!);
    return switch (failure.code) {
      'network_error' => l10n.ledgerDocumentOffline,
      'not_authenticated' ||
      'permission_denied' => l10n.ledgerDocumentUnauthorized,
      _ => l10n.ledgerDocumentFailure,
    };
  }

  Future<void> _open() async {
    if (_loading) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    final Uint8List bytes;
    try {
      bytes = await ref
          .read(transparencyRepositoryProvider)
          .fetchDocument(widget.document.downloadUrl);
    } catch (error) {
      // Fetch failures belong to this row, with a retry. Render failures
      // belong to the viewer, so it is opened outside this try.
      if (mounted) setState(() => _error = error);
      return;
    } finally {
      if (mounted) setState(() => _loading = false);
    }
    if (!mounted) return;
    await showDocumentViewer(
      context,
      bytes: bytes,
      filename: widget.document.filename,
      contentType: widget.document.contentType,
    );
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    return ListTile(
      minTileHeight: 56,
      contentPadding: EdgeInsets.zero,
      leading: const IconWell(Icons.description_outlined),
      title: Text(ledgerDocumentKindLabel(widget.document.kind, l10n)),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(widget.document.filename),
          Text(_error == null ? l10n.ledgerDocumentOpen : _errorMessage(l10n)),
          if (_error != null)
            Align(
              alignment: Alignment.centerLeft,
              child: AdaptiveTextButton(
                onPressed: _open,
                child: Text(l10n.commonRetry),
              ),
            ),
        ],
      ),
      trailing: _loading
          ? const SizedBox.square(
              dimension: 24,
              child: CircularProgressIndicator.adaptive(strokeWidth: 2),
            )
          : _error == null
          ? const Icon(Icons.chevron_right)
          : null,
      onTap: _loading ? null : _open,
    );
  }
}
