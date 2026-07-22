import 'package:flutter/material.dart';

class GateRegistrationScreen extends StatelessWidget {
  const GateRegistrationScreen({super.key});
  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Vehicles & face')),
    body: const ListView(children: [
      ListTile(title: Text('Vehicles')),
      ListTile(title: Text('Face'), subtitle: Text('Your review photo is deleted after review.')),
    ]),
  );
}
