import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../l10n/app_localizations.dart';
import 'session_controller.dart';

class OccupancyPickerScreen extends ConsumerWidget {
  const OccupancyPickerScreen({required this.me, super.key});
  final Me me;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context)!;
    return Scaffold(
      appBar: AppBar(title: Text(l10n.occupancyPickerTitle)),
      body: ListView(
        children: me.occupancies.map((Occupancy o) {
          return ListTile(
            title: Text('${o.buildingName} · ${o.unitLabel}'),
            onTap: () async {
              await ref
                  .read(sessionControllerProvider.notifier)
                  .selectOccupancy(me, o.id);
              // Rebuild router with holder now set.
              ref.invalidate(sessionControllerProvider);
            },
          );
        }).toList(),
      ),
    );
  }
}
