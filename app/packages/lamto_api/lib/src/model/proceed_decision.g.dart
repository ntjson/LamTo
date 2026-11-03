// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'proceed_decision.dart';

// **************************************************************************
// BuiltValueGenerator
// **************************************************************************

class _$ProceedDecision extends ProceedDecision {
  @override
  final String decidedBy;
  @override
  final DateTime decidedAt;

  factory _$ProceedDecision([void Function(ProceedDecisionBuilder)? updates]) =>
      (ProceedDecisionBuilder()..update(updates))._build();

  _$ProceedDecision._({required this.decidedBy, required this.decidedAt})
      : super._();
  @override
  ProceedDecision rebuild(void Function(ProceedDecisionBuilder) updates) =>
      (toBuilder()..update(updates)).build();

  @override
  ProceedDecisionBuilder toBuilder() => ProceedDecisionBuilder()..replace(this);

  @override
  bool operator ==(Object other) {
    if (identical(other, this)) return true;
    return other is ProceedDecision &&
        decidedBy == other.decidedBy &&
        decidedAt == other.decidedAt;
  }

  @override
  int get hashCode {
    var _$hash = 0;
    _$hash = $jc(_$hash, decidedBy.hashCode);
    _$hash = $jc(_$hash, decidedAt.hashCode);
    _$hash = $jf(_$hash);
    return _$hash;
  }

  @override
  String toString() {
    return (newBuiltValueToStringHelper(r'ProceedDecision')
          ..add('decidedBy', decidedBy)
          ..add('decidedAt', decidedAt))
        .toString();
  }
}

class ProceedDecisionBuilder
    implements Builder<ProceedDecision, ProceedDecisionBuilder> {
  _$ProceedDecision? _$v;

  String? _decidedBy;
  String? get decidedBy => _$this._decidedBy;
  set decidedBy(String? decidedBy) => _$this._decidedBy = decidedBy;

  DateTime? _decidedAt;
  DateTime? get decidedAt => _$this._decidedAt;
  set decidedAt(DateTime? decidedAt) => _$this._decidedAt = decidedAt;

  ProceedDecisionBuilder() {
    ProceedDecision._defaults(this);
  }

  ProceedDecisionBuilder get _$this {
    final $v = _$v;
    if ($v != null) {
      _decidedBy = $v.decidedBy;
      _decidedAt = $v.decidedAt;
      _$v = null;
    }
    return this;
  }

  @override
  void replace(ProceedDecision other) {
    _$v = other as _$ProceedDecision;
  }

  @override
  void update(void Function(ProceedDecisionBuilder)? updates) {
    if (updates != null) updates(this);
  }

  @override
  ProceedDecision build() => _build();

  _$ProceedDecision _build() {
    final _$result = _$v ??
        _$ProceedDecision._(
          decidedBy: BuiltValueNullFieldError.checkNotNull(
              decidedBy, r'ProceedDecision', 'decidedBy'),
          decidedAt: BuiltValueNullFieldError.checkNotNull(
              decidedAt, r'ProceedDecision', 'decidedAt'),
        );
    replace(_$result);
    return _$result;
  }
}

// ignore_for_file: deprecated_member_use_from_same_package,type=lint
