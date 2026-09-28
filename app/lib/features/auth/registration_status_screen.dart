import 'package:flutter/cupertino.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/failure.dart';
import '../../core/adaptive_buttons.dart';
import '../../core/adaptive_page_route.dart';
import '../../core/page_body.dart';
import '../../core/providers.dart';
import '../../l10n/app_localizations.dart';
import '../../theme.dart';
import '../../widgets/brand_identity.dart';
import '../../widgets/grouped.dart';
import 'login_screen.dart';
import 'registration_screen.dart';
import 'registration_status_store.dart';

class RegistrationStatusScreen extends ConsumerStatefulWidget {
  const RegistrationStatusScreen({required this.secret, super.key});

  final RegistrationStatusSecret secret;

  @override
  ConsumerState<RegistrationStatusScreen> createState() =>
      _RegistrationStatusScreenState();
}

class _RegistrationStatusScreenState
    extends ConsumerState<RegistrationStatusScreen>
    with WidgetsBindingObserver {
  RegistrationStatus? _status;
  String? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _refresh();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _refresh();
    }
  }

  Future<void> _refresh() async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final status = await ref
          .read(registrationRepositoryProvider)
          .status(widget.secret.token);
      if (status.status == RegistrationStatusEnum.EXPIRED) {
        await ref.read(registrationStatusStoreProvider).clear();
      }
      if (mounted) {
        setState(() => _status = status);
      }
    } catch (error) {
      if (mounted) {
        setState(
          () => _error = failureMessage(
            Failure.fromObject(error),
            AppLocalizations.of(context)!,
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _busy = false);
      }
    }
  }

  Future<void> _newRequest() async {
    await ref.read(registrationStatusStoreProvider).clear();
    if (!mounted) return;
    await Navigator.of(context).pushReplacement(
      adaptivePageRoute<void>(builder: (_) => const RegistrationScreen()),
    );
  }

  Future<void> _login() async {
    await ref.read(registrationStatusStoreProvider).clear();
    if (!mounted) return;
    await Navigator.of(context).pushAndRemoveUntil(
      adaptivePageRoute<void>(
        builder: (_) => LoginScreen(initialIdentifier: widget.secret.phone),
      ),
      (route) => false,
    );
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final status = _status;
    return _page(
      PageBody(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20),
          child: status == null
              ? Center(
                  child: _error == null
                      ? const CircularProgressIndicator.adaptive()
                      : Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Semantics(
                              key: const Key('registration_status_error'),
                              liveRegion: true,
                              child: Text(_error!),
                            ),
                            AdaptiveOutlinedButton(
                              onPressed: _refresh,
                              child: Text(l10n.commonRetry),
                            ),
                          ],
                        ),
                )
              : Semantics(
                  key: const Key('registration_status_state'),
                  liveRegion: true,
                  child: ListView(
                    children: [
                      const SizedBox(height: 8),
                      const BrandMark(size: 64),
                      const SizedBox(height: 28),
                      _StatusCard(
                        place: '${status.building} · ${status.unit}',
                        status: status,
                        busy: _busy,
                        onRefresh: _refresh,
                        onNewRequest: _newRequest,
                        onLogin: _login,
                      ),
                      if (_error != null)
                        Semantics(
                          key: const Key('registration_status_error'),
                          liveRegion: true,
                          child: Padding(
                            padding: const EdgeInsets.only(top: 16),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                StatusNotice(
                                  tone: StatusTone.error,
                                  message: _error!,
                                ),
                                const SizedBox(height: 8),
                                AdaptiveOutlinedButton(
                                  onPressed: _refresh,
                                  child: Text(l10n.commonRetry),
                                ),
                              ],
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
        ),
      ),
      l10n,
    );
  }

  Widget _page(Widget child, AppLocalizations l10n) {
    if (defaultTargetPlatform == TargetPlatform.iOS) {
      return CupertinoPageScaffold(
        navigationBar: CupertinoNavigationBar(
          middle: Text(l10n.registrationTitle),
        ),
        child: SafeArea(child: child),
      );
    }
    return Scaffold(
      appBar: AppBar(title: Text(l10n.registrationTitle)),
      body: child,
    );
  }
}

/// Where the request stands, in one card: a state glyph, the place, what it
/// means, and the one next step.
class _StatusCard extends StatelessWidget {
  const _StatusCard({
    required this.place,
    required this.status,
    required this.busy,
    required this.onRefresh,
    required this.onNewRequest,
    required this.onLogin,
  });

  final String place;
  final RegistrationStatus status;
  final bool busy;
  final VoidCallback onRefresh;
  final VoidCallback onNewRequest;
  final VoidCallback onLogin;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final theme = Theme.of(context);
    final (icon, tone, title, body, action) = switch (status.status) {
      RegistrationStatusEnum.PENDING => (
        Icons.hourglass_top_rounded,
        StatusTone.warning,
        l10n.registrationPendingTitle,
        l10n.registrationPendingBody,
        AdaptiveOutlinedButton(
          onPressed: busy ? null : onRefresh,
          child: Text(l10n.registrationRefresh),
        ),
      ),
      RegistrationStatusEnum.REJECTED => (
        Icons.cancel_outlined,
        StatusTone.error,
        l10n.registrationRejectedTitle,
        status.rejectionReason!,
        AdaptiveFilledButton(
          onPressed: onNewRequest,
          child: Text(l10n.registrationNewRequest),
        ),
      ),
      RegistrationStatusEnum.APPROVED => (
        Icons.check_circle_outline,
        StatusTone.success,
        l10n.registrationApprovedTitle,
        l10n.registrationApprovedBody,
        AdaptiveFilledButton(
          onPressed: onLogin,
          child: Text(l10n.registrationContinueLogin),
        ),
      ),
      _ => (
        Icons.schedule,
        StatusTone.warning,
        l10n.registrationExpiredTitle,
        l10n.registrationExpiredBody,
        AdaptiveFilledButton(
          onPressed: onNewRequest,
          child: Text(l10n.registrationNewRequest),
        ),
      ),
    };
    final colors = statusToneColors(context, tone);
    return InsetGroup(
      padding: const EdgeInsets.all(24),
      children: [
        Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Center(
              child: Container(
                width: 56,
                height: 56,
                decoration: BoxDecoration(
                  color: colors.bg,
                  shape: BoxShape.circle,
                ),
                child: Icon(icon, color: colors.fg, size: 30),
              ),
            ),
            const SizedBox(height: 16),
            Text(
              place,
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyMedium?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
            const SizedBox(height: 6),
            Text(
              title,
              textAlign: TextAlign.center,
              style: theme.textTheme.titleLarge,
            ),
            const SizedBox(height: 8),
            Text(body, textAlign: TextAlign.center),
            const SizedBox(height: 24),
            action,
          ],
        ),
      ],
    );
  }
}
