import 'package:built_collection/built_collection.dart';
import 'package:built_value/json_object.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/features/proposals/proposal_detail_screen.dart';
import 'package:lamto/features/proposals/proposals_list_screen.dart';
import 'package:lamto/features/proposals/proposals_repository.dart';
import 'package:lamto/l10n/app_localizations.dart';
import 'package:lamto_api/lamto_api.dart';

Proposal _proposal({bool canRate = true}) => Proposal(
  (b) => b
    ..id = 7
    ..buildingId = 1
    ..status = 'COMPLETED'
    ..completedAt = DateTime.utc(2026, 7, 20)
    ..currentVersion = MapBuilder<String, JsonObject?>({
      'number': JsonObject(2),
      'purpose': JsonObject('Repair the lobby lift'),
      'proposed_action': JsonObject('Replace the control board'),
      'amount_vnd': JsonObject(12500000),
      'fund_code': JsonObject('GENERAL'),
      'contractor_name': JsonObject('Acme Lift'),
      'expected_schedule': JsonObject('Within 14 days'),
      'can_rate': JsonObject(canRate),
      'versions': JsonObject([
        {
          'number': 1,
          'published_at': '2026-07-01T00:00:00Z',
          'evidence_level': 'CHAIN_CONFIRMED',
        },
        {
          'number': 2,
          'published_at': '2026-07-10T00:00:00Z',
          'evidence_level': 'LOCAL_SIGNED',
        },
      ]),
      'updates': JsonObject([
        {'result': 'Control board installed', 'created_at': '2026-07-18'},
      ]),
      'settlement': JsonObject({'settled': true}),
    }),
);

class _FakeProposalsRepository implements ProposalsRepository {
  bool? satisfied;

  @override
  Future<PaginatedProposalList> listProposals({String? cursor}) async =>
      PaginatedProposalList(results: BuiltList([_proposal()]));

  @override
  Future<ProposalDetail> fetchProposal(int id) async => _proposal();

  @override
  Future<ProposalRatingResult> rateProposal({
    required int id,
    required bool satisfied,
    String comment = '',
  }) async {
    this.satisfied = satisfied;
    return ProposalRatingResult(
      (b) => b
        ..id = 1
        ..proposalId = id
        ..satisfied = satisfied,
    );
  }
}

Widget _host(Widget child, _FakeProposalsRepository repository) =>
    ProviderScope(
      overrides: [proposalsRepositoryProvider.overrideWithValue(repository)],
      child: MaterialApp(
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        locale: const Locale('en'),
        home: child,
      ),
    );

void main() {
  testWidgets('proposal list shows purpose, status and tabular amount', (
    tester,
  ) async {
    final repository = _FakeProposalsRepository();
    await tester.pumpWidget(
      _host(const Scaffold(body: ProposalsListScreen()), repository),
    );
    await tester.pumpAndSettle();

    expect(find.text('Repair the lobby lift'), findsOneWidget);
    expect(find.text('Completed'), findsOneWidget);
    expect(find.textContaining('12.500.000'), findsOneWidget);
  });

  testWidgets('proposal detail shows flat evidence, progress and rating', (
    tester,
  ) async {
    final repository = _FakeProposalsRepository();
    await tester.pumpWidget(
      _host(const ProposalDetailScreen(proposalId: 7), repository),
    );
    await tester.pumpAndSettle();

    for (final label in [
      'Problem or need',
      'Proposed action',
      'Estimated cost',
      'Funding source',
      'Contractor',
      'Expected schedule',
      'Published versions',
      'Payment settlement',
    ]) {
      await tester.scrollUntilVisible(
        find.text(label),
        150,
        scrollable: find.byType(Scrollable).last,
      );
      expect(find.text(label), findsOneWidget);
    }
    expect(find.text('Version 1', skipOffstage: false), findsOneWidget);
    expect(
      find.text('Anchored on the blockchain', skipOffstage: false),
      findsOneWidget,
    );
    expect(
      find.text('Control board installed', skipOffstage: false),
      findsOneWidget,
    );
    expect(find.text('Paid and acknowledged by the payee'), findsOneWidget);

    await tester.scrollUntilVisible(
      find.text('Rate the result'),
      150,
      scrollable: find.byType(Scrollable).last,
    );
    await tester.tap(find.text('Rate the result'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Not satisfied'));
    await tester.tap(find.text('Send rating'));
    await tester.pumpAndSettle();
    expect(repository.satisfied, isFalse);
  });
}
