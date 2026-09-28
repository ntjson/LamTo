import 'package:flutter/cupertino.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/adaptive_page_route.dart';
import '../../core/failure.dart';
import '../../core/providers.dart';
import '../../l10n/app_localizations.dart';
import '../../theme.dart';
import '../../widgets/grouped.dart';
import '../shell/tab_page.dart';
import '../auth/session_controller.dart';
import '../reports/reports_repository.dart';
import '../settings/api_base_url_tile.dart';
import '../transparency/transparency_repository.dart';
import '../gate/gate_registration_screen.dart';

/// Resident notification event codes (server defaults absent rows to
/// enabled). One master switch drives every code on both channels.
const residentPreferenceCodes = [
  'report.receipt',
  'triage.status',
  'work.completed',
  'ledger.publication',
  'correction.status',
  'building.announcement',
];

/// Account tab (spec 6.3(7)). Body-only: the shell owns chrome.
class AccountScreen extends ConsumerStatefulWidget {
  const AccountScreen({super.key});

  @override
  ConsumerState<AccountScreen> createState() => _AccountScreenState();
}

class _AccountScreenState extends ConsumerState<AccountScreen> {
  /// Local overlay of the master toggle after the user flipped it.
  bool? _all;

  /// Last preference PATCH failure (resident copy). Inline — not SnackBar —
  /// so the message works under iOS [CupertinoPageScaffold] (no Material
  /// Scaffold / snack-bar host).
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
    // Absent rows default to enabled server-side, so present rows decide.
    final serverAll = me.notificationPreferences.every(
      (pref) => pref.emailEnabled && pref.pushEnabled,
    );

    final theme = Theme.of(context);
    final palette = LamToPalette.of(context);
    final contact = [
      if (me.email != null && me.email!.isNotEmpty) me.email!,
      if (me.phone != null && me.phone!.isNotEmpty) me.phone!,
    ];
    final initial = me.displayName.trim().isEmpty
        ? '?'
        : me.displayName.trim().characters.first.toUpperCase();

    return Material(
      color: Colors.transparent,
      child: TabPage(
        title: l10n.tabAccount,
        slivers: [
          SliverPadding(
            padding: tabContentPadding,
            // Short, bounded content: built whole, like a plain column.
            sliver: SliverToBoxAdapter(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  InsetGroup(
                    padding: const EdgeInsets.all(16),
                    children: [
                      Row(
                        children: [
                          ExcludeSemantics(
                            child: CircleAvatar(
                              radius: 30,
                              backgroundColor: LamToColors.brand,
                              foregroundColor: Colors.white,
                              child: Text(
                                initial,
                                style: theme.textTheme.titleLarge?.copyWith(
                                  color: Colors.white,
                                ),
                              ),
                            ),
                          ),
                          const SizedBox(width: 16),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  me.displayName,
                                  style: theme.textTheme.titleLarge,
                                ),
                                for (final line in contact) ...[
                                  const SizedBox(height: 2),
                                  Text(
                                    line,
                                    style: theme.textTheme.bodyMedium?.copyWith(
                                      color: palette.muted,
                                    ),
                                  ),
                                ],
                              ],
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                  const SizedBox(height: 28),
                  RadioGroup<int>(
                    groupValue: holder.occupancyId,
                    onChanged: (id) {
                      if (id != null) {
                        ref
                            .read(sessionControllerProvider.notifier)
                            .selectOccupancy(me, id);
                      }
                    },
                    child: InsetGroup(
                      header: l10n.accountOccupancies,
                      dividerIndent: 56,
                      children: [
                        for (final occupancy in me.occupancies)
                          RadioListTile<int>(
                            value: occupancy.id,
                            title: Text(
                              '${occupancy.buildingName} · ${occupancy.unitLabel}',
                            ),
                          ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 28),
                  InsetGroup(
                    header: l10n.accountPreferences,
                    children: [
                      SwitchListTile.adaptive(
                        key: const Key('notifications_all'),
                        title: Text(l10n.accountPrefAll),
                        value: _all ?? serverAll,
                        onChanged: _setAll,
                      ),
                    ],
                  ),
                  if (_prefError != null) ...[
                    const SizedBox(height: 8),
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 16),
                      child: Text(
                        _prefError!,
                        key: const Key('account_pref_error'),
                        style: theme.textTheme.bodyMedium?.copyWith(
                          color: theme.colorScheme.error,
                        ),
                      ),
                    ),
                  ],
                  const SizedBox(height: 28),
                  InsetGroup(
                    dividerIndent: 68,
                    children: [
                      ListTile(
                        minTileHeight: 56,
                        leading: const IconWell(Icons.door_front_door_outlined),
                        title: Text(l10n.gateAccountAction),
                        trailing: Icon(
                          Icons.chevron_right,
                          color: palette.muted.withValues(alpha: 0.6),
                        ),
                        onTap: () => Navigator.of(context).push(
                          adaptivePageRoute<void>(
                            builder: (_) => GateRegistrationScreen(
                              repository: ref.read(gateRepositoryProvider),
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 28),
                  // Session actions, not the tab's primary CTA: destructive
                  // rows, never the filled tint reserved for primary actions.
                  InsetGroup(
                    children: [
                      ListTile(
                        minTileHeight: 52,
                        title: Text(
                          l10n.signOut,
                          style: TextStyle(color: theme.colorScheme.error),
                        ),
                        onTap: () => _confirmSignOut(),
                      ),
                      ListTile(
                        minTileHeight: 52,
                        title: Text(
                          l10n.accountSignOutAll,
                          style: TextStyle(color: theme.colorScheme.error),
                        ),
                        onTap: () => _confirmSignOut(allDevices: true),
                      ),
                    ],
                  ),
                  const SizedBox(height: 28),
                  // Not debug-gated: a released APK must be retargetable at a
                  // fresh quick-tunnel URL without a rebuild.
                  const InsetGroup(children: [ApiBaseUrlTile()]),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  /// Sign-out destroys unsent work on this device ([ReportDraftStore.clearAll]
  /// wipes report drafts and pending reply photos), so it confirms first.
  /// The consequence line appears only when such work actually exists.
  Future<void> _confirmSignOut({bool allDevices = false}) async {
    final l10n = AppLocalizations.of(context)!;
    final hasUnsentWork = await ref
        .read(reportDraftStoreProvider)
        .hasUnsentWork();
    if (!mounted) return;
    final title = allDevices ? l10n.accountSignOutAll : l10n.signOut;
    final warning = hasUnsentWork ? l10n.signOutUnsentWorkWarning : null;
    final confirmed = defaultTargetPlatform == TargetPlatform.iOS
        ? await showCupertinoDialog<bool>(
            context: context,
            builder: (context) => CupertinoAlertDialog(
              title: Text(title),
              content: warning == null ? null : Text(warning),
              actions: [
                CupertinoDialogAction(
                  isDefaultAction: true,
                  onPressed: () => Navigator.pop(context, false),
                  child: Text(l10n.commonCancel),
                ),
                CupertinoDialogAction(
                  isDestructiveAction: true,
                  onPressed: () => Navigator.pop(context, true),
                  child: Text(l10n.signOut),
                ),
              ],
            ),
          )
        : await showDialog<bool>(
            context: context,
            builder: (context) => AlertDialog(
              title: Text(title),
              content: warning == null ? null : Text(warning),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(context, false),
                  child: Text(l10n.commonCancel),
                ),
                TextButton(
                  style: TextButton.styleFrom(
                    foregroundColor: Theme.of(context).colorScheme.error,
                  ),
                  onPressed: () => Navigator.pop(context, true),
                  child: Text(l10n.signOut),
                ),
              ],
            ),
          );
    if (confirmed == true && mounted) {
      await ref
          .read(sessionControllerProvider.notifier)
          .signOut(allDevices: allDevices);
    }
  }

  Future<void> _setAll(bool value) async {
    setState(() {
      _all = value;
      _prefError = null;
    });
    try {
      // ponytail: sequential per-code PATCH (no bulk endpoint); a mid-loop
      // failure leaves earlier codes applied — the revert + retry covers it.
      for (final code in residentPreferenceCodes) {
        await ref
            .read(transparencyRepositoryProvider)
            .updatePreference(
              eventCode: code,
              emailEnabled: value,
              pushEnabled: value,
            );
      }
    } catch (error) {
      // Revert the optimistic flip on failure and surface resident copy.
      // Inline error only — SnackBar needs a Material Scaffold host that
      // iOS CupertinoPageScaffold (HomeShell) does not provide.
      if (!mounted) return;
      final l10n = AppLocalizations.of(context)!;
      setState(() {
        _all = !value;
        _prefError = failureMessage(Failure.fromObject(error), l10n);
      });
    }
  }
}
