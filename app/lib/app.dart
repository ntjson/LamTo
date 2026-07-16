import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import 'core/failure.dart';
import 'core/occupancy.dart';
import 'core/providers.dart';
import 'features/auth/login_screen.dart';
import 'features/auth/occupancy_picker_screen.dart';
import 'features/auth/session_controller.dart';
import 'features/shell/home_shell.dart';
import 'l10n/app_localizations.dart';
import 'theme.dart';

class LamToApp extends StatelessWidget {
  const LamToApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'LamTo',
      theme: lamToTheme(Brightness.light),
      darkTheme: lamToTheme(Brightness.dark),
      localizationsDelegates: const [
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      supportedLocales: AppLocalizations.supportedLocales,
      locale: const Locale('vi'),
      home: const AppRouter(),
    );
  }
}

class AppRouter extends ConsumerStatefulWidget {
  const AppRouter({super.key});

  @override
  ConsumerState<AppRouter> createState() => _AppRouterState();
}

class _AppRouterState extends ConsumerState<AppRouter> {
  OccupancyHolder? _listened;

  @override
  void dispose() {
    _listened?.removeListener(_onOccupancyChanged);
    super.dispose();
  }

  void _onOccupancyChanged() {
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionControllerProvider);
    final holder = ref.watch(occupancyHolderProvider);
    if (!identical(_listened, holder)) {
      _listened?.removeListener(_onOccupancyChanged);
      _listened = holder;
      holder.addListener(_onOccupancyChanged);
    }

    return switch (session) {
      AsyncData(:final value) => switch (value) {
          SessionUnauthenticated() => const LoginScreen(),
          SessionAuthenticated(:final me) => _routeAuthenticated(me, holder),
          SessionBootstrapError(:final failure) => BootstrapErrorScreen(
              failure: failure,
              onRetry: () => ref.invalidate(sessionControllerProvider),
            ),
        },
      AsyncError(:final error) => BootstrapErrorScreen(
          failure: error is Failure ? error : Failure(code: 'server_error'),
          onRetry: () => ref.invalidate(sessionControllerProvider),
        ),
      _ => const Scaffold(
          body: Center(child: CircularProgressIndicator.adaptive()),
        ),
    };
  }

  /// Pure routing over session + occupancy holder (no mutations in build).
  Widget _routeAuthenticated(Me me, OccupancyHolder holder) {
    if (me.occupancies.isEmpty) {
      return const OccupancyPickerScreen.empty();
    }
    if (me.occupancies.length == 1) {
      // Single occupancy is selected during bootstrap; just land on shell.
      return const HomeShell();
    }
    final selected = holder.occupancyId;
    if (selected != null && me.occupancies.any((o) => o.id == selected)) {
      return const HomeShell();
    }
    return OccupancyPickerScreen(me: me);
  }
}

/// Retryable bootstrap failure UI (clarification #1).
class BootstrapErrorScreen extends StatelessWidget {
  const BootstrapErrorScreen({
    required this.failure,
    required this.onRetry,
    super.key,
  });
  final Failure failure;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    return Scaffold(
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(failureMessage(failure, l10n), textAlign: TextAlign.center),
              const SizedBox(height: 16),
              FilledButton(onPressed: onRetry, child: Text(l10n.bootstrapRetry)),
            ],
          ),
        ),
      ),
    );
  }
}
