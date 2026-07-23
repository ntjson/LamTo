import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/failure.dart';
import '../../core/page_body.dart';
import '../../core/providers.dart';
import '../../l10n/app_localizations.dart';
import 'registration_status_screen.dart';
import 'registration_status_store.dart';

class RegistrationScreen extends ConsumerStatefulWidget {
  const RegistrationScreen({super.key});

  @override
  ConsumerState<RegistrationScreen> createState() => _RegistrationScreenState();
}

class _RegistrationScreenState extends ConsumerState<RegistrationScreen> {
  final _formKey = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _phone = TextEditingController();
  final _email = TextEditingController();
  final _password = TextEditingController();
  List<RegistrationBuilding>? _buildings;
  int? _buildingId;
  int? _unitId;
  String? _error;
  bool _busy = false;
  bool _checkingSecret = true;

  @override
  void initState() {
    super.initState();
    _open();
  }

  Future<void> _open() async {
    final secret = await ref.read(registrationStatusStoreProvider).read();
    if (!mounted) return;
    if (secret != null) {
      await Navigator.of(context).pushReplacement(
        MaterialPageRoute<void>(
          builder: (_) => RegistrationStatusScreen(secret: secret),
        ),
      );
      return;
    }
    try {
      final buildings = await ref
          .read(registrationRepositoryProvider)
          .options();
      if (mounted) setState(() => _buildings = buildings.toList());
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
      if (mounted) setState(() => _checkingSecret = false);
    }
  }

  @override
  void dispose() {
    _name.dispose();
    _phone.dispose();
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final email = _email.text.trim();
      final submission = await ref
          .read(registrationRepositoryProvider)
          .submit(
            RegistrationCreateRequest(
              (b) => b
                ..fullName = _name.text.trim()
                ..phone = _phone.text.trim()
                ..email = email.isEmpty ? null : email
                ..password = _password.text
                ..buildingId = _buildingId
                ..unitId = _unitId,
            ),
          );
      _password.clear();
      final secret = RegistrationStatusSecret(
        token: submission.statusToken,
        phone: submission.phone,
      );
      await ref.read(registrationStatusStoreProvider).save(secret);
      if (!mounted) return;
      await Navigator.of(context).pushReplacement(
        MaterialPageRoute<void>(
          builder: (_) => RegistrationStatusScreen(secret: secret),
        ),
      );
    } on DioException catch (error) {
      if (mounted) {
        setState(
          () => _error = failureMessage(
            Failure.fromDio(error),
            AppLocalizations.of(context)!,
          ),
        );
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
      _password.clear();
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final building = _buildings
        ?.where((item) => item.id == _buildingId)
        .firstOrNull;
    if (_checkingSecret || (_buildings == null && _error == null)) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator.adaptive()),
      );
    }
    return Scaffold(
      appBar: AppBar(title: Text(l10n.registrationTitle)),
      body: PageBody(
        child: Form(
          key: _formKey,
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              TextFormField(
                key: const Key('registration_name'),
                controller: _name,
                decoration: InputDecoration(
                  labelText: l10n.registrationFullName,
                ),
                validator: _required,
              ),
              TextFormField(
                key: const Key('registration_phone'),
                controller: _phone,
                keyboardType: TextInputType.phone,
                decoration: InputDecoration(labelText: l10n.registrationPhone),
                validator: _required,
              ),
              TextFormField(
                key: const Key('registration_email'),
                controller: _email,
                keyboardType: TextInputType.emailAddress,
                decoration: InputDecoration(labelText: l10n.registrationEmail),
              ),
              TextFormField(
                key: const Key('registration_password'),
                controller: _password,
                obscureText: true,
                decoration: InputDecoration(
                  labelText: l10n.registrationPassword,
                ),
                validator: _required,
              ),
              DropdownButtonFormField<int>(
                key: const Key('registration_building'),
                initialValue: _buildingId,
                decoration: InputDecoration(
                  labelText: l10n.registrationBuilding,
                ),
                items: [
                  for (final item
                      in _buildings ?? const <RegistrationBuilding>[])
                    DropdownMenuItem(value: item.id, child: Text(item.name)),
                ],
                onChanged: (value) => setState(() {
                  _buildingId = value;
                  _unitId = null;
                }),
                validator: (value) =>
                    value == null ? l10n.registrationRequired : null,
              ),
              KeyedSubtree(
                key: ValueKey(_buildingId),
                child: DropdownButtonFormField<int>(
                  key: const Key('registration_unit'),
                  initialValue: _unitId,
                  decoration: InputDecoration(labelText: l10n.registrationUnit),
                  items: [
                    for (final item
                        in building?.units ?? const <RegistrationUnit>[])
                      DropdownMenuItem(value: item.id, child: Text(item.label)),
                  ],
                  onChanged: building == null
                      ? null
                      : (value) => setState(() => _unitId = value),
                  validator: (value) =>
                      value == null ? l10n.registrationRequired : null,
                ),
              ),
              if (_error != null)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Text(
                    _error!,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                ),
              const SizedBox(height: 20),
              FilledButton(
                onPressed: _busy ? null : _submit,
                child: Text(l10n.registrationSubmit),
              ),
            ],
          ),
        ),
      ),
    );
  }

  String? _required(String? value) => value == null || value.trim().isEmpty
      ? AppLocalizations.of(context)!.registrationRequired
      : null;
}
