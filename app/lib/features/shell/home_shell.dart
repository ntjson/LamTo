import 'package:flutter/cupertino.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/legacy.dart';

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
/// [shellTabProvider] synchronizes cross-tab requests with Android's selected
/// index and iOS's [CupertinoTabController].
final shellTabProvider = StateProvider<int>((_) => 0);

const ledgerTabIndex = 2;

void selectLedgerTab(WidgetRef ref) {
  ref.read(ledgerSegmentProvider.notifier).state = 0;
  ref.read(shellTabProvider.notifier).state = ledgerTabIndex;
}

class HomeShell extends ConsumerStatefulWidget {
  const HomeShell({super.key});
  @override
  ConsumerState<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends ConsumerState<HomeShell> {
  /// Android (and shared) selected index.
  int _index = 0;

  /// iOS single source of truth for tab selection.
  late final CupertinoTabController _cupertinoController;

  @override
  void initState() {
    super.initState();
    _index = ref.read(shellTabProvider);
    _cupertinoController = CupertinoTabController(initialIndex: _index)
      ..addListener(() {
        ref.read(shellTabProvider.notifier).state = _cupertinoController.index;
      });
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

  @override
  Widget build(BuildContext context) {
    ref.listen<int>(shellTabProvider, (_, next) {
      if (_index != next) setState(() => _index = next);
      if (_cupertinoController.index != next) {
        _cupertinoController.index = next;
      }
    });
    final l10n = AppLocalizations.of(context)!;
    final bodies = _bodies;
    final isIos = defaultTargetPlatform == TargetPlatform.iOS;

    if (isIos) {
      return CupertinoTabScaffold(
        controller: _cupertinoController,
        tabBar: CupertinoTabBar(
          items: [
            BottomNavigationBarItem(
              icon: const Icon(CupertinoIcons.house),
              activeIcon: const Icon(CupertinoIcons.house_fill),
              label: l10n.tabHome,
            ),
            BottomNavigationBarItem(
              icon: const Icon(CupertinoIcons.square_list),
              activeIcon: const Icon(CupertinoIcons.square_list_fill),
              label: l10n.tabIssues,
            ),
            BottomNavigationBarItem(
              // The open ledger book ("Sổ quỹ"), twinned with Android's
              // Icons.account_balance institution glyph. Never a currency
              // symbol ("$" fronting a VND fund).
              icon: const Icon(CupertinoIcons.book),
              activeIcon: const Icon(CupertinoIcons.book_fill),
              label: l10n.tabLedger,
            ),
            BottomNavigationBarItem(
              icon: const Icon(CupertinoIcons.person_crop_circle),
              activeIcon: const Icon(CupertinoIcons.person_crop_circle_fill),
              label: l10n.tabAccount,
            ),
          ],
        ),
        // Each tab root draws its own collapsing large title (TabPage), so
        // the scaffold adds no bar and no top inset of its own.
        tabBuilder: (context, index) => CupertinoPageScaffold(
          child: PageBody(child: bodies[index]),
        ),
      );
    }

    final destinations = [
      (Icons.home_outlined, Icons.home, l10n.tabHome),
      (Icons.list_alt_outlined, Icons.list_alt, l10n.tabIssues),
      (Icons.account_balance_outlined, Icons.account_balance, l10n.tabLedger),
      (Icons.person_outline, Icons.person, l10n.tabAccount),
    ];
    final expanded = MediaQuery.sizeOf(context).width >= kExpandedWidthMin;

    if (expanded) {
      // Medium/expanded window class: navigation rail instead of a
      // stretched phone bottom bar (Material 3 adaptive navigation).
      return Scaffold(
        floatingActionButton: _reportButton(l10n),
        body: SafeArea(
          child: Row(
            children: [
              NavigationRail(
                selectedIndex: _index,
                onDestinationSelected: (i) {
                  ref.read(shellTabProvider.notifier).state = i;
                  setState(() => _index = i);
                },
                labelType: NavigationRailLabelType.all,
                groupAlignment: -0.9,
                destinations: [
                  for (final (icon, selectedIcon, label) in destinations)
                    NavigationRailDestination(
                      icon: Icon(icon),
                      selectedIcon: Icon(selectedIcon),
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
      body: SafeArea(child: PageBody(child: bodies[_index])),
      floatingActionButton: _reportButton(l10n),
      bottomNavigationBar: DecoratedBox(
        decoration: BoxDecoration(
          border: Border(
            top: BorderSide(color: Theme.of(context).dividerColor),
          ),
        ),
        child: NavigationBar(
          selectedIndex: _index,
          onDestinationSelected: (i) {
            ref.read(shellTabProvider.notifier).state = i;
            setState(() => _index = i);
          },
          destinations: [
            for (final (icon, selectedIcon, label) in destinations)
              NavigationDestination(
                icon: Icon(icon),
                selectedIcon: Icon(selectedIcon),
                label: label,
              ),
          ],
        ),
      ),
    );
  }

  /// Report is a task, not a place: the labelled primary action.
  Widget _reportButton(AppLocalizations l10n) => FloatingActionButton.extended(
    onPressed: () => openReportForm(context),
    icon: const Icon(Icons.add),
    label: Text(l10n.tabReport),
  );
}
