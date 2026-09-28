import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/adaptive_buttons.dart';
import '../../core/adaptive_scaffold.dart';
import '../../core/page_body.dart';
import '../../l10n/app_localizations.dart';
import '../../widgets/grouped.dart';
import 'session_controller.dart';

class OccupancyPickerScreen extends ConsumerWidget {
  const OccupancyPickerScreen({required this.me, super.key})
    : emptyState = false;

  /// Zero-occupancy: authenticated but no linked home (dedicated empty state).
  const OccupancyPickerScreen.empty({super.key}) : me = null, emptyState = true;

  final Me? me;
  final bool emptyState;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context)!;
    if (emptyState || me == null || me!.occupancies.isEmpty) {
      return _NoOccupancyScreen(
        onSignOut: () => ref.read(sessionControllerProvider.notifier).signOut(),
      );
    }
    final current = me!;
    return AdaptiveScaffold(
      title: l10n.occupancyPickerTitle,
      body: PageBody(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
          children: [
            InsetGroup(
              dividerIndent: 68,
              children: [
                for (final o in current.occupancies)
                  ListTile(
                    minTileHeight: 60,
                    leading: const IconWell(Icons.apartment_outlined),
                    title: Text('${o.buildingName} · ${o.unitLabel}'),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () async {
                      await ref
                          .read(sessionControllerProvider.notifier)
                          .selectOccupancy(current, o.id);
                    },
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// Resident-facing empty state when /me has zero occupancies.
class _NoOccupancyScreen extends StatelessWidget {
  const _NoOccupancyScreen({required this.onSignOut});
  final VoidCallback onSignOut;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    return AdaptiveScaffold(
      title: l10n.noOccupancyTitle,
      body: PageBody(
        child: Center(
          child: EmptyState(
            icon: Icons.apartment_outlined,
            message: l10n.noOccupancyBody,
            action: AdaptiveFilledButton(
              onPressed: onSignOut,
              child: Text(l10n.signOut),
            ),
          ),
        ),
      ),
    );
  }
}
