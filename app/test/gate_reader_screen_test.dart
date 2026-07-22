import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/material.dart';
import 'package:lamto/features/gate/reader/gate_reader_screen.dart';
void main() { testWidgets('prompts for credential', (tester) async { await tester.pumpWidget(const MaterialApp(home: GateReaderScreen())); expect(find.text('Enter reader credential'), findsOneWidget); }); }
