//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//

// ignore_for_file: unused_element
import 'dart:core';
import 'package:built_value/built_value.dart';
import 'package:built_value/serializer.dart';
import 'package:one_of/one_of.dart';

part 'registration_create_request_email.g.dart';

/// RegistrationCreateRequestEmail
@BuiltValue()
abstract class RegistrationCreateRequestEmail implements Built<RegistrationCreateRequestEmail, RegistrationCreateRequestEmailBuilder> {
  /// One Of [String]
  OneOf get oneOf;

  RegistrationCreateRequestEmail._();

  factory RegistrationCreateRequestEmail([void updates(RegistrationCreateRequestEmailBuilder b)]) = _$RegistrationCreateRequestEmail;

  @BuiltValueHook(initializeBuilder: true)
  static void _defaults(RegistrationCreateRequestEmailBuilder b) => b;

  @BuiltValueSerializer(custom: true)
  static Serializer<RegistrationCreateRequestEmail> get serializer => _$RegistrationCreateRequestEmailSerializer();
}

class _$RegistrationCreateRequestEmailSerializer implements PrimitiveSerializer<RegistrationCreateRequestEmail> {
  @override
  final Iterable<Type> types = const [RegistrationCreateRequestEmail, _$RegistrationCreateRequestEmail];

  @override
  final String wireName = r'RegistrationCreateRequestEmail';

  Iterable<Object?> _serializeProperties(
    Serializers serializers,
    RegistrationCreateRequestEmail object, {
    FullType specifiedType = FullType.unspecified,
  }) sync* {
  }

  @override
  Object serialize(
    Serializers serializers,
    RegistrationCreateRequestEmail object, {
    FullType specifiedType = FullType.unspecified,
  }) {
    final oneOf = object.oneOf;
    return serializers.serialize(oneOf.value, specifiedType: FullType(oneOf.valueType))!;
  }

  @override
  RegistrationCreateRequestEmail deserialize(
    Serializers serializers,
    Object serialized, {
    FullType specifiedType = FullType.unspecified,
  }) {
    final result = RegistrationCreateRequestEmailBuilder();
    Object? oneOfDataSrc;
    final targetType = const FullType(OneOf, [FullType(String), FullType(String), ]);
    oneOfDataSrc = serialized;
    result.oneOf = serializers.deserialize(oneOfDataSrc, specifiedType: targetType) as OneOf;
    return result.build();
  }
}
