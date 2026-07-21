// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'proposal.dart';

// **************************************************************************
// BuiltValueGenerator
// **************************************************************************

class _$Proposal extends Proposal {
  @override
  final int id;
  @override
  final int? caseId;
  @override
  final int buildingId;
  @override
  final String status;
  @override
  final DateTime? completedAt;
  @override
  final DateTime? closedAt;
  @override
  final BuiltMap<String, JsonObject?>? currentVersion;

  factory _$Proposal([void Function(ProposalBuilder)? updates]) =>
      (ProposalBuilder()..update(updates))._build();

  _$Proposal._(
      {required this.id,
      this.caseId,
      required this.buildingId,
      required this.status,
      this.completedAt,
      this.closedAt,
      this.currentVersion})
      : super._();
  @override
  Proposal rebuild(void Function(ProposalBuilder) updates) =>
      (toBuilder()..update(updates)).build();

  @override
  ProposalBuilder toBuilder() => ProposalBuilder()..replace(this);

  @override
  bool operator ==(Object other) {
    if (identical(other, this)) return true;
    return other is Proposal &&
        id == other.id &&
        caseId == other.caseId &&
        buildingId == other.buildingId &&
        status == other.status &&
        completedAt == other.completedAt &&
        closedAt == other.closedAt &&
        currentVersion == other.currentVersion;
  }

  @override
  int get hashCode {
    var _$hash = 0;
    _$hash = $jc(_$hash, id.hashCode);
    _$hash = $jc(_$hash, caseId.hashCode);
    _$hash = $jc(_$hash, buildingId.hashCode);
    _$hash = $jc(_$hash, status.hashCode);
    _$hash = $jc(_$hash, completedAt.hashCode);
    _$hash = $jc(_$hash, closedAt.hashCode);
    _$hash = $jc(_$hash, currentVersion.hashCode);
    _$hash = $jf(_$hash);
    return _$hash;
  }

  @override
  String toString() {
    return (newBuiltValueToStringHelper(r'Proposal')
          ..add('id', id)
          ..add('caseId', caseId)
          ..add('buildingId', buildingId)
          ..add('status', status)
          ..add('completedAt', completedAt)
          ..add('closedAt', closedAt)
          ..add('currentVersion', currentVersion))
        .toString();
  }
}

class ProposalBuilder implements Builder<Proposal, ProposalBuilder> {
  _$Proposal? _$v;

  int? _id;
  int? get id => _$this._id;
  set id(int? id) => _$this._id = id;

  int? _caseId;
  int? get caseId => _$this._caseId;
  set caseId(int? caseId) => _$this._caseId = caseId;

  int? _buildingId;
  int? get buildingId => _$this._buildingId;
  set buildingId(int? buildingId) => _$this._buildingId = buildingId;

  String? _status;
  String? get status => _$this._status;
  set status(String? status) => _$this._status = status;

  DateTime? _completedAt;
  DateTime? get completedAt => _$this._completedAt;
  set completedAt(DateTime? completedAt) => _$this._completedAt = completedAt;

  DateTime? _closedAt;
  DateTime? get closedAt => _$this._closedAt;
  set closedAt(DateTime? closedAt) => _$this._closedAt = closedAt;

  MapBuilder<String, JsonObject?>? _currentVersion;
  MapBuilder<String, JsonObject?> get currentVersion =>
      _$this._currentVersion ??= MapBuilder<String, JsonObject?>();
  set currentVersion(MapBuilder<String, JsonObject?>? currentVersion) =>
      _$this._currentVersion = currentVersion;

  ProposalBuilder() {
    Proposal._defaults(this);
  }

  ProposalBuilder get _$this {
    final $v = _$v;
    if ($v != null) {
      _id = $v.id;
      _caseId = $v.caseId;
      _buildingId = $v.buildingId;
      _status = $v.status;
      _completedAt = $v.completedAt;
      _closedAt = $v.closedAt;
      _currentVersion = $v.currentVersion?.toBuilder();
      _$v = null;
    }
    return this;
  }

  @override
  void replace(Proposal other) {
    _$v = other as _$Proposal;
  }

  @override
  void update(void Function(ProposalBuilder)? updates) {
    if (updates != null) updates(this);
  }

  @override
  Proposal build() => _build();

  _$Proposal _build() {
    _$Proposal _$result;
    try {
      _$result = _$v ??
          _$Proposal._(
            id: BuiltValueNullFieldError.checkNotNull(id, r'Proposal', 'id'),
            caseId: caseId,
            buildingId: BuiltValueNullFieldError.checkNotNull(
                buildingId, r'Proposal', 'buildingId'),
            status: BuiltValueNullFieldError.checkNotNull(
                status, r'Proposal', 'status'),
            completedAt: completedAt,
            closedAt: closedAt,
            currentVersion: _currentVersion?.build(),
          );
    } catch (_) {
      late String _$failedField;
      try {
        _$failedField = 'currentVersion';
        _currentVersion?.build();
      } catch (e) {
        throw BuiltValueNestedFieldError(
            r'Proposal', _$failedField, e.toString());
      }
      rethrow;
    }
    replace(_$result);
    return _$result;
  }
}

// ignore_for_file: deprecated_member_use_from_same_package,type=lint
