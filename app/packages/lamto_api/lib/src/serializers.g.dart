// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'serializers.dart';

// **************************************************************************
// BuiltValueGenerator
// **************************************************************************

Serializers _$serializers = (Serializers().toBuilder()
      ..add(Correction.serializer)
      ..add(Device.serializer)
      ..add(DeviceRegisterRequest.serializer)
      ..add(FundSeries.serializer)
      ..add(FundSeriesPoint.serializer)
      ..add(FundSummary.serializer)
      ..add(LedgerApprover.serializer)
      ..add(LedgerEntryDetail.serializer)
      ..add(LedgerEntryList.serializer)
      ..add(Location.serializer)
      ..add(LoginRequest.serializer)
      ..add(LogoutInstallIdRequest.serializer)
      ..add(Me.serializer)
      ..add(NotificationFeed.serializer)
      ..add(NotificationPreference.serializer)
      ..add(NotificationPreferenceUpdateItemRequest.serializer)
      ..add(Occupancy.serializer)
      ..add(PaginatedLedgerEntryListList.serializer)
      ..add(PaginatedNotificationFeedList.serializer)
      ..add(PaginatedReportSummaryList.serializer)
      ..add(PatchedNotificationPreferenceUpdateRequest.serializer)
      ..add(PlatformEnum.serializer)
      ..add(Problem.serializer)
      ..add(Proof.serializer)
      ..add(ProofEvent.serializer)
      ..add(RedactedDocument.serializer)
      ..add(ReportCase.serializer)
      ..add(ReportCreateRequest.serializer)
      ..add(ReportDetail.serializer)
      ..add(ReportPhoto.serializer)
      ..add(ReportSummary.serializer)
      ..add(ReportWorkOrder.serializer)
      ..add(TokenResponse.serializer)
      ..add(Verification.serializer)
      ..add(WorkRatingRequest.serializer)
      ..add(WorkRatingResult.serializer)
      ..addBuilderFactory(
          const FullType(BuiltList, const [const FullType(FundSeriesPoint)]),
          () => ListBuilder<FundSeriesPoint>())
      ..addBuilderFactory(
          const FullType(BuiltList, const [const FullType(LedgerApprover)]),
          () => ListBuilder<LedgerApprover>())
      ..addBuilderFactory(
          const FullType(BuiltList, const [const FullType(RedactedDocument)]),
          () => ListBuilder<RedactedDocument>())
      ..addBuilderFactory(
          const FullType(BuiltList, const [const FullType(Correction)]),
          () => ListBuilder<Correction>())
      ..addBuilderFactory(
          const FullType(BuiltList, const [const FullType(LedgerEntryList)]),
          () => ListBuilder<LedgerEntryList>())
      ..addBuilderFactory(
          const FullType(BuiltList, const [const FullType(NotificationFeed)]),
          () => ListBuilder<NotificationFeed>())
      ..addBuilderFactory(
          const FullType(BuiltList,
              const [const FullType(NotificationPreferenceUpdateItemRequest)]),
          () => ListBuilder<NotificationPreferenceUpdateItemRequest>())
      ..addBuilderFactory(
          const FullType(BuiltList, const [const FullType(Occupancy)]),
          () => ListBuilder<Occupancy>())
      ..addBuilderFactory(
          const FullType(
              BuiltList, const [const FullType(NotificationPreference)]),
          () => ListBuilder<NotificationPreference>())
      ..addBuilderFactory(
          const FullType(BuiltList, const [const FullType(ProofEvent)]),
          () => ListBuilder<ProofEvent>())
      ..addBuilderFactory(
          const FullType(BuiltList, const [const FullType(ReportPhoto)]),
          () => ListBuilder<ReportPhoto>())
      ..addBuilderFactory(
          const FullType(BuiltList, const [const FullType(ReportCase)]),
          () => ListBuilder<ReportCase>())
      ..addBuilderFactory(
          const FullType(BuiltList, const [const FullType(ReportSummary)]),
          () => ListBuilder<ReportSummary>())
      ..addBuilderFactory(
          const FullType(BuiltList, const [const FullType(ReportWorkOrder)]),
          () => ListBuilder<ReportWorkOrder>())
      ..addBuilderFactory(
          const FullType(BuiltMap, const [
            const FullType(String),
            const FullType.nullable(JsonObject)
          ]),
          () => MapBuilder<String, JsonObject?>()))
    .build();

// ignore_for_file: deprecated_member_use_from_same_package,type=lint
