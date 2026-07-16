// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'report_work_order.dart';

// **************************************************************************
// BuiltValueGenerator
// **************************************************************************

class _$ReportWorkOrder extends ReportWorkOrder {
  @override
  final int id;
  @override
  final String status;
  @override
  final DateTime deadlineAt;
  @override
  final DateTime? completedAt;
  @override
  final DateTime? acceptedAt;
  @override
  final bool canRate;

  factory _$ReportWorkOrder([void Function(ReportWorkOrderBuilder)? updates]) =>
      (ReportWorkOrderBuilder()..update(updates))._build();

  _$ReportWorkOrder._(
      {required this.id,
      required this.status,
      required this.deadlineAt,
      this.completedAt,
      this.acceptedAt,
      required this.canRate})
      : super._();
  @override
  ReportWorkOrder rebuild(void Function(ReportWorkOrderBuilder) updates) =>
      (toBuilder()..update(updates)).build();

  @override
  ReportWorkOrderBuilder toBuilder() => ReportWorkOrderBuilder()..replace(this);

  @override
  bool operator ==(Object other) {
    if (identical(other, this)) return true;
    return other is ReportWorkOrder &&
        id == other.id &&
        status == other.status &&
        deadlineAt == other.deadlineAt &&
        completedAt == other.completedAt &&
        acceptedAt == other.acceptedAt &&
        canRate == other.canRate;
  }

  @override
  int get hashCode {
    var _$hash = 0;
    _$hash = $jc(_$hash, id.hashCode);
    _$hash = $jc(_$hash, status.hashCode);
    _$hash = $jc(_$hash, deadlineAt.hashCode);
    _$hash = $jc(_$hash, completedAt.hashCode);
    _$hash = $jc(_$hash, acceptedAt.hashCode);
    _$hash = $jc(_$hash, canRate.hashCode);
    _$hash = $jf(_$hash);
    return _$hash;
  }

  @override
  String toString() {
    return (newBuiltValueToStringHelper(r'ReportWorkOrder')
          ..add('id', id)
          ..add('status', status)
          ..add('deadlineAt', deadlineAt)
          ..add('completedAt', completedAt)
          ..add('acceptedAt', acceptedAt)
          ..add('canRate', canRate))
        .toString();
  }
}

class ReportWorkOrderBuilder
    implements Builder<ReportWorkOrder, ReportWorkOrderBuilder> {
  _$ReportWorkOrder? _$v;

  int? _id;
  int? get id => _$this._id;
  set id(int? id) => _$this._id = id;

  String? _status;
  String? get status => _$this._status;
  set status(String? status) => _$this._status = status;

  DateTime? _deadlineAt;
  DateTime? get deadlineAt => _$this._deadlineAt;
  set deadlineAt(DateTime? deadlineAt) => _$this._deadlineAt = deadlineAt;

  DateTime? _completedAt;
  DateTime? get completedAt => _$this._completedAt;
  set completedAt(DateTime? completedAt) => _$this._completedAt = completedAt;

  DateTime? _acceptedAt;
  DateTime? get acceptedAt => _$this._acceptedAt;
  set acceptedAt(DateTime? acceptedAt) => _$this._acceptedAt = acceptedAt;

  bool? _canRate;
  bool? get canRate => _$this._canRate;
  set canRate(bool? canRate) => _$this._canRate = canRate;

  ReportWorkOrderBuilder() {
    ReportWorkOrder._defaults(this);
  }

  ReportWorkOrderBuilder get _$this {
    final $v = _$v;
    if ($v != null) {
      _id = $v.id;
      _status = $v.status;
      _deadlineAt = $v.deadlineAt;
      _completedAt = $v.completedAt;
      _acceptedAt = $v.acceptedAt;
      _canRate = $v.canRate;
      _$v = null;
    }
    return this;
  }

  @override
  void replace(ReportWorkOrder other) {
    _$v = other as _$ReportWorkOrder;
  }

  @override
  void update(void Function(ReportWorkOrderBuilder)? updates) {
    if (updates != null) updates(this);
  }

  @override
  ReportWorkOrder build() => _build();

  _$ReportWorkOrder _build() {
    final _$result = _$v ??
        _$ReportWorkOrder._(
          id: BuiltValueNullFieldError.checkNotNull(
              id, r'ReportWorkOrder', 'id'),
          status: BuiltValueNullFieldError.checkNotNull(
              status, r'ReportWorkOrder', 'status'),
          deadlineAt: BuiltValueNullFieldError.checkNotNull(
              deadlineAt, r'ReportWorkOrder', 'deadlineAt'),
          completedAt: completedAt,
          acceptedAt: acceptedAt,
          canRate: BuiltValueNullFieldError.checkNotNull(
              canRate, r'ReportWorkOrder', 'canRate'),
        );
    replace(_$result);
    return _$result;
  }
}

// ignore_for_file: deprecated_member_use_from_same_package,type=lint
