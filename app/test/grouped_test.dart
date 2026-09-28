import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/theme.dart';
import 'package:lamto/widgets/grouped.dart';

void main() {
  testWidgets('each row of an inset group is its own accessibility node', (
    tester,
  ) async {
    final semantics = tester.ensureSemantics();
    var tapped = 0;
    await tester.pumpWidget(
      MaterialApp(
        theme: lamToTheme(Brightness.light),
        home: Scaffold(
          body: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              InsetGroup(
                children: [
                  ListTile(
                    title: const Text('Chọn vị trí'),
                    onTap: () => tapped++,
                  ),
                  SwitchListTile(
                    title: const Text('Yêu cầu riêng tư'),
                    value: false,
                    onChanged: (_) {},
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );

    // A lone tappable row must not absorb the whole group: its node is the
    // row, so a screen reader focuses, reads, and taps just that row.
    final row = tester.getSemantics(find.text('Chọn vị trí'));
    expect(
      row.rect.height,
      tester.getSize(find.widgetWithText(ListTile, 'Chọn vị trí')).height,
    );
    expect(row.label, 'Chọn vị trí');

    tester.semantics.tap(find.semantics.byLabel('Chọn vị trí'));
    expect(tapped, 1);
    semantics.dispose();
  });

  testWidgets('empty state names what is missing and the next step', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: lamToTheme(Brightness.light),
        home: Scaffold(
          body: EmptyState(
            icon: Icons.inbox_outlined,
            message: 'Bạn chưa gửi phản ánh nào.',
            action: TextButton(onPressed: () {}, child: const Text('Phản ánh')),
          ),
        ),
      ),
    );

    expect(find.text('Bạn chưa gửi phản ánh nào.'), findsOneWidget);
    expect(find.text('Phản ánh'), findsOneWidget);
  });
}
