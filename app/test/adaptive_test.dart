import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/core/page_body.dart';

void main() {
  testWidgets('PageBody caps content width on wide screens', (tester) async {
    tester.view.physicalSize = const Size(1000, 700);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(body: PageBody(child: SizedBox.expand())),
      ),
    );
    expect(tester.getSize(find.byType(SizedBox)).width, 640);
  });
}
