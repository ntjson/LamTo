// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'work_rating_request.dart';

// **************************************************************************
// BuiltValueGenerator
// **************************************************************************

class _$WorkRatingRequest extends WorkRatingRequest {
  @override
  final int score;
  @override
  final String? comment;

  factory _$WorkRatingRequest(
          [void Function(WorkRatingRequestBuilder)? updates]) =>
      (WorkRatingRequestBuilder()..update(updates))._build();

  _$WorkRatingRequest._({required this.score, this.comment}) : super._();
  @override
  WorkRatingRequest rebuild(void Function(WorkRatingRequestBuilder) updates) =>
      (toBuilder()..update(updates)).build();

  @override
  WorkRatingRequestBuilder toBuilder() =>
      WorkRatingRequestBuilder()..replace(this);

  @override
  bool operator ==(Object other) {
    if (identical(other, this)) return true;
    return other is WorkRatingRequest &&
        score == other.score &&
        comment == other.comment;
  }

  @override
  int get hashCode {
    var _$hash = 0;
    _$hash = $jc(_$hash, score.hashCode);
    _$hash = $jc(_$hash, comment.hashCode);
    _$hash = $jf(_$hash);
    return _$hash;
  }

  @override
  String toString() {
    return (newBuiltValueToStringHelper(r'WorkRatingRequest')
          ..add('score', score)
          ..add('comment', comment))
        .toString();
  }
}

class WorkRatingRequestBuilder
    implements Builder<WorkRatingRequest, WorkRatingRequestBuilder> {
  _$WorkRatingRequest? _$v;

  int? _score;
  int? get score => _$this._score;
  set score(int? score) => _$this._score = score;

  String? _comment;
  String? get comment => _$this._comment;
  set comment(String? comment) => _$this._comment = comment;

  WorkRatingRequestBuilder() {
    WorkRatingRequest._defaults(this);
  }

  WorkRatingRequestBuilder get _$this {
    final $v = _$v;
    if ($v != null) {
      _score = $v.score;
      _comment = $v.comment;
      _$v = null;
    }
    return this;
  }

  @override
  void replace(WorkRatingRequest other) {
    _$v = other as _$WorkRatingRequest;
  }

  @override
  void update(void Function(WorkRatingRequestBuilder)? updates) {
    if (updates != null) updates(this);
  }

  @override
  WorkRatingRequest build() => _build();

  _$WorkRatingRequest _build() {
    final _$result = _$v ??
        _$WorkRatingRequest._(
          score: BuiltValueNullFieldError.checkNotNull(
              score, r'WorkRatingRequest', 'score'),
          comment: comment,
        );
    replace(_$result);
    return _$result;
  }
}

// ignore_for_file: deprecated_member_use_from_same_package,type=lint
