// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'ledger_approver.dart';

// **************************************************************************
// BuiltValueGenerator
// **************************************************************************

class _$LedgerApprover extends LedgerApprover {
  @override
  final String role;
  @override
  final String name;
  @override
  final String decision;

  factory _$LedgerApprover([void Function(LedgerApproverBuilder)? updates]) =>
      (LedgerApproverBuilder()..update(updates))._build();

  _$LedgerApprover._(
      {required this.role, required this.name, required this.decision})
      : super._();
  @override
  LedgerApprover rebuild(void Function(LedgerApproverBuilder) updates) =>
      (toBuilder()..update(updates)).build();

  @override
  LedgerApproverBuilder toBuilder() => LedgerApproverBuilder()..replace(this);

  @override
  bool operator ==(Object other) {
    if (identical(other, this)) return true;
    return other is LedgerApprover &&
        role == other.role &&
        name == other.name &&
        decision == other.decision;
  }

  @override
  int get hashCode {
    var _$hash = 0;
    _$hash = $jc(_$hash, role.hashCode);
    _$hash = $jc(_$hash, name.hashCode);
    _$hash = $jc(_$hash, decision.hashCode);
    _$hash = $jf(_$hash);
    return _$hash;
  }

  @override
  String toString() {
    return (newBuiltValueToStringHelper(r'LedgerApprover')
          ..add('role', role)
          ..add('name', name)
          ..add('decision', decision))
        .toString();
  }
}

class LedgerApproverBuilder
    implements Builder<LedgerApprover, LedgerApproverBuilder> {
  _$LedgerApprover? _$v;

  String? _role;
  String? get role => _$this._role;
  set role(String? role) => _$this._role = role;

  String? _name;
  String? get name => _$this._name;
  set name(String? name) => _$this._name = name;

  String? _decision;
  String? get decision => _$this._decision;
  set decision(String? decision) => _$this._decision = decision;

  LedgerApproverBuilder() {
    LedgerApprover._defaults(this);
  }

  LedgerApproverBuilder get _$this {
    final $v = _$v;
    if ($v != null) {
      _role = $v.role;
      _name = $v.name;
      _decision = $v.decision;
      _$v = null;
    }
    return this;
  }

  @override
  void replace(LedgerApprover other) {
    _$v = other as _$LedgerApprover;
  }

  @override
  void update(void Function(LedgerApproverBuilder)? updates) {
    if (updates != null) updates(this);
  }

  @override
  LedgerApprover build() => _build();

  _$LedgerApprover _build() {
    final _$result = _$v ??
        _$LedgerApprover._(
          role: BuiltValueNullFieldError.checkNotNull(
              role, r'LedgerApprover', 'role'),
          name: BuiltValueNullFieldError.checkNotNull(
              name, r'LedgerApprover', 'name'),
          decision: BuiltValueNullFieldError.checkNotNull(
              decision, r'LedgerApprover', 'decision'),
        );
    replace(_$result);
    return _$result;
  }
}

// ignore_for_file: deprecated_member_use_from_same_package,type=lint
