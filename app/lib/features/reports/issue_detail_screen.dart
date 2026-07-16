import 'package:flutter/material.dart';

/// Minimal placeholder for Task 7 issue detail. Report form navigates here
/// after a successful create (committed-result "view issue").
class IssueDetailScreen extends StatelessWidget {
  const IssueDetailScreen({super.key, required this.reportId});

  final int reportId;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('Issue #$reportId')),
      body: Center(child: Text('Issue #$reportId')),
    );
  }
}
