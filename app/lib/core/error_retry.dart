import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
import 'adaptive_buttons.dart';
import 'failure.dart';

/// Inline failure state: resident copy plus an explicit retry action
/// (PRODUCT.md principle 5 — expose failure honestly, give the next safe
/// action). Accepts any thrown object; coercion goes through [Failure].
class ErrorRetry extends StatelessWidget {
  const ErrorRetry({required this.error, required this.onRetry, super.key});

  final Object error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 20),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            failureMessage(Failure.fromObject(error), l10n),
            textAlign: TextAlign.center,
            style: theme.textTheme.bodyMedium?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
          const SizedBox(height: 14),
          AdaptiveOutlinedButton(
            onPressed: onRetry,
            icon: const Icon(Icons.refresh),
            child: Text(l10n.commonRetry),
          ),
        ],
      ),
    );
  }
}
