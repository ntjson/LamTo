import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/adaptive_page_route.dart';
import '../../core/error_retry.dart';
import '../../core/format.dart';
import '../../core/load_more_button.dart';
import '../../core/providers.dart';
import '../../l10n/app_localizations.dart';
import '../../theme.dart';
import '../../widgets/grouped.dart';
import '../shell/tab_page.dart';
import '../reports/reports_repository.dart' show cursorFromNext;
import 'proposal_detail_screen.dart';
import 'proposals_repository.dart';

String proposalStatusLabel(String status, AppLocalizations l10n) =>
    switch (status) {
      'PUBLISHED' => l10n.proposalStatusPublished,
      'IN_PROGRESS' => l10n.proposalStatusInProgress,
      'NOT_PROCEEDING' => l10n.proposalStatusNotProceeding,
      'COMPLETED' => l10n.proposalStatusCompleted,
      'CLOSED' => l10n.proposalStatusClosed,
      'DRAFT' => l10n.proposalStatusDraft,
      _ => status,
    };

StatusTone proposalStatusTone(String status) => switch (status) {
  'COMPLETED' || 'CLOSED' => StatusTone.success,
  'NOT_PROCEEDING' => StatusTone.warning,
  _ => StatusTone.info,
};

class ProposalsListController extends AsyncNotifier<List<Proposal>> {
  String? _nextCursor;
  bool get hasMore => _nextCursor != null;

  @override
  Future<List<Proposal>> build() async {
    ref.watch(occupancyScopedProviders);
    final page = await ref.read(proposalsRepositoryProvider).listProposals();
    _nextCursor = cursorFromNext(page.next);
    return page.results.toList();
  }

  Future<void> loadMore() async {
    final cursor = _nextCursor;
    final current = state.value;
    if (cursor == null || current == null) return;
    final page = await ref
        .read(proposalsRepositoryProvider)
        .listProposals(cursor: cursor);
    if (!identical(state.value, current)) return;
    _nextCursor = cursorFromNext(page.next);
    state = AsyncData([...current, ...page.results]);
  }
}

final proposalsListProvider =
    AsyncNotifierProvider<ProposalsListController, List<Proposal>>(
      ProposalsListController.new,
    );

/// The proposals list as one sliver, so it can sit under the Ledger tab's
/// segmented control inside the tab's scroll view.
class ProposalsSliver extends ConsumerWidget {
  const ProposalsSliver({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context)!;
    final proposals = ref.watch(proposalsListProvider);
    final slivers = switch (proposals) {
      AsyncData(:final value) when value.isEmpty => <Widget>[
        SliverToBoxAdapter(
          child: InsetGroup(
            children: [
              EmptyState(
                icon: Icons.description_outlined,
                message: l10n.proposalsEmpty,
              ),
            ],
          ),
        ),
      ],
      // Builder-based so a long paginated history lays out lazily.
      AsyncData(:final value) => <Widget>[
        SliverList.builder(
          itemCount: value.length,
          itemBuilder: (context, i) => GroupedListItem(
            isFirst: i == 0,
            isLast: i == value.length - 1,
            child: _ProposalTile(proposal: value[i]),
          ),
        ),
        if (ref.read(proposalsListProvider.notifier).hasMore)
          SliverToBoxAdapter(
            child: LoadMoreButton(
              label: l10n.ledgerLoadMore,
              onLoadMore: ref.read(proposalsListProvider.notifier).loadMore,
            ),
          ),
      ],
      AsyncError(:final error) => <Widget>[
        SliverToBoxAdapter(
          child: ErrorRetry(
            error: error,
            onRetry: () => ref.invalidate(proposalsListProvider),
          ),
        ),
      ],
      _ => <Widget>[
        const SliverToBoxAdapter(
          child: Padding(
            padding: EdgeInsets.only(top: 48),
            child: Center(child: CircularProgressIndicator.adaptive()),
          ),
        ),
      ],
    };
    return SliverPadding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      sliver: SliverMainAxisGroup(slivers: slivers),
    );
  }
}

/// Standalone proposals list (the same rows the Ledger tab shows).
class ProposalsListScreen extends ConsumerWidget {
  const ProposalsListScreen({this.showTitle = true, super.key});

  final bool showTitle;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context)!;
    return Material(
      color: Colors.transparent,
      child: RefreshIndicator.adaptive(
        onRefresh: () async {
          ref.invalidate(proposalsListProvider);
          try {
            await ref.read(proposalsListProvider.future);
          } catch (_) {}
        },
        child: CustomScrollView(
          physics: const AlwaysScrollableScrollPhysics(),
          slivers: [
            SliverToBoxAdapter(
              child: showTitle
                  ? Padding(
                      padding: const EdgeInsets.fromLTRB(20, 16, 20, 12),
                      child: Text(
                        l10n.proposalsSegment,
                        style: Theme.of(context).textTheme.headlineSmall,
                      ),
                    )
                  : const SizedBox(height: 8),
            ),
            const ProposalsSliver(),
            const SliverToBoxAdapter(child: SizedBox(height: 32)),
          ],
        ),
      ),
    );
  }
}

class _ProposalTile extends StatelessWidget {
  const _ProposalTile({required this.proposal});

  final Proposal proposal;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    return ListTile(
      minTileHeight: 72,
      contentPadding: const EdgeInsets.fromLTRB(16, 4, 12, 4),
      title: Text(
        proposal.purpose,
        maxLines: 2,
        overflow: TextOverflow.ellipsis,
      ),
      subtitle: Padding(
        padding: const EdgeInsets.only(top: 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (!figuresTrail(context)) ...[
              Text(
                formatVnd(proposal.amountVnd),
                style: listAmountStyle(context),
              ),
              const SizedBox(height: 6),
            ],
            StatusChip(
              tone: proposalStatusTone(proposal.status),
              label: proposalStatusLabel(proposal.status, l10n),
            ),
          ],
        ),
      ),
      trailing: figuresTrail(context)
          ? Text(formatVnd(proposal.amountVnd), style: listAmountStyle(context))
          : null,
      onTap: () => Navigator.push(
        context,
        adaptivePageRoute(
          builder: (_) => ProposalDetailScreen(proposalId: proposal.id),
        ),
      ),
    );
  }
}
