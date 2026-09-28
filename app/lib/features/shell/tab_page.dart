import 'package:flutter/cupertino.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../../l10n/app_localizations.dart';
import '../../theme.dart';
import '../reports/report_form_screen.dart';

/// Root page of a tab: a large title that collapses as the content scrolls
/// under it — the iOS large title, and Material's large top app bar on
/// Android — then optional pull to refresh, then the content slivers.
///
/// On iOS the bar also carries Report, the app's primary action; Android
/// keeps it on the shell's floating action button.
class TabPage extends StatelessWidget {
  const TabPage({
    required this.title,
    required this.slivers,
    this.onRefresh,
    super.key,
  });

  final String title;
  final List<Widget> slivers;
  final Future<void> Function()? onRefresh;

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.paddingOf(context).bottom;
    // Room below the last row for the tab bar / floating action button.
    final end = SliverToBoxAdapter(child: SizedBox(height: bottom + 96));
    if (defaultTargetPlatform == TargetPlatform.iOS) {
      final l10n = AppLocalizations.of(context)!;
      final palette = LamToPalette.of(context);
      return CustomScrollView(
        physics: const AlwaysScrollableScrollPhysics(
          parent: BouncingScrollPhysics(),
        ),
        slivers: [
          CupertinoSliverNavigationBar(
            largeTitle: Text(title),
            backgroundColor: palette.bg.withValues(alpha: 0.86),
            border: null,
            trailing: Semantics(
              label: l10n.tabReport,
              button: true,
              excludeSemantics: true,
              child: CupertinoButton(
                padding: EdgeInsets.zero,
                onPressed: () => openReportForm(context),
                child: const Icon(CupertinoIcons.add),
              ),
            ),
          ),
          if (onRefresh != null)
            CupertinoSliverRefreshControl(onRefresh: onRefresh),
          ...slivers,
          end,
        ],
      );
    }
    final view = CustomScrollView(
      physics: const AlwaysScrollableScrollPhysics(),
      slivers: [
        SliverAppBar.large(title: Text(title)),
        ...slivers,
        end,
      ],
    );
    final refresh = onRefresh;
    return refresh == null
        ? view
        : RefreshIndicator(onRefresh: refresh, child: view);
  }
}

/// Horizontal page padding for tab content slivers.
const tabContentPadding = EdgeInsets.symmetric(horizontal: 16);

/// Wraps one row of a lazily built grouped list so consecutive rows read as
/// a single inset group: rounded outer corners, inset hairlines between.
class GroupedListItem extends StatelessWidget {
  const GroupedListItem({
    required this.child,
    required this.isFirst,
    required this.isLast,
    this.dividerIndent = 16,
    super.key,
  });

  final Widget child;
  final bool isFirst;
  final bool isLast;
  final double dividerIndent;

  @override
  Widget build(BuildContext context) {
    final palette = LamToPalette.of(context);
    const radius = Radius.circular(14);
    return Material(
      color: palette.surface,
      clipBehavior: Clip.antiAlias,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(
          top: isFirst ? radius : Radius.zero,
          bottom: isLast ? radius : Radius.zero,
        ),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (!isFirst) Divider(height: 1, indent: dividerIndent),
          Semantics(container: true, child: child),
        ],
      ),
    );
  }
}
