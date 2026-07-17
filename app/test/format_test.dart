import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/core/format.dart';

void main() {
  test('formatVnd groups with dots and appends dong sign', () {
    expect(formatVnd(0), '0 ₫');
    expect(formatVnd(1500000), '1.500.000 ₫');
    expect(formatVnd(-250000), '-250.000 ₫');
  });
}
