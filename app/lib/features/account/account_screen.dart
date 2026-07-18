import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/failure.dart';
import '../../core/providers.dart';
import '../../l10n/app_localizations.dart';
import '../auth/session_controller.dart';
import '../settings/api_base_url_tile.dart';
import '../transparency/transparency_repository.dart';

/// The five resident notification categories (server defaults absent rows to
/// enabled). Labels resolve through l10n.
List<({String code, String label})> residentPreferenceCategories(
  AppLocalizations l10n,
) => [
  (code: 'report.receipt', label: l10n.prefReportReceipt),
  (code: 'triage.status', label: l10n.prefTriageStatus),
  (code: 'work.completed', label: l10n.prefWorkCompleted),
  (code: 'ledger.publication', label: l10n.prefLedgerPublication),
  (code: 'correction.status', label: l10n.prefCorrectionStatus),
];

/// Account tab (spec 6.3(7)). Body-only: the shell owns chrome.
class AccountScreen extends ConsumerStatefulWidget {
  const AccountScreen({super.key});

  @override
  ConsumerState<AccountScreen> createState() => _AccountScreenState();
}

class _AccountScreenState extends ConsumerState<AccountScreen> {
  /// Local overlay of toggles the user flipped this session.
  final Map<String, bool> _email = {};
  final Map<String, bool> _push = {};

  /// Last preference PATCH failure (resident copy). Inline — not SnackBar —
  /// so the message works under iOS [CupertinoPageScaffold] (no Material
  /// Scaffold / ScaffoldMessenger host).
  String? _prefError;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final session = ref.watch(sessionControllerProvider);
    final me = switch (session) {
      AsyncData(value: SessionAuthenticated(:final me)) => me,
      _ => null,
    };
    if (me == null) {
      return const Center(child: CircularProgressIndicator.adaptive());
    }
    final holder = ref.watch(occupancyHolderProvider);
    final serverPrefs = {
      for (final pref in me.notificationPreferences) pref.eventCode: pref,
    };

    return Material(
      color: Colors.transparent,
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(me.displayName, style: Theme.of(context).textTheme.titleLarge),
            Text(me.email, style: Theme.of(context).textTheme.bodySmall),
            if (me.phone != null && me.phone!.isNotEmpty)
              Text(me.phone!, style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 24),
            Text(
              l10n.accountOccupancies,
              style: Theme.of(context).textTheme.titleMedium,
            ),
            RadioGroup<int>(
              groupValue: holder.occupancyId,
              onChanged: (id) {
                if (id != null) {
                  ref
                      .read(sessionControllerProvider.notifier)
                      .selectOccupancy(me, id);
                }
              },
              child: Column(
                children: [
                  for (final occupancy in me.occupancies)
                    RadioListTile<int>(
                      contentPadding: EdgeInsets.zero,
                      value: occupancy.id,
                      title: Text(
                        '${occupancy.buildingName} · ${occupancy.unitLabel}',
                      ),
                    ),
                ],
              ),
            ),
            const SizedBox(height: 24),
            Text(
              l10n.accountPreferences,
              style: Theme.of(context).textTheme.titleMedium,
            ),
            if (_prefError != null) ...[
              const SizedBox(height: 8),
              Text(
                _prefError!,
                key: const Key('account_pref_error'),
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: Theme.of(context).colorScheme.error,
                ),
              ),
            ],
            for (final category in residentPreferenceCategories(l10n))
              _prefRow(l10n, category, serverPrefs[category.code]),
            const SizedBox(height: 24),
            const ApiBaseUrlTile(),
            const SizedBox(height: 24),
            // Session actions, not the tab's primary CTA: outlined/text, never
            // the filled Accountability Indigo reserved for primary actions.
            OutlinedButton(
              style: OutlinedButton.styleFrom(
                minimumSize: const Size.fromHeight(48),
              ),
              onPressed: () =>
                  ref.read(sessionControllerProvider.notifier).signOut(),
              child: Text(l10n.signOut),
            ),
            const SizedBox(height: 8),
            TextButton(
              style: TextButton.styleFrom(
                minimumSize: const Size.fromHeight(48),
              ),
              onPressed: () => ref
                  .read(sessionControllerProvider.notifier)
                  .signOut(allDevices: true),
              child: Text(l10n.accountSignOutAll),
            ),
          ],
        ),
      ),
    );
  }

  Widget _prefRow(
    AppLocalizations l10n,
    ({String code, String label}) category,
    NotificationPreference? server,
  ) {
    final email = _email[category.code] ?? server?.emailEnabled ?? true;
    final push = _push[category.code] ?? server?.pushEnabled ?? true;
    // Wrap, not Row: at large system text scale the fixed labels + switches
    // exceed compact widths and a Row would clip (PRODUCT.md: system text
    // scaling without clipping). Controls fall to their own line instead.
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Wrap(
        alignment: WrapAlignment.spaceBetween,
        crossAxisAlignment: WrapCrossAlignment.center,
        runSpacing: 4,
        children: [
          Text(category.label),
          Wrap(
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              ExcludeSemantics(
                child: Text(
                  l10n.accountPrefEmail,
                  style: Theme.of(context).textTheme.labelSmall,
                ),
              ),
              Semantics(
                label: '${category.label} · ${l10n.accountPrefEmail}',
                child: Switch.adaptive(
                  key: Key('email_${category.code}'),
                  value: email,
                  onChanged: (value) => _patch(category.code, email: value),
                ),
              ),
              ExcludeSemantics(
                child: Text(
                  l10n.accountPrefPush,
                  style: Theme.of(context).textTheme.labelSmall,
                ),
              ),
              Semantics(
                label: '${category.label} · ${l10n.accountPrefPush}',
                child: Switch.adaptive(
                  key: Key('push_${category.code}'),
                  value: push,
                  onChanged: (value) => _patch(category.code, push: value),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Future<void> _patch(String code, {bool? email, bool? push}) async {
    setState(() {
      if (email != null) _email[code] = email;
      if (push != null) _push[code] = push;
      _prefError = null;
    });
    try {
      await ref
          .read(transparencyRepositoryProvider)
          .updatePreference(
            eventCode: code,
            emailEnabled: email,
            pushEnabled: push,
          );
    } catch (error) {
      // Revert the optimistic flip on failure and surface resident copy.
      // Inline error only — SnackBar needs a Material Scaffold host that
      // iOS CupertinoPageScaffold (HomeShell) does not provide.
      if (!mounted) return;
      final l10n = AppLocalizations.of(context)!;
      setState(() {
        if (email != null) _email[code] = !email;
        if (push != null) _push[code] = !push;
        _prefError = failureMessage(Failure.fromObject(error), l10n);
      });
    }
  }
}
