//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//

// ignore_for_file: unused_element
import 'package:built_collection/built_collection.dart';
import 'package:built_value/built_value.dart';
import 'package:built_value/serializer.dart';

part 'status_enum.g.dart';

class StatusEnum extends EnumClass {

  /// * `SUBMITTED` - Submitted * `IN_REVIEW` - In review * `NEEDS_INFO` - Needs information * `DECLINED` - Declined * `IN_PROGRESS` - In progress * `PROPOSED` - Proposed * `COMPLETED` - Completed * `CLOSED` - Closed
  @BuiltValueEnumConst(wireName: r'SUBMITTED')
  static const StatusEnum SUBMITTED = _$SUBMITTED;
  /// * `SUBMITTED` - Submitted * `IN_REVIEW` - In review * `NEEDS_INFO` - Needs information * `DECLINED` - Declined * `IN_PROGRESS` - In progress * `PROPOSED` - Proposed * `COMPLETED` - Completed * `CLOSED` - Closed
  @BuiltValueEnumConst(wireName: r'IN_REVIEW')
  static const StatusEnum IN_REVIEW = _$IN_REVIEW;
  /// * `SUBMITTED` - Submitted * `IN_REVIEW` - In review * `NEEDS_INFO` - Needs information * `DECLINED` - Declined * `IN_PROGRESS` - In progress * `PROPOSED` - Proposed * `COMPLETED` - Completed * `CLOSED` - Closed
  @BuiltValueEnumConst(wireName: r'NEEDS_INFO')
  static const StatusEnum NEEDS_INFO = _$NEEDS_INFO;
  /// * `SUBMITTED` - Submitted * `IN_REVIEW` - In review * `NEEDS_INFO` - Needs information * `DECLINED` - Declined * `IN_PROGRESS` - In progress * `PROPOSED` - Proposed * `COMPLETED` - Completed * `CLOSED` - Closed
  @BuiltValueEnumConst(wireName: r'DECLINED')
  static const StatusEnum DECLINED = _$DECLINED;
  /// * `SUBMITTED` - Submitted * `IN_REVIEW` - In review * `NEEDS_INFO` - Needs information * `DECLINED` - Declined * `IN_PROGRESS` - In progress * `PROPOSED` - Proposed * `COMPLETED` - Completed * `CLOSED` - Closed
  @BuiltValueEnumConst(wireName: r'IN_PROGRESS')
  static const StatusEnum IN_PROGRESS = _$IN_PROGRESS;
  /// * `SUBMITTED` - Submitted * `IN_REVIEW` - In review * `NEEDS_INFO` - Needs information * `DECLINED` - Declined * `IN_PROGRESS` - In progress * `PROPOSED` - Proposed * `COMPLETED` - Completed * `CLOSED` - Closed
  @BuiltValueEnumConst(wireName: r'PROPOSED')
  static const StatusEnum PROPOSED = _$PROPOSED;
  /// * `SUBMITTED` - Submitted * `IN_REVIEW` - In review * `NEEDS_INFO` - Needs information * `DECLINED` - Declined * `IN_PROGRESS` - In progress * `PROPOSED` - Proposed * `COMPLETED` - Completed * `CLOSED` - Closed
  @BuiltValueEnumConst(wireName: r'COMPLETED')
  static const StatusEnum COMPLETED = _$COMPLETED;
  /// * `SUBMITTED` - Submitted * `IN_REVIEW` - In review * `NEEDS_INFO` - Needs information * `DECLINED` - Declined * `IN_PROGRESS` - In progress * `PROPOSED` - Proposed * `COMPLETED` - Completed * `CLOSED` - Closed
  @BuiltValueEnumConst(wireName: r'CLOSED')
  static const StatusEnum CLOSED = _$CLOSED;

  static Serializer<StatusEnum> get serializer => _$statusEnumSerializer;

  const StatusEnum._(String name): super(name);

  static BuiltSet<StatusEnum> get values => _$values;
  static StatusEnum valueOf(String name) => _$valueOf(name);
}

/// Optionally, enum_class can generate a mixin to go with your enum for use
/// with Angular. It exposes your enum constants as getters. So, if you mix it
/// in to your Dart component class, the values become available to the
/// corresponding Angular template.
///
/// Trigger mixin generation by writing a line like this one next to your enum.
abstract class StatusEnumMixin = Object with _$StatusEnumMixin;
