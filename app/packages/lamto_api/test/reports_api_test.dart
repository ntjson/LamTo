import 'package:test/test.dart';
import 'package:lamto_api/lamto_api.dart';


/// tests for ReportsApi
void main() {
  final instance = LamtoApi().getReportsApi();

  group(ReportsApi, () {
    //Future<ReportSummary> reportsCreate(ReportCreateRequest reportCreateRequest, { int xLamToOccupancy }) async
    test('test reportsCreate', () async {
      // TODO
    });

    //Future<InfoReplyResult> reportsInfoReplyCreate(int id, InfoReplyRequest infoReplyRequest) async
    test('test reportsInfoReplyCreate', () async {
      // TODO
    });

    //Future<PaginatedReportSummaryList> reportsList({ String cursor }) async
    test('test reportsList', () async {
      // TODO
    });

    //Future<ReportPhoto> reportsPhotosCreate(int id, MultipartFile photo) async
    test('test reportsPhotosCreate', () async {
      // TODO
    });

    //Future<ReportDetail> reportsRetrieve(int id) async
    test('test reportsRetrieve', () async {
      // TODO
    });

  });
}
