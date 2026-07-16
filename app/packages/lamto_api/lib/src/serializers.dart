//
// AUTO-GENERATED FILE, DO NOT MODIFY!
//

// ignore_for_file: unused_import

import 'package:one_of_serializer/any_of_serializer.dart';
import 'package:one_of_serializer/one_of_serializer.dart';
import 'package:built_collection/built_collection.dart';
import 'package:built_value/json_object.dart';
import 'package:built_value/serializer.dart';
import 'package:built_value/standard_json_plugin.dart';
import 'package:built_value/iso_8601_date_time_serializer.dart';
import 'package:lamto_api/src/date_serializer.dart';
import 'package:lamto_api/src/model/date.dart';

import 'package:lamto_api/src/model/correction.dart';
import 'package:lamto_api/src/model/device.dart';
import 'package:lamto_api/src/model/device_register_request.dart';
import 'package:lamto_api/src/model/fund_summary.dart';
import 'package:lamto_api/src/model/ledger_entry_detail.dart';
import 'package:lamto_api/src/model/ledger_entry_list.dart';
import 'package:lamto_api/src/model/location.dart';
import 'package:lamto_api/src/model/login_request.dart';
import 'package:lamto_api/src/model/logout_install_id_request.dart';
import 'package:lamto_api/src/model/me.dart';
import 'package:lamto_api/src/model/notification_feed.dart';
import 'package:lamto_api/src/model/notification_preference.dart';
import 'package:lamto_api/src/model/notification_preference_update_item_request.dart';
import 'package:lamto_api/src/model/occupancy.dart';
import 'package:lamto_api/src/model/paginated_ledger_entry_list_list.dart';
import 'package:lamto_api/src/model/paginated_notification_feed_list.dart';
import 'package:lamto_api/src/model/paginated_report_summary_list.dart';
import 'package:lamto_api/src/model/patched_notification_preference_update_request.dart';
import 'package:lamto_api/src/model/platform_enum.dart';
import 'package:lamto_api/src/model/problem.dart';
import 'package:lamto_api/src/model/proof.dart';
import 'package:lamto_api/src/model/proof_event.dart';
import 'package:lamto_api/src/model/redacted_document.dart';
import 'package:lamto_api/src/model/report_case.dart';
import 'package:lamto_api/src/model/report_create_request.dart';
import 'package:lamto_api/src/model/report_detail.dart';
import 'package:lamto_api/src/model/report_photo.dart';
import 'package:lamto_api/src/model/report_summary.dart';
import 'package:lamto_api/src/model/report_work_order.dart';
import 'package:lamto_api/src/model/token_response.dart';
import 'package:lamto_api/src/model/verification.dart';
import 'package:lamto_api/src/model/work_rating_request.dart';
import 'package:lamto_api/src/model/work_rating_result.dart';

part 'serializers.g.dart';

@SerializersFor([
  Correction,
  Device,
  DeviceRegisterRequest,
  FundSummary,
  LedgerEntryDetail,
  LedgerEntryList,
  Location,
  LoginRequest,
  LogoutInstallIdRequest,
  Me,
  NotificationFeed,
  NotificationPreference,
  NotificationPreferenceUpdateItemRequest,
  Occupancy,
  PaginatedLedgerEntryListList,
  PaginatedNotificationFeedList,
  PaginatedReportSummaryList,
  PatchedNotificationPreferenceUpdateRequest,
  PlatformEnum,
  Problem,
  Proof,
  ProofEvent,
  RedactedDocument,
  ReportCase,
  ReportCreateRequest,
  ReportDetail,
  ReportPhoto,
  ReportSummary,
  ReportWorkOrder,
  TokenResponse,
  Verification,
  WorkRatingRequest,
  WorkRatingResult,
])
Serializers serializers = (_$serializers.toBuilder()
      ..addBuilderFactory(
        const FullType(BuiltList, [FullType(Location)]),
        () => ListBuilder<Location>(),
      )
      ..addBuilderFactory(
        const FullType(BuiltList, [FullType(NotificationPreference)]),
        () => ListBuilder<NotificationPreference>(),
      )
      ..add(const OneOfSerializer())
      ..add(const AnyOfSerializer())
      ..add(const DateSerializer())
      ..add(Iso8601DateTimeSerializer())
    ).build();

Serializers standardSerializers =
    (serializers.toBuilder()..addPlugin(StandardJsonPlugin())).build();
