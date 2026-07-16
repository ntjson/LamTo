//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//

// ignore_for_file: unused_element
import 'package:built_value/built_value.dart';
import 'package:built_value/serializer.dart';

part 'work_rating_request.g.dart';

/// WorkRatingRequest
///
/// Properties:
/// * [score] 
/// * [comment] 
@BuiltValue()
abstract class WorkRatingRequest implements Built<WorkRatingRequest, WorkRatingRequestBuilder> {
  @BuiltValueField(wireName: r'score')
  int get score;

  @BuiltValueField(wireName: r'comment')
  String? get comment;

  WorkRatingRequest._();

  factory WorkRatingRequest([void updates(WorkRatingRequestBuilder b)]) = _$WorkRatingRequest;

  @BuiltValueHook(initializeBuilder: true)
  static void _defaults(WorkRatingRequestBuilder b) => b;

  @BuiltValueSerializer(custom: true)
  static Serializer<WorkRatingRequest> get serializer => _$WorkRatingRequestSerializer();
}

class _$WorkRatingRequestSerializer implements PrimitiveSerializer<WorkRatingRequest> {
  @override
  final Iterable<Type> types = const [WorkRatingRequest, _$WorkRatingRequest];

  @override
  final String wireName = r'WorkRatingRequest';

  Iterable<Object?> _serializeProperties(
    Serializers serializers,
    WorkRatingRequest object, {
    FullType specifiedType = FullType.unspecified,
  }) sync* {
    yield r'score';
    yield serializers.serialize(
      object.score,
      specifiedType: const FullType(int),
    );
    if (object.comment != null) {
      yield r'comment';
      yield serializers.serialize(
        object.comment,
        specifiedType: const FullType(String),
      );
    }
  }

  @override
  Object serialize(
    Serializers serializers,
    WorkRatingRequest object, {
    FullType specifiedType = FullType.unspecified,
  }) {
    return _serializeProperties(serializers, object, specifiedType: specifiedType).toList();
  }

  void _deserializeProperties(
    Serializers serializers,
    Object serialized, {
    FullType specifiedType = FullType.unspecified,
    required List<Object?> serializedList,
    required WorkRatingRequestBuilder result,
    required List<Object?> unhandled,
  }) {
    for (var i = 0; i < serializedList.length; i += 2) {
      final key = serializedList[i] as String;
      final value = serializedList[i + 1];
      switch (key) {
        case r'score':
          final valueDes = serializers.deserialize(
            value,
            specifiedType: const FullType(int),
          ) as int;
          result.score = valueDes;
          break;
        case r'comment':
          final valueDes = serializers.deserialize(
            value,
            specifiedType: const FullType(String),
          ) as String;
          result.comment = valueDes;
          break;
        default:
          unhandled.add(key);
          unhandled.add(value);
          break;
      }
    }
  }

  @override
  WorkRatingRequest deserialize(
    Serializers serializers,
    Object serialized, {
    FullType specifiedType = FullType.unspecified,
  }) {
    final result = WorkRatingRequestBuilder();
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

