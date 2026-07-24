import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/features/notifications/deep_link.dart';

void main() {
  test('event key and push link map bill to DeepLinkBill', () {
    expect(parseEventKey('building.bill_issued:bill:7'), const DeepLinkBill(7));
    expect(parsePushLink(type: 'bill', id: '7'), const DeepLinkBill(7));
  });
}
