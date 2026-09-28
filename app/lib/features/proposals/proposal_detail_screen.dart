import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/error_retry.dart';
import '../../core/adaptive_buttons.dart';
import '../../core/adaptive_scaffold.dart';
import '../../core/failure.dart';
import '../../core/format.dart';
import '../../core/page_body.dart';
import '../../l10n/app_localizations.dart';
import '../../theme.dart';
import '../../widgets/grouped.dart';
import '../ledger/evidence_explorer_tile.dart';
import '../ledger/evidence_labels.dart';
import 'proposals_list_screen.dart';
import 'proposals_repository.dart';

class ProposalDetailScreen extends ConsumerStatefulWidget {
  const ProposalDetailScreen({required this.proposalId, super.key});

  final int proposalId;

  @override
  ConsumerState<ProposalDetailScreen> createState() =>
      _ProposalDetailScreenState();
}

class _ProposalDetailScreenState extends ConsumerState<ProposalDetailScreen> {
  /// Shows the inline thanks notice after a rating — SnackBars never render
  /// under the iOS Cupertino shell.
  bool _rated = false;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final proposal = ref.watch(proposalDetailProvider(widget.proposalId));
    return AdaptiveScaffold(
      title: l10n.proposalsSegment,
      body: PageBody(
        child: switch (proposal) {
          AsyncData(:final value) => _body(context, ref, l10n, value),
          AsyncError(:final error) => Center(
            child: ErrorRetry(
              error: error,
              onRetry: () =>
                  ref.invalidate(proposalDetailProvider(widget.proposalId)),
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
    Proposal proposal,
  ) {
    final settlement = proposal.settlement;
    final theme = Theme.of(context);
    final palette = LamToPalette.of(context);

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 40),
      children: [
        Align(
          alignment: Alignment.centerLeft,
          child: StatusChip(
            tone: proposalStatusTone(proposal.status),
            label: proposalStatusLabel(proposal.status, l10n),
          ),
        ),
        const SizedBox(height: 16),
        InsetGroup(
          children: [
            InfoRow(
              label: l10n.proposalCost,
              value: formatVnd(proposal.amountVnd),
              valueStyle: heroAmountStyle(context)?.copyWith(fontSize: 26),
            ),
            if (proposal.comparison != null)
              _PriceComparisonField(comparison: proposal.comparison!),
            InfoRow(label: l10n.proposalProblem, value: proposal.purpose),
            InfoRow(label: l10n.proposalAction, value: proposal.proposedAction),
            InfoRow(
              label: l10n.proposalContractor,
              value: proposal.contractorName,
            ),
            InfoRow(
              label: l10n.proposalSchedule,
              value: proposal.expectedSchedule,
            ),
          ],
        ),
        const SizedBox(height: 28),
        SectionHeader(l10n.proposalVersions),
        InsetGroup(
          children: [
            for (final version in proposal.versions)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 14),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      l10n.proposalVersion('${version.number}'),
                      style: theme.textTheme.bodyLarge?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    Text(
                      _date(version.publishedAt),
                      style: theme.textTheme.bodySmall,
                    ),
                    const SizedBox(height: 8),
                    EvidenceBadge(level: version.evidenceLevel),
                    for (final document in version.supportingDocuments)
                      Padding(
                        padding: const EdgeInsets.only(top: 10),
                        child: Row(
                          children: [
                            Icon(
                              Icons.description_outlined,
                              size: 20,
                              color: palette.muted,
                            ),
                            const SizedBox(width: 10),
                            Expanded(child: Text(document.filename)),
                          ],
                        ),
                      ),
                  ],
                ),
              ),
          ],
        ),
        if (proposal.progress.isNotEmpty) ...[
          const SizedBox(height: 28),
          SectionHeader(l10n.progressTitle),
          InsetGroup(
            padding: const EdgeInsets.all(16),
            children: [
              Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  for (final (index, update) in proposal.progress.indexed)
                    TimelineStep(
                      icon: Icons.build_outlined,
                      isLast: index == proposal.progress.length - 1,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            update.result,
                            style: theme.textTheme.bodyLarge?.copyWith(
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                          const SizedBox(height: 2),
                          Text(
                            '${update.cause} · ${_date(update.createdAt)}',
                            style: theme.textTheme.bodySmall,
                          ),
                        ],
                      ),
                    ),
                ],
              ),
            ],
          ),
        ],
        if (settlement != null) ...[
          const SizedBox(height: 28),
          SectionHeader(l10n.proposalSettlement),
          InsetGroup(
            children: [
              ListTile(
                minTileHeight: 56,
                leading: const IconWell(
                  Icons.check_circle_outline,
                  tone: StatusTone.success,
                ),
                title: Text(l10n.proposalSettled),
              ),
            ],
          ),
        ],
        if (proposal.explorerUrl != null &&
            proposal.explorerUrl!.isNotEmpty) ...[
          const SizedBox(height: 16),
          InsetGroup(
            children: [EvidenceExplorerTile(url: proposal.explorerUrl!)],
          ),
        ],
        // Inline where the rate CTA sits (visible on iOS, unlike a SnackBar).
        if (_rated) ...[
          const SizedBox(height: 24),
          StatusNotice(tone: StatusTone.success, message: l10n.rateThanks),
        ],
        if (proposal.status == 'COMPLETED' && proposal.canRate) ...[
          const SizedBox(height: 24),
          AdaptiveFilledButton(
            icon: const Icon(Icons.star_outline),
            child: Text(l10n.proposalRateCta),
            onPressed: () => _openRating(context),
          ),
        ],
      ],
    );
  }

  Future<void> _openRating(BuildContext context) async {
    final rated = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _RateProposalSheet(proposalId: widget.proposalId),
    );
    if (rated == true && mounted) {
      ref.invalidate(proposalDetailProvider(widget.proposalId));
      setState(() => _rated = true);
    }
  }
}

String _date(DateTime value) =>
    DateFormat('dd/MM/yyyy').format(value.toLocal());

class _PriceComparisonField extends StatelessWidget {
  const _PriceComparisonField({required this.comparison});

  final ProposalComparison comparison;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final direction = comparison.direction;

    final String arrow;
    final Color? arrowColor;
    final String comparisonText;

    if (direction == 'below') {
      arrow = '↓';
      arrowColor = statusToneColors(context, StatusTone.success).fg;
      comparisonText = l10n.proposalPriceComparisonBelow(
        comparison.percentage,
        comparison.range,
      );
    } else if (direction == 'above') {
      arrow = '↑';
      arrowColor = statusToneColors(context, StatusTone.error).fg;
      comparisonText = l10n.proposalPriceComparisonAbove(
        comparison.percentage,
        comparison.range,
      );
    } else {
      arrow = '';
      arrowColor = null;
      comparisonText = l10n.proposalPriceComparisonEqual;
    }

    final mutedColor = Theme.of(context).colorScheme.onSurfaceVariant;
    final textTheme = Theme.of(context).textTheme;

    return MergeSemantics(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(l10n.proposalPriceComparison, style: textTheme.bodySmall),
            const SizedBox(height: 4),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (arrow.isNotEmpty) ...[
                  Text(
                    arrow,
                    style: TextStyle(
                      color: arrowColor,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const SizedBox(width: 6),
                ],
                Expanded(
                  child: Text(
                    comparisonText,
                    style: textTheme.bodyLarge?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ],
            ),
            if (comparison.reasoning.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(
                comparison.reasoning,
                style: textTheme.bodySmall?.copyWith(color: mutedColor),
              ),
            ],
            const SizedBox(height: 4),
            Text(
              l10n.proposalPriceComparisonCaveat,
              style: textTheme.bodySmall?.copyWith(color: mutedColor),
            ),
          ],
        ),
      ),
    );
  }
}

class _RateProposalSheet extends ConsumerStatefulWidget {
  const _RateProposalSheet({required this.proposalId});

  final int proposalId;

  @override
  ConsumerState<_RateProposalSheet> createState() => _RateProposalSheetState();
}

class _RateProposalSheetState extends ConsumerState<_RateProposalSheet> {
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
        left: 20,
        right: 20,
        top: 4,
        bottom: 24 + MediaQuery.viewInsetsOf(context).bottom,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            l10n.rateWorkTitle,
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 16),
          SegmentedButton<bool>(
            segments: [
              ButtonSegment(value: true, label: Text(l10n.rateSatisfied)),
              ButtonSegment(value: false, label: Text(l10n.rateNotSatisfied)),
            ],
            selected: {_satisfied},
            showSelectedIcon: false,
            onSelectionChanged: _busy
                ? null
                : (value) => setState(() => _satisfied = value.first),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _comment,
            maxLength: 500,
            decoration: InputDecoration(labelText: l10n.rateCommentLabel),
          ),
          if (_error != null)
            Text(
              _error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          const SizedBox(height: 8),
          AdaptiveFilledButton(
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
          .read(proposalsRepositoryProvider)
          .rateProposal(
            id: widget.proposalId,
            satisfied: _satisfied,
            comment: _comment.text.trim(),
          );
      if (mounted) Navigator.pop(context, true);
    } catch (error) {
      if (mounted) {
        setState(
          () => _error = failureMessage(Failure.fromObject(error), l10n),
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
}
