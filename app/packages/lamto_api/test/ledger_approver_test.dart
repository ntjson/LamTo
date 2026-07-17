import 'package:test/test.dart';
import 'package:lamto_api/lamto_api.dart';

// tests for LedgerApprover
void main() {
  final instance = LedgerApproverBuilder();
  // TODO add properties to the builder and call build()

  group(LedgerApprover, () {
    // Machine role: board, resident_rep, or emergency.
    // String role
    test('to test the property `role`', () async {
      // TODO
    });

    // Display name of the approver.
    // String name
    test('to test the property `name`', () async {
      // TODO
    });

    // Decision code (e.g. APPROVE).
    // String decision
    test('to test the property `decision`', () async {
      // TODO
    });

  });
}
