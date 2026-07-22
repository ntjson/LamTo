import 'package:flutter/material.dart';
class GateReaderScreen extends StatelessWidget {
  const GateReaderScreen({super.key});
  @override
  Widget build(BuildContext context) => Scaffold(appBar: AppBar(title: const Text('Gate reader')), body: const Center(child: Text('Enter reader credential')));
}
