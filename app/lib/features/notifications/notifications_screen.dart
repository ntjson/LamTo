import 'package:flutter/material.dart';

import '../../l10n/app_localizations.dart';

/// Filled in by the notifications task; placeholder keeps the bell navigable.
class NotificationsScreen extends StatelessWidget {
  const NotificationsScreen({super.key});

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar:
            AppBar(title: Text(AppLocalizations.of(context)!.notificationsTitle)),
      );
}
