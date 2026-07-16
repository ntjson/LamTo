import 'package:flutter/cupertino.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../../l10n/app_localizations.dart';

/// Platform-adaptive tab shell: Material NavigationBar on Android,
/// CupertinoTabBar on iOS; same five placeholder bodies (clarification #7).
///
/// iOS uses [CupertinoTabController] as the single source of truth for the
/// selected tab so bar and body cannot diverge.
class HomeShell extends StatefulWidget {
  const HomeShell({super.key});
  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  /// Android (and shared) selected index.
  int _index = 0;

  /// iOS single source of truth for tab selection.
  late final CupertinoTabController _cupertinoController;

  @override
  void initState() {
    super.initState();
    _cupertinoController = CupertinoTabController(initialIndex: 0);
  }

  @override
  void dispose() {
    _cupertinoController.dispose();
    super.dispose();
  }

  List<Widget> _bodies(AppLocalizations l10n) => [
        for (final label in [
          l10n.tabHome,
          l10n.tabReport,
          l10n.tabIssues,
          l10n.tabLedger,
          l10n.tabAccount,
        ])
          Center(child: Text(label)),
      ];

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final bodies = _bodies(l10n);
    final isIos = defaultTargetPlatform == TargetPlatform.iOS;

    if (isIos) {
      return CupertinoTabScaffold(
        controller: _cupertinoController,
        tabBar: CupertinoTabBar(
          items: [
            BottomNavigationBarItem(
              icon: const Icon(CupertinoIcons.home),
              label: l10n.tabHome,
            ),
            BottomNavigationBarItem(
              icon: const Icon(CupertinoIcons.add_circled),
              label: l10n.tabReport,
            ),
            BottomNavigationBarItem(
              icon: const Icon(CupertinoIcons.list_bullet),
              label: l10n.tabIssues,
            ),
            BottomNavigationBarItem(
              icon: const Icon(CupertinoIcons.money_dollar),
              label: l10n.tabLedger,
            ),
            BottomNavigationBarItem(
              icon: const Icon(CupertinoIcons.person),
              label: l10n.tabAccount,
            ),
          ],
        ),
        tabBuilder: (context, index) => CupertinoPageScaffold(
          child: SafeArea(child: bodies[index]),
        ),
      );
    }

    return Scaffold(
      body: bodies[_index],
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) => setState(() => _index = i),
        destinations: [
          NavigationDestination(
            icon: const Icon(Icons.home_outlined),
            label: l10n.tabHome,
          ),
          NavigationDestination(
            icon: const Icon(Icons.add_circle_outline),
            label: l10n.tabReport,
          ),
          NavigationDestination(
            icon: const Icon(Icons.list_alt_outlined),
            label: l10n.tabIssues,
          ),
          NavigationDestination(
            icon: const Icon(Icons.account_balance_outlined),
            label: l10n.tabLedger,
          ),
          NavigationDestination(
            icon: const Icon(Icons.person_outline),
            label: l10n.tabAccount,
          ),
        ],
      ),
    );
  }
}
