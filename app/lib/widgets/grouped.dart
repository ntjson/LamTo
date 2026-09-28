import 'package:flutter/material.dart';

import '../theme.dart';

/// Section title above a group: the one heading size between the screen
/// title and row text, so a page reads in three steps.
class SectionHeader extends StatelessWidget {
  const SectionHeader(this.title, {this.trailing, super.key});

  final String title;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 0, 4, 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Expanded(
            child: Semantics(
              header: true,
              child: Text(title, style: Theme.of(context).textTheme.titleLarge),
            ),
          ),
          ?trailing,
        ],
      ),
    );
  }
}

/// Rows grouped on one rounded surface, separated by inset hairlines — the
/// iOS inset-grouped list. Not a card stack: one group per topic.
class InsetGroup extends StatelessWidget {
  const InsetGroup({
    required this.children,
    this.header,
    this.headerTrailing,
    this.footer,
    this.dividerIndent = 16,
    this.padding,
    super.key,
  });

  final List<Widget> children;
  final String? header;
  final Widget? headerTrailing;

  /// A footnote under the group, for the one sentence a row cannot hold.
  final String? footer;

  /// Where row separators start; align it with the row text, not the icon.
  final double dividerIndent;

  /// Inner padding for non-row content (a figure, a chart).
  final EdgeInsetsGeometry? padding;

  @override
  Widget build(BuildContext context) {
    final palette = LamToPalette.of(context);
    final rows = <Widget>[];
    for (var i = 0; i < children.length; i++) {
      if (i > 0) {
        rows.add(Divider(height: 1, indent: dividerIndent));
      }
      rows.add(children[i]);
    }
    Widget body = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: rows,
    );
    if (padding != null) body = Padding(padding: padding!, child: body);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        if (header != null) SectionHeader(header!, trailing: headerTrailing),
        Material(
          color: palette.surface,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(14),
          ),
          clipBehavior: Clip.antiAlias,
          child: body,
        ),
        if (footer != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: Text(footer!, style: Theme.of(context).textTheme.bodySmall),
          ),
      ],
    );
  }
}

/// A leading glyph on a soft tint well, so rows scan by shape first.
class IconWell extends StatelessWidget {
  const IconWell(this.icon, {this.tone, super.key});

  final IconData icon;

  /// Semantic tone for state-bearing rows; the brand tint otherwise.
  final StatusTone? tone;

  @override
  Widget build(BuildContext context) {
    final palette = LamToPalette.of(context);
    final colors = tone == null
        ? (bg: palette.primarySoft, fg: palette.primary)
        : statusToneColors(context, tone!);
    return Container(
      width: 36,
      height: 36,
      decoration: BoxDecoration(
        color: colors.bg,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Icon(icon, size: 20, color: colors.fg),
    );
  }
}

/// Label and value on one row inside an [InsetGroup]: the label names the
/// fact in quiet ink, the value carries it in full ink.
class InfoRow extends StatelessWidget {
  const InfoRow({
    required this.label,
    required this.value,
    this.valueStyle,
    this.child,
    super.key,
  });

  final String label;
  final String value;
  final TextStyle? valueStyle;

  /// Extra content under the value (a chip, a note).
  final Widget? child;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return MergeSemantics(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label, style: theme.textTheme.bodySmall),
            const SizedBox(height: 2),
            Text(value, style: valueStyle ?? theme.textTheme.bodyLarge),
            if (child != null) ...[const SizedBox(height: 8), child!],
          ],
        ),
      ),
    );
  }
}

/// A calm empty or not-yet state: what is missing, and the next step.
class EmptyState extends StatelessWidget {
  const EmptyState({
    required this.icon,
    required this.message,
    this.title,
    this.action,
    super.key,
  });

  final IconData icon;
  final String? title;
  final String message;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final palette = LamToPalette.of(context);
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 32),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          ExcludeSemantics(
            child: Container(
              width: 64,
              height: 64,
              decoration: BoxDecoration(
                color: palette.fill,
                shape: BoxShape.circle,
              ),
              child: Icon(icon, size: 30, color: palette.muted),
            ),
          ),
          const SizedBox(height: 16),
          if (title != null) ...[
            Text(
              title!,
              textAlign: TextAlign.center,
              style: theme.textTheme.titleSmall?.copyWith(fontSize: 17),
            ),
            const SizedBox(height: 6),
          ],
          Text(
            message,
            textAlign: TextAlign.center,
            style: theme.textTheme.bodyMedium?.copyWith(color: palette.muted),
          ),
          if (action != null) ...[const SizedBox(height: 20), action!],
        ],
      ),
    );
  }
}

/// One step of a vertical timeline: a marker, a rule to the next step, and
/// the content. Marker colour agrees with the words; it never replaces them.
class TimelineStep extends StatelessWidget {
  const TimelineStep({
    required this.child,
    this.icon,
    this.tone,
    this.isLast = false,
    super.key,
  });

  final Widget child;
  final IconData? icon;
  final StatusTone? tone;
  final bool isLast;

  @override
  Widget build(BuildContext context) {
    final palette = LamToPalette.of(context);
    final colors = tone == null
        ? (bg: palette.fill, fg: palette.muted)
        : statusToneColors(context, tone!);
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            width: 28,
            child: Column(
              children: [
                const SizedBox(height: 2),
                ExcludeSemantics(
                  child: Container(
                    width: 28,
                    height: 28,
                    decoration: BoxDecoration(
                      color: colors.bg,
                      shape: BoxShape.circle,
                    ),
                    child: Icon(
                      icon ?? Icons.circle,
                      size: icon == null ? 8 : 16,
                      color: colors.fg,
                    ),
                  ),
                ),
                if (!isLast)
                  Expanded(
                    child: Container(
                      width: 2,
                      margin: const EdgeInsets.symmetric(vertical: 4),
                      decoration: BoxDecoration(
                        color: palette.border,
                        borderRadius: BorderRadius.circular(1),
                      ),
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Padding(
              padding: EdgeInsets.only(top: 4, bottom: isLast ? 0 : 20),
              child: child,
            ),
          ),
        ],
      ),
    );
  }
}

/// Whether a row's figure can sit in a right-aligned trailing column. Once
/// text is scaled up the figure moves under the title instead, so an amount
/// is never squeezed, truncated, or broken across lines.
bool figuresTrail(BuildContext context) =>
    MediaQuery.textScalerOf(context).scale(1) <= 1.3;
