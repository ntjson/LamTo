//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//

// ignore_for_file: unused_element
import 'package:built_value/built_value.dart';
import 'package:built_value/serializer.dart';

part 'proceed_decision.g.dart';

/// ProceedDecision
///
/// Properties:
/// * [decidedBy] - Display name of the decider.
/// * [decidedAt]
@BuiltValue()
abstract class ProceedDecision implements Built<ProceedDecision, ProceedDecisionBuilder> {
  /// Display name of the decider.
  @BuiltValueField(wireName: r'decided_by')
  String get decidedBy;

  @BuiltValueField(wireName: r'decided_at')
  DateTime get decidedAt;

  ProceedDecision._();

  factory ProceedDecision([void updates(ProceedDecisionBuilder b)]) = _$ProceedDecision;

  @BuiltValueHook(initializeBuilder: true)
  static void _defaults(ProceedDecisionBuilder b) => b;

  @BuiltValueSerializer(custom: true)
  static Serializer<ProceedDecision> get serializer => _$ProceedDecisionSerializer();
}

class _$ProceedDecisionSerializer implements PrimitiveSerializer<ProceedDecision> {
  @override
  final Iterable<Type> types = const [ProceedDecision, _$ProceedDecision];

  @override
  final String wireName = r'ProceedDecision';

  Iterable<Object?> _serializeProperties(
    Serializers serializers,
    ProceedDecision object, {
    FullType specifiedType = FullType.unspecified,
  }) sync* {
    yield r'decided_by';
    yield serializers.serialize(
      object.decidedBy,
      specifiedType: const FullType(String),
    );
    yield r'decided_at';
    yield serializers.serialize(
      object.decidedAt,
      specifiedType: const FullType(DateTime),
    );
  }

  @override
  Object serialize(
    Serializers serializers,
    ProceedDecision object, {
    FullType specifiedType = FullType.unspecified,
  }) {
    return _serializeProperties(serializers, object, specifiedType: specifiedType).toList();
  }

  void _deserializeProperties(
    Serializers serializers,
    Object serialized, {
    FullType specifiedType = FullType.unspecified,
    required List<Object?> serializedList,
    required ProceedDecisionBuilder result,
    required List<Object?> unhandled,
  }) {
    for (var i = 0; i < serializedList.length; i += 2) {
      final key = serializedList[i] as String;
      final value = serializedList[i + 1];
      switch (key) {
        case r'decided_by':
          final valueDes = serializers.deserialize(
            value,
            specifiedType: const FullType(String),
          ) as String;
          result.decidedBy = valueDes;
          break;
        case r'decided_at':
          final valueDes = serializers.deserialize(
            value,
            specifiedType: const FullType(DateTime),
          ) as DateTime;
          result.decidedAt = valueDes;
          break;
        default:
          unhandled.add(key);
          unhandled.add(value);
          break;
      }
    }
  }

  @override
  ProceedDecision deserialize(
    Serializers serializers,
    Object serialized, {
    FullType specifiedType = FullType.unspecified,
  }) {
    final result = ProceedDecisionBuilder();
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
