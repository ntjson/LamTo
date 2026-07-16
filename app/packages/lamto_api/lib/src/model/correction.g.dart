// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'correction.dart';

// **************************************************************************
// BuiltValueGenerator
// **************************************************************************

class _$Correction extends Correction {
  @override
  final int id;
  @override
  final String status;
  @override
  final String reason;

  factory _$Correction([void Function(CorrectionBuilder)? updates]) =>
      (CorrectionBuilder()..update(updates))._build();

  _$Correction._({required this.id, required this.status, required this.reason})
      : super._();
  @override
  Correction rebuild(void Function(CorrectionBuilder) updates) =>
      (toBuilder()..update(updates)).build();

  @override
  CorrectionBuilder toBuilder() => CorrectionBuilder()..replace(this);

  @override
  bool operator ==(Object other) {
    if (identical(other, this)) return true;
    return other is Correction &&
        id == other.id &&
        status == other.status &&
        reason == other.reason;
  }

  @override
  int get hashCode {
    var _$hash = 0;
    _$hash = $jc(_$hash, id.hashCode);
    _$hash = $jc(_$hash, status.hashCode);
    _$hash = $jc(_$hash, reason.hashCode);
    _$hash = $jf(_$hash);
    return _$hash;
  }

  @override
  String toString() {
    return (newBuiltValueToStringHelper(r'Correction')
          ..add('id', id)
          ..add('status', status)
          ..add('reason', reason))
        .toString();
  }
}

class CorrectionBuilder implements Builder<Correction, CorrectionBuilder> {
  _$Correction? _$v;

  int? _id;
  int? get id => _$this._id;
  set id(int? id) => _$this._id = id;

  String? _status;
  String? get status => _$this._status;
  set status(String? status) => _$this._status = status;

  String? _reason;
  String? get reason => _$this._reason;
  set reason(String? reason) => _$this._reason = reason;

  CorrectionBuilder() {
    Correction._defaults(this);
  }

  CorrectionBuilder get _$this {
    final $v = _$v;
    if ($v != null) {
      _id = $v.id;
      _status = $v.status;
      _reason = $v.reason;
      _$v = null;
    }
    return this;
  }

  @override
  void replace(Correction other) {
    _$v = other as _$Correction;
  }

  @override
  void update(void Function(CorrectionBuilder)? updates) {
    if (updates != null) updates(this);
  }

  @override
  Correction build() => _build();

  _$Correction _build() {
    final _$result = _$v ??
        _$Correction._(
          id: BuiltValueNullFieldError.checkNotNull(id, r'Correction', 'id'),
          status: BuiltValueNullFieldError.checkNotNull(
              status, r'Correction', 'status'),
          reason: BuiltValueNullFieldError.checkNotNull(
              reason, r'Correction', 'reason'),
        );
    replace(_$result);
    return _$result;
  }
}

// ignore_for_file: deprecated_member_use_from_same_package,type=lint
