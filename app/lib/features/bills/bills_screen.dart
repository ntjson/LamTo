import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
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
import 'bill_detail_screen.dart';
import 'bills_repository.dart';

class BillsScreen extends ConsumerWidget {
  const BillsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context)!;
    final bills = ref.watch(billsProvider);
    return AdaptiveScaffold(
      title: l10n.billsTitle,
      body: PageBody(
        child: switch (bills) {
          AsyncData(:final value) => _list(context, l10n, value),
          AsyncError(:final error) => Center(
            child: ErrorRetry(
              error: error,
              onRetry: () => ref.invalidate(billsProvider),
            ),
          ),
          _ => const Center(child: CircularProgressIndicator.adaptive()),
        },
      ),
    );
  }

  Widget _list(
    BuildContext context,
    AppLocalizations l10n,
    List<BillSummary> bills,
  ) {
    if (bills.isEmpty) {
      return ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        children: [
          const SizedBox(height: 80),
          EmptyState(
            icon: Icons.receipt_long_outlined,
            message: l10n.billNone,
            action: AdaptiveOutlinedButton(
              onPressed: () => Navigator.maybePop(context),
              child: Text(MaterialLocalizations.of(context).backButtonTooltip),
            ),
          ),
        ],
      );
    }
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
      children: [
        InsetGroup(
          children: [
            for (final bill in bills)
              ListTile(
                minTileHeight: 72,
                contentPadding: const EdgeInsets.fromLTRB(16, 4, 12, 4),
                title: Text(bill.title),
                subtitle: Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (!figuresTrail(context)) ...[
                        Text(
                          formatVnd(bill.amountVnd),
                          style: listAmountStyle(context),
                        ),
                        const SizedBox(height: 6),
                      ],
                      StatusChip(
                        tone: switch (bill.status) {
                          BillStatusEnum.PAID => StatusTone.success,
                          BillStatusEnum.VOID => StatusTone.error,
                          _ => StatusTone.warning,
                        },
                        label: switch (bill.status) {
                          BillStatusEnum.PAID => l10n.billStatusPaid,
                          BillStatusEnum.VOID => l10n.billStatusVoid,
                          _ => l10n.billStatusIssued,
                        },
                      ),
                    ],
                  ),
                ),
                trailing: figuresTrail(context)
                    ? Text(
                        formatVnd(bill.amountVnd),
                        style: listAmountStyle(context),
                      )
                    : null,
                onTap: () => Navigator.push(
                  context,
                  adaptivePageRoute(
                    builder: (_) => BillDetailScreen(billId: bill.id),
                  ),
                ),
              ),
          ],
        ),
      ],
    );
  }
}
