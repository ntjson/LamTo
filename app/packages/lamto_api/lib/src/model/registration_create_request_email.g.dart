// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'registration_create_request_email.dart';

// **************************************************************************
// BuiltValueGenerator
// **************************************************************************

class _$RegistrationCreateRequestEmail extends RegistrationCreateRequestEmail {
  @override
  final OneOf oneOf;

  factory _$RegistrationCreateRequestEmail(
          [void Function(RegistrationCreateRequestEmailBuilder)? updates]) =>
      (RegistrationCreateRequestEmailBuilder()..update(updates))._build();

  _$RegistrationCreateRequestEmail._({required this.oneOf}) : super._();
  @override
  RegistrationCreateRequestEmail rebuild(
          void Function(RegistrationCreateRequestEmailBuilder) updates) =>
      (toBuilder()..update(updates)).build();

  @override
  RegistrationCreateRequestEmailBuilder toBuilder() =>
      RegistrationCreateRequestEmailBuilder()..replace(this);

  @override
  bool operator ==(Object other) {
    if (identical(other, this)) return true;
    return other is RegistrationCreateRequestEmail && oneOf == other.oneOf;
  }

  @override
  int get hashCode {
    var _$hash = 0;
    _$hash = $jc(_$hash, oneOf.hashCode);
    _$hash = $jf(_$hash);
    return _$hash;
  }

  @override
  String toString() {
    return (newBuiltValueToStringHelper(r'RegistrationCreateRequestEmail')
          ..add('oneOf', oneOf))
        .toString();
  }
}

class RegistrationCreateRequestEmailBuilder
    implements
        Builder<RegistrationCreateRequestEmail,
            RegistrationCreateRequestEmailBuilder> {
  _$RegistrationCreateRequestEmail? _$v;

  OneOf? _oneOf;
  OneOf? get oneOf => _$this._oneOf;
  set oneOf(OneOf? oneOf) => _$this._oneOf = oneOf;

  RegistrationCreateRequestEmailBuilder() {
    RegistrationCreateRequestEmail._defaults(this);
  }

  RegistrationCreateRequestEmailBuilder get _$this {
    final $v = _$v;
    if ($v != null) {
      _oneOf = $v.oneOf;
      _$v = null;
    }
    return this;
  }

  @override
  void replace(RegistrationCreateRequestEmail other) {
    _$v = other as _$RegistrationCreateRequestEmail;
  }

  @override
  void update(void Function(RegistrationCreateRequestEmailBuilder)? updates) {
    if (updates != null) updates(this);
  }

  @override
  RegistrationCreateRequestEmail build() => _build();

  _$RegistrationCreateRequestEmail _build() {
    final _$result = _$v ??
        _$RegistrationCreateRequestEmail._(
          oneOf: BuiltValueNullFieldError.checkNotNull(
              oneOf, r'RegistrationCreateRequestEmail', 'oneOf'),
        );
    replace(_$result);
    return _$result;
  }
}

// ignore_for_file: deprecated_member_use_from_same_package,type=lint
