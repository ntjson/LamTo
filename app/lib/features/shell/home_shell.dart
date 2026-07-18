import 'package:flutter/cupertino.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../../core/page_body.dart';
import '../../l10n/app_localizations.dart';
import '../account/account_screen.dart';
import '../home/home_screen.dart';
import '../ledger/ledger_screen.dart';
import '../reports/my_issues_screen.dart';
import '../reports/report_form_screen.dart';

/// Platform-adaptive tab shell: Material NavigationBar (compact) or
/// NavigationRail (expanded width) on Android, CupertinoTabBar on iOS;
/// same five tab slots (clarification #7).
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

  List<Widget> get _bodies => [
    const HomeScreen(),
    const ReportFormScreen(),
    const MyIssuesScreen(),
    const LedgerScreen(),
    const AccountScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final bodies = _bodies;
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
          child: SafeArea(child: PageBody(child: bodies[index])),
        ),
      );
    }

    final destinations = [
      (Icons.home_outlined, l10n.tabHome),
      (Icons.add_circle_outline, l10n.tabReport),
      (Icons.list_alt_outlined, l10n.tabIssues),
      (Icons.account_balance_outlined, l10n.tabLedger),
      (Icons.person_outline, l10n.tabAccount),
    ];
    final expanded = MediaQuery.sizeOf(context).width >= kExpandedWidthMin;

    if (expanded) {
      // Medium/expanded window class: navigation rail instead of a
      // stretched phone bottom bar (Material 3 adaptive navigation).
      return Scaffold(
        body: SafeArea(
          child: Row(
            children: [
              NavigationRail(
                selectedIndex: _index,
                onDestinationSelected: (i) => setState(() => _index = i),
                labelType: NavigationRailLabelType.all,
                destinations: [
                  for (final (icon, label) in destinations)
                    NavigationRailDestination(
                      icon: Icon(icon),
                      label: Text(label),
                    ),
                ],
              ),
              const VerticalDivider(width: 1, thickness: 1),
              Expanded(child: PageBody(child: bodies[_index])),
            ],
          ),
        ),
      );
    }

    return Scaffold(
      body: SafeArea(child: bodies[_index]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) => setState(() => _index = i),
        destinations: [
          for (final (icon, label) in destinations)
            NavigationDestination(icon: Icon(icon), label: label),
        ],
      ),
    );
  }
}
