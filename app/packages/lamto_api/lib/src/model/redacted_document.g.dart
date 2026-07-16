// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'redacted_document.dart';

// **************************************************************************
// BuiltValueGenerator
// **************************************************************************

class _$RedactedDocument extends RedactedDocument {
  @override
  final String label;
  @override
  final String filename;
  @override
  final String sha256;
  @override
  final String downloadUrl;

  factory _$RedactedDocument(
          [void Function(RedactedDocumentBuilder)? updates]) =>
      (RedactedDocumentBuilder()..update(updates))._build();

  _$RedactedDocument._(
      {required this.label,
      required this.filename,
      required this.sha256,
      required this.downloadUrl})
      : super._();
  @override
  RedactedDocument rebuild(void Function(RedactedDocumentBuilder) updates) =>
      (toBuilder()..update(updates)).build();

  @override
  RedactedDocumentBuilder toBuilder() =>
      RedactedDocumentBuilder()..replace(this);

  @override
  bool operator ==(Object other) {
    if (identical(other, this)) return true;
    return other is RedactedDocument &&
        label == other.label &&
        filename == other.filename &&
        sha256 == other.sha256 &&
        downloadUrl == other.downloadUrl;
  }

  @override
  int get hashCode {
    var _$hash = 0;
    _$hash = $jc(_$hash, label.hashCode);
    _$hash = $jc(_$hash, filename.hashCode);
    _$hash = $jc(_$hash, sha256.hashCode);
    _$hash = $jc(_$hash, downloadUrl.hashCode);
    _$hash = $jf(_$hash);
    return _$hash;
  }

  @override
  String toString() {
    return (newBuiltValueToStringHelper(r'RedactedDocument')
          ..add('label', label)
          ..add('filename', filename)
          ..add('sha256', sha256)
          ..add('downloadUrl', downloadUrl))
        .toString();
  }
}

class RedactedDocumentBuilder
    implements Builder<RedactedDocument, RedactedDocumentBuilder> {
  _$RedactedDocument? _$v;

  String? _label;
  String? get label => _$this._label;
  set label(String? label) => _$this._label = label;

  String? _filename;
  String? get filename => _$this._filename;
  set filename(String? filename) => _$this._filename = filename;

  String? _sha256;
  String? get sha256 => _$this._sha256;
  set sha256(String? sha256) => _$this._sha256 = sha256;

  String? _downloadUrl;
  String? get downloadUrl => _$this._downloadUrl;
  set downloadUrl(String? downloadUrl) => _$this._downloadUrl = downloadUrl;

  RedactedDocumentBuilder() {
    RedactedDocument._defaults(this);
  }

  RedactedDocumentBuilder get _$this {
    final $v = _$v;
    if ($v != null) {
      _label = $v.label;
      _filename = $v.filename;
      _sha256 = $v.sha256;
      _downloadUrl = $v.downloadUrl;
      _$v = null;
    }
    return this;
  }

  @override
  void replace(RedactedDocument other) {
    _$v = other as _$RedactedDocument;
  }

  @override
  void update(void Function(RedactedDocumentBuilder)? updates) {
    if (updates != null) updates(this);
  }

  @override
  RedactedDocument build() => _build();

  _$RedactedDocument _build() {
    final _$result = _$v ??
        _$RedactedDocument._(
          label: BuiltValueNullFieldError.checkNotNull(
              label, r'RedactedDocument', 'label'),
          filename: BuiltValueNullFieldError.checkNotNull(
              filename, r'RedactedDocument', 'filename'),
          sha256: BuiltValueNullFieldError.checkNotNull(
              sha256, r'RedactedDocument', 'sha256'),
          downloadUrl: BuiltValueNullFieldError.checkNotNull(
              downloadUrl, r'RedactedDocument', 'downloadUrl'),
        );
    replace(_$result);
    return _$result;
  }
}

// ignore_for_file: deprecated_member_use_from_same_package,type=lint
