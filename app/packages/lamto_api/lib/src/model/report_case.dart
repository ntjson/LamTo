//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//

// ignore_for_file: unused_element
import 'package:built_collection/built_collection.dart';
import 'package:lamto_api/src/model/report_work_order.dart';
import 'package:built_value/built_value.dart';
import 'package:built_value/serializer.dart';

part 'report_case.g.dart';

/// ReportCase
///
/// Properties:
/// * [id] 
/// * [category] 
/// * [urgency] 
/// * [deadlineAt] 
/// * [active] 
/// * [workOrders] 
@BuiltValue()
abstract class ReportCase implements Built<ReportCase, ReportCaseBuilder> {
  @BuiltValueField(wireName: r'id')
  int get id;

  @BuiltValueField(wireName: r'category')
  String get category;

  @BuiltValueField(wireName: r'urgency')
  String get urgency;

  @BuiltValueField(wireName: r'deadline_at')
  DateTime get deadlineAt;

  @BuiltValueField(wireName: r'active')
  bool get active;

  @BuiltValueField(wireName: r'work_orders')
  BuiltList<ReportWorkOrder> get workOrders;

  ReportCase._();

  factory ReportCase([void updates(ReportCaseBuilder b)]) = _$ReportCase;

  @BuiltValueHook(initializeBuilder: true)
  static void _defaults(ReportCaseBuilder b) => b;

  @BuiltValueSerializer(custom: true)
  static Serializer<ReportCase> get serializer => _$ReportCaseSerializer();
}

class _$ReportCaseSerializer implements PrimitiveSerializer<ReportCase> {
  @override
  final Iterable<Type> types = const [ReportCase, _$ReportCase];

  @override
  final String wireName = r'ReportCase';

  Iterable<Object?> _serializeProperties(
    Serializers serializers,
    ReportCase object, {
    FullType specifiedType = FullType.unspecified,
  }) sync* {
    yield r'id';
    yield serializers.serialize(
      object.id,
      specifiedType: const FullType(int),
    );
    yield r'category';
    yield serializers.serialize(
      object.category,
      specifiedType: const FullType(String),
    );
    yield r'urgency';
    yield serializers.serialize(
      object.urgency,
      specifiedType: const FullType(String),
    );
    yield r'deadline_at';
    yield serializers.serialize(
      object.deadlineAt,
      specifiedType: const FullType(DateTime),
    );
    yield r'active';
    yield serializers.serialize(
      object.active,
      specifiedType: const FullType(bool),
    );
    yield r'work_orders';
    yield serializers.serialize(
      object.workOrders,
      specifiedType: const FullType(BuiltList, [FullType(ReportWorkOrder)]),
    );
  }

  @override
  Object serialize(
    Serializers serializers,
    ReportCase object, {
    FullType specifiedType = FullType.unspecified,
  }) {
    return _serializeProperties(serializers, object, specifiedType: specifiedType).toList();
  }

  void _deserializeProperties(
    Serializers serializers,
    Object serialized, {
    FullType specifiedType = FullType.unspecified,
    required List<Object?> serializedList,
    required ReportCaseBuilder result,
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
        case r'category':
          final valueDes = serializers.deserialize(
            value,
            specifiedType: const FullType(String),
          ) as String;
          result.category = valueDes;
          break;
        case r'urgency':
          final valueDes = serializers.deserialize(
            value,
            specifiedType: const FullType(String),
          ) as String;
          result.urgency = valueDes;
          break;
        case r'deadline_at':
          final valueDes = serializers.deserialize(
            value,
            specifiedType: const FullType(DateTime),
          ) as DateTime;
          result.deadlineAt = valueDes;
          break;
        case r'active':
          final valueDes = serializers.deserialize(
            value,
            specifiedType: const FullType(bool),
          ) as bool;
          result.active = valueDes;
          break;
        case r'work_orders':
          final valueDes = serializers.deserialize(
            value,
            specifiedType: const FullType(BuiltList, [FullType(ReportWorkOrder)]),
          ) as BuiltList<ReportWorkOrder>;
          result.workOrders.replace(valueDes);
          break;
        default:
          unhandled.add(key);
          unhandled.add(value);
          break;
      }
    }
  }

  @override
  ReportCase deserialize(
    Serializers serializers,
    Object serialized, {
    FullType specifiedType = FullType.unspecified,
  }) {
    final result = ReportCaseBuilder();
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

