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
import 'features/ledger/ledger_detail_screen.dart';
import 'features/notifications/deep_link.dart';
import 'features/notifications/notifications_screen.dart';
import 'features/reports/issue_detail_screen.dart';
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

  /// Last push-open payload waiting for [SessionAuthenticated] (last-wins).
  Map<String, String>? _pendingPush;
  bool _pushWired = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _wirePushTaps());
  }

  Future<void> _wirePushTaps() async {
    if (_pushWired) return;
    _pushWired = true;
    final source = ref.read(pushTokenSourceProvider);
    final initial = await source.initialMessageData();
    if (initial != null) _openPush(initial);
    source.onMessageOpened.listen(_openPush);
  }

  bool get _isAuthenticated {
    final session = ref.read(sessionControllerProvider);
    return switch (session) {
      AsyncData(value: SessionAuthenticated()) => true,
      _ => false,
    };
  }

  /// Gate navigation: buffer while unauthenticated / bootstrapping; apply when
  /// [SessionAuthenticated]. Destinations still re-fetch via the API (A8).
  void _openPush(Map<String, String> data) {
    if (!mounted) return;
    if (!_isAuthenticated) {
      _pendingPush = data;
      return;
    }
    _navigatePush(data);
  }

  void _flushPendingPush() {
    final pending = _pendingPush;
    if (pending == null || !mounted) return;
    if (!_isAuthenticated) return;
    _pendingPush = null;
    _navigatePush(pending);
  }

  void _navigatePush(Map<String, String> data) {
    if (!mounted) return;
    final link = parsePushLink(type: data['type'], id: data['id']);
    final navigator = Navigator.of(context);
    switch (link) {
      case DeepLinkReport(:final id):
        navigator.push(MaterialPageRoute(
            builder: (_) => IssueDetailScreen(reportId: id)));
      case DeepLinkLedger(:final id):
        navigator.push(MaterialPageRoute(
            builder: (_) => LedgerDetailScreen(entryId: id)));
      case DeepLinkFeed():
        navigator.push(MaterialPageRoute(
            builder: (_) => const NotificationsScreen()));
    }
  }

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

    // When auth becomes ready, apply any buffered cold-start / background tap.
    ref.listen(sessionControllerProvider, (previous, next) {
      final authed = switch (next) {
        AsyncData(value: SessionAuthenticated()) => true,
        _ => false,
      };
      if (!authed) return;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _flushPendingPush();
      });
    });

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
