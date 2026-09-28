import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../l10n/app_localizations.dart';
import '../../widgets/grouped.dart';

/// Reusable Evidence explorer link row (spec 6.3(11) / issue 07 & 08).
///
/// Tapping opens the public Evidence explorer page in the device's external
/// browser so the full URL is visible and shareable.
class EvidenceExplorerTile extends StatelessWidget {
  const EvidenceExplorerTile({required this.url, super.key});

  final String url;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    return ListTile(
      minTileHeight: 56,
      leading: const IconWell(Icons.travel_explore_outlined),
      title: Text(l10n.evidenceExplorer),
      trailing: Icon(
        Icons.open_in_new,
        size: 20,
        color: Theme.of(context).colorScheme.primary,
      ),
      onTap: () async {
        final uri = Uri.tryParse(url);
        if (uri != null) {
          await launchUrl(uri, mode: LaunchMode.externalApplication);
        }
      },
    );
  }
}
