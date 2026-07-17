//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//

// ignore_for_file: unused_element
import 'package:built_value/built_value.dart';
import 'package:built_value/serializer.dart';

part 'ledger_approver.g.dart';

/// Who authorized the spend (board / resident rep / emergency).
///
/// Properties:
/// * [role] - Machine role: board, resident_rep, or emergency.
/// * [name] - Display name of the approver.
/// * [decision] - Decision code (e.g. APPROVE).
@BuiltValue()
abstract class LedgerApprover implements Built<LedgerApprover, LedgerApproverBuilder> {
  /// Machine role: board, resident_rep, or emergency.
  @BuiltValueField(wireName: r'role')
  String get role;

  /// Display name of the approver.
  @BuiltValueField(wireName: r'name')
  String get name;

  /// Decision code (e.g. APPROVE).
  @BuiltValueField(wireName: r'decision')
  String get decision;

  LedgerApprover._();

  factory LedgerApprover([void updates(LedgerApproverBuilder b)]) = _$LedgerApprover;

  @BuiltValueHook(initializeBuilder: true)
  static void _defaults(LedgerApproverBuilder b) => b;

  @BuiltValueSerializer(custom: true)
  static Serializer<LedgerApprover> get serializer => _$LedgerApproverSerializer();
}

class _$LedgerApproverSerializer implements PrimitiveSerializer<LedgerApprover> {
  @override
  final Iterable<Type> types = const [LedgerApprover, _$LedgerApprover];

  @override
  final String wireName = r'LedgerApprover';

  Iterable<Object?> _serializeProperties(
    Serializers serializers,
    LedgerApprover object, {
    FullType specifiedType = FullType.unspecified,
  }) sync* {
    yield r'role';
    yield serializers.serialize(
      object.role,
      specifiedType: const FullType(String),
    );
    yield r'name';
    yield serializers.serialize(
      object.name,
      specifiedType: const FullType(String),
    );
    yield r'decision';
    yield serializers.serialize(
      object.decision,
      specifiedType: const FullType(String),
    );
  }

  @override
  Object serialize(
    Serializers serializers,
    LedgerApprover object, {
    FullType specifiedType = FullType.unspecified,
  }) {
    return _serializeProperties(serializers, object, specifiedType: specifiedType).toList();
  }

  void _deserializeProperties(
    Serializers serializers,
    Object serialized, {
    FullType specifiedType = FullType.unspecified,
    required List<Object?> serializedList,
    required LedgerApproverBuilder result,
    required List<Object?> unhandled,
  }) {
    for (var i = 0; i < serializedList.length; i += 2) {
      final key = serializedList[i] as String;
      final value = serializedList[i + 1];
      switch (key) {
        case r'role':
          final valueDes = serializers.deserialize(
            value,
            specifiedType: const FullType(String),
          ) as String;
          result.role = valueDes;
          break;
        case r'name':
          final valueDes = serializers.deserialize(
            value,
            specifiedType: const FullType(String),
          ) as String;
          result.name = valueDes;
          break;
        case r'decision':
          final valueDes = serializers.deserialize(
            value,
            specifiedType: const FullType(String),
          ) as String;
          result.decision = valueDes;
          break;
        default:
          unhandled.add(key);
          unhandled.add(value);
          break;
      }
    }
  }

  @override
  LedgerApprover deserialize(
    Serializers serializers,
    Object serialized, {
    FullType specifiedType = FullType.unspecified,
  }) {
    final result = LedgerApproverBuilder();
    final serializedList = (serialized as Iterable<Object?>).toList();
    final unhandled = <Object?>[];
    _deserializeProperties(
      serializers,
      serialized,
      specifiedType: specifiedType,
      serializedList: serializedList,
      unhandled: unhandled,
      result: result,
    );
    return result.build();
  }
}

