//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//

// ignore_for_file: unused_element
import 'package:built_collection/built_collection.dart';
import 'package:built_value/json_object.dart';
import 'package:built_value/built_value.dart';
import 'package:built_value/serializer.dart';

part 'proposal.g.dart';

/// Proposal
///
/// Properties:
/// * [id]
/// * [caseId]
/// * [buildingId]
/// * [status]
/// * [completedAt]
/// * [closedAt]
/// * [currentVersion]
@BuiltValue()
abstract class Proposal implements Built<Proposal, ProposalBuilder> {
  @BuiltValueField(wireName: r'id')
  int get id;

  @BuiltValueField(wireName: r'case_id')
  int? get caseId;

  @BuiltValueField(wireName: r'building_id')
  int get buildingId;

  @BuiltValueField(wireName: r'status')
  String get status;

  @BuiltValueField(wireName: r'completed_at')
  DateTime? get completedAt;

  @BuiltValueField(wireName: r'closed_at')
  DateTime? get closedAt;

  @BuiltValueField(wireName: r'current_version')
  BuiltMap<String, JsonObject?>? get currentVersion;

  Proposal._();

  factory Proposal([void updates(ProposalBuilder b)]) = _$Proposal;

  @BuiltValueHook(initializeBuilder: true)
  static void _defaults(ProposalBuilder b) => b;

  @BuiltValueSerializer(custom: true)
  static Serializer<Proposal> get serializer => _$ProposalSerializer();
}

class _$ProposalSerializer implements PrimitiveSerializer<Proposal> {
  @override
  final Iterable<Type> types = const [Proposal, _$Proposal];

  @override
  final String wireName = r'Proposal';

  Iterable<Object?> _serializeProperties(
    Serializers serializers,
    Proposal object, {
    FullType specifiedType = FullType.unspecified,
  }) sync* {
    yield r'id';
    yield serializers.serialize(
      object.id,
      specifiedType: const FullType(int),
    );
    yield r'case_id';
    yield object.caseId == null ? null : serializers.serialize(
      object.caseId,
      specifiedType: const FullType.nullable(int),
    );
    yield r'building_id';
    yield serializers.serialize(
      object.buildingId,
      specifiedType: const FullType(int),
    );
    yield r'status';
    yield serializers.serialize(
      object.status,
      specifiedType: const FullType(String),
    );
    yield r'completed_at';
    yield object.completedAt == null ? null : serializers.serialize(
      object.completedAt,
      specifiedType: const FullType.nullable(DateTime),
    );
    yield r'closed_at';
    yield object.closedAt == null ? null : serializers.serialize(
      object.closedAt,
      specifiedType: const FullType.nullable(DateTime),
    );
    yield r'current_version';
    yield object.currentVersion == null ? null : serializers.serialize(
      object.currentVersion,
      specifiedType: const FullType.nullable(BuiltMap, [FullType(String), FullType.nullable(JsonObject)]),
    );
  }

  @override
  Object serialize(
    Serializers serializers,
    Proposal object, {
    FullType specifiedType = FullType.unspecified,
  }) {
    return _serializeProperties(serializers, object, specifiedType: specifiedType).toList();
  }

  void _deserializeProperties(
    Serializers serializers,
    Object serialized, {
    FullType specifiedType = FullType.unspecified,
    required List<Object?> serializedList,
    required ProposalBuilder result,
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
        case r'case_id':
          final valueDes = serializers.deserialize(
            value,
            specifiedType: const FullType.nullable(int),
          ) as int?;
          if (valueDes == null) continue;
          result.caseId = valueDes;
          break;
        case r'building_id':
          final valueDes = serializers.deserialize(
            value,
            specifiedType: const FullType(int),
          ) as int;
          result.buildingId = valueDes;
          break;
        case r'status':
          final valueDes = serializers.deserialize(
            value,
            specifiedType: const FullType(String),
          ) as String;
          result.status = valueDes;
          break;
        case r'completed_at':
          final valueDes = serializers.deserialize(
            value,
            specifiedType: const FullType.nullable(DateTime),
          ) as DateTime?;
          if (valueDes == null) continue;
          result.completedAt = valueDes;
          break;
        case r'closed_at':
          final valueDes = serializers.deserialize(
            value,
            specifiedType: const FullType.nullable(DateTime),
          ) as DateTime?;
          if (valueDes == null) continue;
          result.closedAt = valueDes;
          break;
        case r'current_version':
          final valueDes = serializers.deserialize(
            value,
            specifiedType: const FullType.nullable(BuiltMap, [FullType(String), FullType.nullable(JsonObject)]),
          ) as BuiltMap<String, JsonObject?>?;
          if (valueDes == null) continue;
          result.currentVersion.replace(valueDes);
          break;
        default:
          unhandled.add(key);
          unhandled.add(value);
          break;
      }
    }
  }

  @override
  Proposal deserialize(
    Serializers serializers,
    Object serialized, {
    FullType specifiedType = FullType.unspecified,
  }) {
    final result = ProposalBuilder();
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
