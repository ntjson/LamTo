import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../l10n/app_localizations.dart';
import 'session_controller.dart';

class OccupancyPickerScreen extends ConsumerWidget {
  const OccupancyPickerScreen({required this.me, super.key}) : emptyState = false;

  /// Zero-occupancy hard-stop (no units to pick).
  const OccupancyPickerScreen.empty({super.key})
      : me = null,
        emptyState = true;

  final Me? me;
  final bool emptyState;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context)!;
    if (emptyState || me == null || me!.occupancies.isEmpty) {
      return Scaffold(
        appBar: AppBar(title: Text(l10n.occupancyPickerTitle)),
        body: Center(child: Text(l10n.errGeneric)),
      );
    }
    final current = me!;
    return Scaffold(
      appBar: AppBar(title: Text(l10n.occupancyPickerTitle)),
      body: ListView(
        children: current.occupancies.map((Occupancy o) {
          return ListTile(
            title: Text('${o.buildingName} · ${o.unitLabel}'),
            onTap: () async {
              // Persist + notify listeners; router rebuilds to HomeShell
              // without invalidating session (review I1).
              await ref
                  .read(sessionControllerProvider.notifier)
                  .selectOccupancy(current, o.id);
            },
          );
        }).toList(),
      ),
    );
  }
}
