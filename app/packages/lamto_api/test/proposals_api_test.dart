import 'package:test/test.dart';
import 'package:lamto_api/lamto_api.dart';


/// tests for ProposalsApi
void main() {
  final instance = LamtoApi().getProposalsApi();

  group(ProposalsApi, () {
    //Future<Proposal> proposalDetail(int id, { int xLamToOccupancy }) async
    test('test proposalDetail', () async {
      // TODO
    });

    //Future<BuiltList<Proposal>> proposalList({ int xLamToOccupancy }) async
    test('test proposalList', () async {
      // TODO
    });

    //Future<ProposalRatingResult> proposalsRatingCreate(int id, CaseRatingRequest caseRatingRequest, { int xLamToOccupancy }) async
    test('test proposalsRatingCreate', () async {
      // TODO
    });

  });
}
