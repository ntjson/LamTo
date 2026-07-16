// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'work_rating_result.dart';

// **************************************************************************
// BuiltValueGenerator
// **************************************************************************

class _$WorkRatingResult extends WorkRatingResult {
  @override
  final int id;
  @override
  final int workOrderId;
  @override
  final int score;

  factory _$WorkRatingResult(
          [void Function(WorkRatingResultBuilder)? updates]) =>
      (WorkRatingResultBuilder()..update(updates))._build();

  _$WorkRatingResult._(
      {required this.id, required this.workOrderId, required this.score})
      : super._();
  @override
  WorkRatingResult rebuild(void Function(WorkRatingResultBuilder) updates) =>
      (toBuilder()..update(updates)).build();

  @override
  WorkRatingResultBuilder toBuilder() =>
      WorkRatingResultBuilder()..replace(this);

  @override
  bool operator ==(Object other) {
    if (identical(other, this)) return true;
    return other is WorkRatingResult &&
        id == other.id &&
        workOrderId == other.workOrderId &&
        score == other.score;
  }

  @override
  int get hashCode {
    var _$hash = 0;
    _$hash = $jc(_$hash, id.hashCode);
    _$hash = $jc(_$hash, workOrderId.hashCode);
    _$hash = $jc(_$hash, score.hashCode);
    _$hash = $jf(_$hash);
    return _$hash;
  }

  @override
  String toString() {
    return (newBuiltValueToStringHelper(r'WorkRatingResult')
          ..add('id', id)
          ..add('workOrderId', workOrderId)
          ..add('score', score))
        .toString();
  }
}

class WorkRatingResultBuilder
    implements Builder<WorkRatingResult, WorkRatingResultBuilder> {
  _$WorkRatingResult? _$v;

  int? _id;
  int? get id => _$this._id;
  set id(int? id) => _$this._id = id;

  int? _workOrderId;
  int? get workOrderId => _$this._workOrderId;
  set workOrderId(int? workOrderId) => _$this._workOrderId = workOrderId;

  int? _score;
  int? get score => _$this._score;
  set score(int? score) => _$this._score = score;

  WorkRatingResultBuilder() {
    WorkRatingResult._defaults(this);
  }

  WorkRatingResultBuilder get _$this {
    final $v = _$v;
    if ($v != null) {
      _id = $v.id;
      _workOrderId = $v.workOrderId;
      _score = $v.score;
      _$v = null;
    }
    return this;
  }

  @override
  void replace(WorkRatingResult other) {
    _$v = other as _$WorkRatingResult;
  }

  @override
  void update(void Function(WorkRatingResultBuilder)? updates) {
    if (updates != null) updates(this);
  }

  @override
  WorkRatingResult build() => _build();

  _$WorkRatingResult _build() {
    final _$result = _$v ??
        _$WorkRatingResult._(
          id: BuiltValueNullFieldError.checkNotNull(
              id, r'WorkRatingResult', 'id'),
          workOrderId: BuiltValueNullFieldError.checkNotNull(
              workOrderId, r'WorkRatingResult', 'workOrderId'),
          score: BuiltValueNullFieldError.checkNotNull(
              score, r'WorkRatingResult', 'score'),
        );
    replace(_$result);
    return _$result;
  }
}

// ignore_for_file: deprecated_member_use_from_same_package,type=lint
