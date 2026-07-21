import 'package:built_collection/built_collection.dart';
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/providers.dart';

typedef ProposalDetail = Proposal;

class PaginatedProposalList {
  const PaginatedProposalList({required this.results, this.next});

  final BuiltList<Proposal> results;
  final String? next;
}

abstract class ProposalsRepository {
  Future<PaginatedProposalList> listProposals({String? cursor});
  Future<ProposalDetail> fetchProposal(int id);
  Future<ProposalRatingResult> rateProposal({
    required int id,
    required bool satisfied,
    String comment = '',
  });
}

class DioProposalsRepository implements ProposalsRepository {
  DioProposalsRepository(Dio dio)
    : _proposals = ProposalsApi(dio, standardSerializers);

  final ProposalsApi _proposals;

  @override
  Future<PaginatedProposalList> listProposals({String? cursor}) async {
    final response = await _proposals.proposalList();
    return PaginatedProposalList(results: response.data!);
  }

  @override
  Future<ProposalDetail> fetchProposal(int id) async =>
      (await _proposals.proposalDetail(id: id)).data!;

  @override
  Future<ProposalRatingResult> rateProposal({
    required int id,
    required bool satisfied,
    String comment = '',
  }) async {
    final response = await _proposals.proposalsRatingCreate(
      id: id,
      caseRatingRequest: CaseRatingRequest(
        (b) => b
          ..satisfied = satisfied
          ..comment = comment,
      ),
    );
    return response.data!;
  }
}

final proposalsRepositoryProvider = Provider<ProposalsRepository>(
  (ref) => DioProposalsRepository(ref.watch(dioProvider)),
);

final proposalDetailProvider = FutureProvider.autoDispose
    .family<ProposalDetail, int>((ref, id) {
      ref.watch(occupancyScopedProviders);
      return ref.watch(proposalsRepositoryProvider).fetchProposal(id);
    });
