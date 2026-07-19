import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:lamto_api/lamto_api.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

import '../../core/error_retry.dart';
import '../../core/failure.dart';
import '../../core/format.dart';
import '../../core/page_body.dart';
import '../../l10n/app_localizations.dart';
import '../transparency/transparency_repository.dart';
import 'evidence_labels.dart';

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
    return Scaffold(
      appBar: AppBar(title: Text(l10n.ledgerDetailTitle)),
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
    final verified =
        verification?.decision == 'VERIFIED' &&
        entry.integrityStatus == 'VERIFIED';
    final mono = Theme.of(
      context,
    ).textTheme.bodySmall?.copyWith(fontFamily: 'monospace');
    final titleStyle = Theme.of(context).textTheme.titleMedium;
    final conclusionColor = verified
        ? Theme.of(context).colorScheme.primary
        : Theme.of(context).colorScheme.error;

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Semantics(
          container: true,
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(
                verified ? Icons.verified_outlined : Icons.pending_outlined,
                color: conclusionColor,
                size: 32,
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      verified
                          ? l10n.ledgerConclusionVerified
                          : l10n.ledgerConclusionUnverified,
                      style: Theme.of(context).textTheme.titleLarge?.copyWith(
                        color: conclusionColor,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      verified
                          ? l10n.ledgerConclusionVerifiedBody
                          : l10n.ledgerConclusionUnverifiedBody,
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 24),
        ExpansionTile(
          tilePadding: EdgeInsets.zero,
          childrenPadding: const EdgeInsets.only(bottom: 16),
          title: Text(l10n.ledgerChainTitle, style: titleStyle),
          subtitle: Text(l10n.ledgerChainHint),
          children: [
            _ChainStep(
              number: 1,
              title: l10n.ledgerChainReports,
              body: entry.why,
            ),
            _ChainStep(
              number: 2,
              title: l10n.ledgerChainWork,
              body: entry.whatWasFixed,
            ),
            _ChainStep(
              number: 3,
              title: l10n.ledgerChainApprovals,
              body: entry.approvers
                  .map((a) => approverLine(a.role, a.name, l10n))
                  .join('\n'),
            ),
            _ChainStep(
              number: 4,
              title: l10n.ledgerChainPayment,
              body:
                  '${l10n.ledgerAmount}: ${formatVnd(entry.actualCostVnd)}\n'
                  '${l10n.ledgerContractor}: ${entry.contractorName}\n'
                  '${l10n.ledgerPublishedOn(date)}',
              child: entry.redactedDocuments.isEmpty
                  ? null
                  : Column(
                      children: [
                        for (final doc in entry.redactedDocuments)
                          _DocumentTile(document: doc),
                      ],
                    ),
            ),
            _ChainStep(
              number: 5,
              title: l10n.ledgerChainVerification,
              body: [
                verification != null
                    ? l10n.ledgerVerifiedBy(verification.verifiedBy)
                    : l10n.ledgerNotVerified,
                integrityStatusLabel(entry.integrityStatus, l10n),
              ].join('\n'),
              child: Padding(
                padding: const EdgeInsets.only(top: 8),
                child: EvidenceBadge(level: entry.proof.evidenceLevel),
              ),
            ),
            const Divider(height: 32),
            Align(
              alignment: Alignment.centerLeft,
              child: Text(l10n.ledgerProofTitle, style: titleStyle),
            ),
            const SizedBox(height: 8),
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: Text(l10n.ledgerProofHash),
              subtitle: Text(entry.proof.payloadHash, style: mono),
            ),
            Align(
              alignment: Alignment.centerLeft,
              child: Text(
                l10n.ledgerProofEvents,
                style: Theme.of(context).textTheme.labelLarge,
              ),
            ),
            for (final event in entry.proof.events)
              ListTile(
                contentPadding: EdgeInsets.zero,
                title: Text(event.eventId, style: mono),
                subtitle: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (event.transactionHash.isNotEmpty)
                      Text(event.transactionHash, style: mono),
                    const SizedBox(height: 4),
                    EvidenceBadge(level: event.evidenceLevel),
                  ],
                ),
              ),
          ],
        ),
        if (entry.corrections.isNotEmpty) ...[
          const SizedBox(height: 24),
          Text(l10n.ledgerCorrections, style: titleStyle),
          for (final correction in entry.corrections)
            ListTile(
              minTileHeight: 48,
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.change_circle_outlined),
              title: Text(correction.reason),
              subtitle: Text(correction.status),
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
    this.child,
  });

  final int number;
  final String title;
  final String body;
  final Widget? child;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          CircleAvatar(
            radius: 16,
            backgroundColor: Theme.of(context).colorScheme.secondaryContainer,
            foregroundColor: Theme.of(context).colorScheme.onSecondaryContainer,
            child: Text('$number'),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: Theme.of(context).textTheme.titleMedium),
                if (body.isNotEmpty) ...[const SizedBox(height: 4), Text(body)],
                ?child,
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _DocumentTile extends ConsumerStatefulWidget {
  const _DocumentTile({required this.document});
  final RedactedDocument document;

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
    File? file;
    try {
      final bytes = await ref
          .read(transparencyRepositoryProvider)
          .fetchDocument(widget.document.downloadUrl);
      final directory = await getTemporaryDirectory();
      final safeName = widget.document.filename.replaceAll(
        RegExp(r'[/\\]|\.\.'),
        '_',
      );
      file = File(
        '${directory.path}/${safeName.isEmpty ? 'document' : safeName}',
      );
      await file.writeAsBytes(bytes, flush: true);
      if (!mounted) return;
      final box = context.findRenderObject() as RenderBox?;
      await SharePlus.instance.share(
        ShareParams(
          files: [XFile(file.path)],
          sharePositionOrigin: box != null && box.hasSize
              ? box.localToGlobal(Offset.zero) & box.size
              : null,
        ),
      );
    } catch (error) {
      if (mounted) setState(() => _error = error);
    } finally {
      try {
        if (await file?.exists() ?? false) await file!.delete();
      } catch (_) {}
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    return ListTile(
      minTileHeight: 56,
      contentPadding: EdgeInsets.zero,
      leading: const Icon(Icons.description_outlined),
      title: Text(widget.document.label),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(widget.document.filename),
          Text(_error == null ? l10n.ledgerDocumentOpen : _errorMessage(l10n)),
          if (_error != null)
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton(
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
          ? const Icon(Icons.open_in_new)
          : null,
      onTap: _loading ? null : _open,
    );
  }
}
