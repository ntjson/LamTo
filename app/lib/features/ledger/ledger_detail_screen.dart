import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/failure.dart';
import '../../core/format.dart';
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
      appBar: AppBar(title: Text(l10n.ledgerTitle)),
      body: switch (detail) {
        AsyncData(:final value) => _body(context, l10n, value),
        AsyncError(:final error) => Center(
            child: Text(failureMessage(Failure.fromObject(error), l10n)),
          ),
        _ => const Center(child: CircularProgressIndicator.adaptive()),
      },
    );
  }

  Widget _body(
      BuildContext context, AppLocalizations l10n, LedgerEntryDetail entry) {
    final date = DateFormat('dd/MM/yyyy').format(entry.publishedAt.toLocal());
    final verification = entry.verification;
    final mono = Theme.of(context)
        .textTheme
        .bodySmall
        ?.copyWith(fontFamily: 'monospace');
    final titleStyle = Theme.of(context).textTheme.titleMedium;

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        // A1 plain-language story: what / why / amount / approvers / payment.
        if (entry.whatWasFixed.isNotEmpty) ...[
          Text(l10n.ledgerWhatFixed, style: titleStyle),
          const SizedBox(height: 4),
          Text(entry.whatWasFixed,
              style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 12),
        ],
        if (entry.why.isNotEmpty) ...[
          Text(l10n.ledgerWhy, style: titleStyle),
          const SizedBox(height: 4),
          Text(entry.why),
          const SizedBox(height: 12),
        ],
        Text(l10n.ledgerContractor, style: titleStyle),
        const SizedBox(height: 4),
        Text(entry.contractorName),
        const SizedBox(height: 4),
        Text(l10n.ledgerPublishedOn(date)),
        const SizedBox(height: 12),
        Text('${l10n.ledgerAmount}: ${formatVnd(entry.actualCostVnd)}',
            style: titleStyle),
        if (entry.approvers.isNotEmpty) ...[
          const SizedBox(height: 12),
          Text(l10n.ledgerApprovers, style: titleStyle),
          const SizedBox(height: 4),
          for (final a in entry.approvers)
            Padding(
              padding: const EdgeInsets.only(bottom: 2),
              child: Text(approverLine(a.role, a.name, l10n)),
            ),
        ],
        const SizedBox(height: 8),
        Text(
          verification != null
              ? l10n.ledgerVerifiedBy(verification.verifiedBy)
              : l10n.ledgerNotVerified,
        ),
        const SizedBox(height: 8),
        Text(integrityStatusLabel(entry.integrityStatus, l10n)),
        const SizedBox(height: 12),
        EvidenceBadge(level: entry.proof.evidenceLevel),
        if (entry.corrections.isNotEmpty) ...[
          const SizedBox(height: 16),
          Text(l10n.ledgerCorrections, style: titleStyle),
          for (final correction in entry.corrections)
            ListTile(
              minTileHeight: 48,
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.change_circle_outlined),
              title: Text(correction.reason,
                  maxLines: 2, overflow: TextOverflow.ellipsis),
              subtitle: Text(correction.status),
            ),
        ],
        if (entry.redactedDocuments.isNotEmpty) ...[
          const SizedBox(height: 16),
          Text(l10n.ledgerDocuments, style: titleStyle),
          for (final doc in entry.redactedDocuments)
            ListTile(
              minTileHeight: 48,
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.description_outlined),
              title: Text(doc.label),
              subtitle: Text(doc.filename,
                  maxLines: 1, overflow: TextOverflow.ellipsis),
            ),
        ],
        const SizedBox(height: 16),
        // Expandable proof: the only mono region (DESIGN.md Human Before Hash).
        ExpansionTile(
          tilePadding: EdgeInsets.zero,
          title: Text(l10n.ledgerProofTitle),
          children: [
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: Text(l10n.ledgerProofHash),
              subtitle: Text(entry.proof.payloadHash, style: mono),
            ),
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text(l10n.ledgerProofEvents,
                    style: Theme.of(context).textTheme.labelLarge),
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
      ],
    );
  }
}
