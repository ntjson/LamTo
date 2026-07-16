//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//

// ignore_for_file: unused_element
import 'package:built_value/built_value.dart';
import 'package:built_value/serializer.dart';

part 'work_rating_result.g.dart';

/// WorkRatingResult
///
/// Properties:
/// * [id] 
/// * [workOrderId] 
/// * [score] 
@BuiltValue()
abstract class WorkRatingResult implements Built<WorkRatingResult, WorkRatingResultBuilder> {
  @BuiltValueField(wireName: r'id')
  int get id;

  @BuiltValueField(wireName: r'work_order_id')
  int get workOrderId;

  @BuiltValueField(wireName: r'score')
  int get score;

  WorkRatingResult._();

  factory WorkRatingResult([void updates(WorkRatingResultBuilder b)]) = _$WorkRatingResult;

  @BuiltValueHook(initializeBuilder: true)
  static void _defaults(WorkRatingResultBuilder b) => b;

  @BuiltValueSerializer(custom: true)
  static Serializer<WorkRatingResult> get serializer => _$WorkRatingResultSerializer();
}

class _$WorkRatingResultSerializer implements PrimitiveSerializer<WorkRatingResult> {
  @override
  final Iterable<Type> types = const [WorkRatingResult, _$WorkRatingResult];

  @override
  final String wireName = r'WorkRatingResult';

  Iterable<Object?> _serializeProperties(
    Serializers serializers,
    WorkRatingResult object, {
    FullType specifiedType = FullType.unspecified,
  }) sync* {
    yield r'id';
    yield serializers.serialize(
      object.id,
      specifiedType: const FullType(int),
    );
    yield r'work_order_id';
    yield serializers.serialize(
      object.workOrderId,
      specifiedType: const FullType(int),
    );
    yield r'score';
    yield serializers.serialize(
      object.score,
      specifiedType: const FullType(int),
    );
  }

  @override
  Object serialize(
    Serializers serializers,
    WorkRatingResult object, {
    FullType specifiedType = FullType.unspecified,
  }) {
    return _serializeProperties(serializers, object, specifiedType: specifiedType).toList();
  }

  void _deserializeProperties(
    Serializers serializers,
    Object serialized, {
    FullType specifiedType = FullType.unspecified,
    required List<Object?> serializedList,
    required WorkRatingResultBuilder result,
    required List<Object?> unhandled,
  }) {
    for (var i = 0; i < serializedList.length; i += 2) {
      final key = serializedList[i] as String;
      final value = serializedList[i + 1];
      switch (key) {
        case r'id':
          final valueDes = serializers.deserialize(
            value,
            specifiedType: const FullType(int),
          ) as int;
          result.id = valueDes;
          break;
        case r'work_order_id':
          final valueDes = serializers.deserialize(
            value,
            specifiedType: const FullType(int),
          ) as int;
          result.workOrderId = valueDes;
          break;
        case r'score':
          final valueDes = serializers.deserialize(
            value,
            specifiedType: const FullType(int),
          ) as int;
          result.score = valueDes;
          break;
        default:
          unhandled.add(key);
          unhandled.add(value);
          break;
      }
    }
  }

  @override
  WorkRatingResult deserialize(
    Serializers serializers,
    Object serialized, {
    FullType specifiedType = FullType.unspecified,
  }) {
    final result = WorkRatingResultBuilder();
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

