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
/// Report creation is a task, so it is exposed as the platform primary action
/// instead of consuming a destination.
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
    const MyIssuesScreen(),
    const LedgerScreen(),
    const AccountScreen(),
  ];

  void _openReport() {
    final l10n = AppLocalizations.of(context)!;
    final isIos = defaultTargetPlatform == TargetPlatform.iOS;
    Navigator.of(context).push(
      isIos
          ? CupertinoPageRoute<void>(
              builder: (_) => CupertinoPageScaffold(
                navigationBar: CupertinoNavigationBar(
                  middle: Text(l10n.reportFormTitle),
                ),
                child: const SafeArea(
                  top: false,
                  child: PageBody(child: ReportFormScreen()),
                ),
              ),
            )
          : MaterialPageRoute<void>(
              builder: (_) => Scaffold(
                appBar: AppBar(title: Text(l10n.reportFormTitle)),
                body: const PageBody(child: ReportFormScreen()),
              ),
            ),
    );
  }

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
          navigationBar: CupertinoNavigationBar(
            middle: Text(
              [
                l10n.tabHome,
                l10n.tabIssues,
                l10n.tabLedger,
                l10n.tabAccount,
              ][index],
            ),
            trailing: Semantics(
              label: l10n.tabReport,
              button: true,
              excludeSemantics: true,
              child: CupertinoButton(
                padding: EdgeInsets.zero,
                onPressed: _openReport,
                child: const Icon(CupertinoIcons.add),
              ),
            ),
          ),
          child: SafeArea(child: PageBody(child: bodies[index])),
        ),
      );
    }

    final destinations = [
      (Icons.home_outlined, l10n.tabHome),
      (Icons.list_alt_outlined, l10n.tabIssues),
      (Icons.account_balance_outlined, l10n.tabLedger),
      (Icons.person_outline, l10n.tabAccount),
    ];
    final expanded = MediaQuery.sizeOf(context).width >= kExpandedWidthMin;

    if (expanded) {
      // Medium/expanded window class: navigation rail instead of a
      // stretched phone bottom bar (Material 3 adaptive navigation).
      return Scaffold(
        floatingActionButton: FloatingActionButton.extended(
          onPressed: _openReport,
          icon: const Icon(Icons.add),
          label: Text(l10n.tabReport),
        ),
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
      floatingActionButton: FloatingActionButton(
        onPressed: _openReport,
        tooltip: l10n.tabReport,
        child: const Icon(Icons.add),
      ),
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
