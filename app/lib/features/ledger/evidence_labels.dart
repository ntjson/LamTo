import 'package:flutter/material.dart';

import '../../l10n/app_localizations.dart';
import '../../theme.dart';

/// Distinct presentation per evidence level (spec 5.1/5.2): LOCAL_SIGNED never
/// borrows chain wording; MISMATCH renders prominently; color never alone.
String evidenceLevelLabel(String level, AppLocalizations l10n) =>
    switch (level) {
      'CHAIN_CONFIRMED' => l10n.evidenceChain,
      'LOCAL_SIGNED' => l10n.evidenceLocal,
      'MISMATCH' => l10n.evidenceMismatch,
      _ => l10n.evidencePending,
    };

String integrityStatusLabel(String status, AppLocalizations l10n) =>
    switch (status) {
      'VERIFIED' => l10n.integrityVerified,
      'MISMATCH' => l10n.integrityMismatch,
      'UNAVAILABLE' => l10n.integrityUnavailable,
      _ => l10n.integrityUnchecked,
    };

/// Role-aware approver line for the plain-language story (A1).
String approverLine(String role, String name, AppLocalizations l10n) =>
    switch (role) {
      'board' => l10n.ledgerApproverBoard(name),
      'resident_rep' => l10n.ledgerApproverRep(name),
      'emergency' => l10n.ledgerApproverEmergency(name),
      _ => l10n.ledgerApproverGeneric(name),
    };

typedef _Style = ({Color bg, Color fg, IconData icon});

_Style _styleFor(String level) => switch (level) {
      'CHAIN_CONFIRMED' => (
          bg: const Color(0xFFE7F6EE), // DESIGN.md success-bg
          fg: LamToColors.success,
          icon: Icons.verified_outlined,
        ),
      'MISMATCH' => (
          bg: const Color(0xFFFEF3F2), // error-bg
          fg: LamToColors.error,
          icon: Icons.error_outline,
        ),
      'LOCAL_SIGNED' => (
          bg: const Color(0xFFEFF8FF), // info-bg
          fg: LamToColors.info,
          icon: Icons.lock_outline,
        ),
      _ => (
          bg: const Color(0xFFFFF6DD), // warning-bg
          fg: LamToColors.warning,
          icon: Icons.hourglass_empty,
        ),
    };

class EvidenceBadge extends StatelessWidget {
  const EvidenceBadge({required this.level, super.key});
  final String level;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final style = _styleFor(level);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: style.bg,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(style.icon, size: 16, color: style.fg),
          const SizedBox(width: 6),
          Flexible(
            child: Text(
              evidenceLevelLabel(level, l10n),
              style: TextStyle(
                color: style.fg,
                fontSize: 13,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
