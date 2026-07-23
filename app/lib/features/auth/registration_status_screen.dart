import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/failure.dart';
import '../../core/page_body.dart';
import '../../core/providers.dart';
import '../../l10n/app_localizations.dart';
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
      MaterialPageRoute<void>(builder: (_) => const RegistrationScreen()),
    );
  }

  Future<void> _login() async {
    await ref.read(registrationStatusStoreProvider).clear();
    if (!mounted) return;
    await Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute<void>(
        builder: (_) => LoginScreen(initialIdentifier: widget.secret.phone),
      ),
      (route) => false,
    );
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final status = _status;
    return Scaffold(
      appBar: AppBar(title: Text(l10n.registrationTitle)),
      body: PageBody(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: status == null
              ? Center(
                  child: _error == null
                      ? const CircularProgressIndicator.adaptive()
                      : Text(_error!),
                )
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      '${status.building} · ${status.unit}',
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    const SizedBox(height: 16),
                    if (status.status == RegistrationStatusEnum.PENDING) ...[
                      Text(
                        l10n.registrationPendingTitle,
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      Text(l10n.registrationPendingBody),
                      const SizedBox(height: 16),
                      OutlinedButton(
                        onPressed: _busy ? null : _refresh,
                        child: Text(l10n.registrationRefresh),
                      ),
                    ] else if (status.status ==
                        RegistrationStatusEnum.REJECTED) ...[
                      Text(
                        l10n.registrationRejectedTitle,
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      Text(status.rejectionReason!),
                      const SizedBox(height: 16),
                      FilledButton(
                        onPressed: _newRequest,
                        child: Text(l10n.registrationNewRequest),
                      ),
                    ] else if (status.status ==
                        RegistrationStatusEnum.APPROVED) ...[
                      Text(
                        l10n.registrationApprovedTitle,
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      Text(l10n.registrationApprovedBody),
                      const SizedBox(height: 16),
                      FilledButton(
                        onPressed: _login,
                        child: Text(l10n.registrationContinueLogin),
                      ),
                    ] else ...[
                      Text(
                        l10n.registrationExpiredTitle,
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      Text(l10n.registrationExpiredBody),
                      const SizedBox(height: 16),
                      FilledButton(
                        onPressed: _newRequest,
                        child: Text(l10n.registrationNewRequest),
                      ),
                    ],
                    if (_error != null)
                      Text(
                        _error!,
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.error,
                        ),
                      ),
                  ],
                ),
        ),
      ),
    );
  }
}
