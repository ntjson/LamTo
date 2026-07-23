//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//

// ignore_for_file: unused_element
import 'package:built_collection/built_collection.dart';
import 'package:built_value/built_value.dart';
import 'package:built_value/serializer.dart';

part 'registration_status_enum.g.dart';

class RegistrationStatusEnum extends EnumClass {

  /// * `PENDING` - Pending * `APPROVED` - Approved * `REJECTED` - Rejected * `EXPIRED` - Expired
  @BuiltValueEnumConst(wireName: r'PENDING')
  static const RegistrationStatusEnum PENDING = _$PENDING;
  /// * `PENDING` - Pending * `APPROVED` - Approved * `REJECTED` - Rejected * `EXPIRED` - Expired
  @BuiltValueEnumConst(wireName: r'APPROVED')
  static const RegistrationStatusEnum APPROVED = _$APPROVED;
  /// * `PENDING` - Pending * `APPROVED` - Approved * `REJECTED` - Rejected * `EXPIRED` - Expired
  @BuiltValueEnumConst(wireName: r'REJECTED')
  static const RegistrationStatusEnum REJECTED = _$REJECTED;
  /// * `PENDING` - Pending * `APPROVED` - Approved * `REJECTED` - Rejected * `EXPIRED` - Expired
  @BuiltValueEnumConst(wireName: r'EXPIRED')
  static const RegistrationStatusEnum EXPIRED = _$EXPIRED;

  static Serializer<RegistrationStatusEnum> get serializer => _$registrationStatusEnumSerializer;

  const RegistrationStatusEnum._(String name): super(name);

  static BuiltSet<RegistrationStatusEnum> get values => _$values;
  static RegistrationStatusEnum valueOf(String name) => _$valueOf(name);
}

/// Optionally, enum_class can generate a mixin to go with your enum for use
/// with Angular. It exposes your enum constants as getters. So, if you mix it
/// in to your Dart component class, the values become available to the
/// corresponding Angular template.
///
/// Trigger mixin generation by writing a line like this one next to your enum.
abstract class RegistrationStatusEnumMixin = Object with _$RegistrationStatusEnumMixin;
