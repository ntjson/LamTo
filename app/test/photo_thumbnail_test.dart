import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/features/reports/photo_thumbnail.dart';
import 'package:lamto/l10n/app_localizations.dart';

import 'report_photo_fakes.dart';

Widget _wrap(Widget child) => MaterialApp(
  localizationsDelegates: AppLocalizations.localizationsDelegates,
  supportedLocales: AppLocalizations.supportedLocales,
  locale: const Locale('vi'),
  home: Scaffold(body: child),
);

void main() {
  testWidgets('renders a preview with n-of-m semantics and delete', (
    tester,
  ) async {
    final semantics = tester.ensureSemantics();
    var deleted = false;
    await tester.pumpWidget(
      _wrap(
        PhotoThumbnail(
          bytes: jpegBytes,
          index: 1,
          count: 2,
          onDelete: () => deleted = true,
        ),
      ),
    );

    // The picture (not a filename) is the confirmation.
    expect(find.byType(Image), findsOneWidget);
    // Drawn from the held bytes, not from a file path.
    final provider = tester.widget<Image>(find.byType(Image)).image;
    expect(provider, isA<ResizeImage>());
    final source = (provider as ResizeImage).imageProvider;
    expect(source, isA<MemoryImage>());
    expect((source as MemoryImage).bytes, jpegBytes);
    expect(find.text('a.jpg'), findsNothing);
    expect(find.bySemanticsLabel('Ảnh 1/2'), findsOneWidget);

    await tester.tap(find.byIcon(Icons.close));
    expect(deleted, isTrue);
    semantics.dispose();
  });

  testWidgets('failed photo shows a non-color state and labeled retry', (
    tester,
  ) async {
    final semantics = tester.ensureSemantics();
    var retried = 0;
    await tester.pumpWidget(
      _wrap(
        PhotoThumbnail(
          bytes: pngBytes,
          index: 2,
          count: 3,
          onRetry: () => retried++,
        ),
      ),
    );

    // Icon + word carry the failed state, never color alone.
    expect(find.byIcon(Icons.error_outline), findsOneWidget);
    expect(find.text('Thử lại'), findsOneWidget);
    expect(
      find.bySemanticsLabel('Ảnh 2/3 — Chưa tải lên được'),
      findsOneWidget,
    );
    expect(find.byIcon(Icons.close), findsNothing); // retry list: no delete

    await tester.tap(find.text('Thử lại'));
    expect(retried, 1);
    semantics.dispose();
  });
}
