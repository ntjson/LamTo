import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:camera/camera.dart';
import 'package:dio/dio.dart';

import 'app.dart';
import 'theme.dart';
import 'core/config.dart';
import 'core/provider_retry.dart';
import 'features/gate/reader/gate_reader_screen.dart';
import 'features/gate/reader/reader_repository.dart';

Future<void> main() async {
  if (!gateReaderMode) {
    runApp(
      const ProviderScope(retry: retryTransientFailures, child: LamToApp()),
    );
    return;
  }
  WidgetsFlutterBinding.ensureInitialized();
  final cameras = await availableCameras();
  final controller = CameraController(
    cameras.first,
    ResolutionPreset.medium,
    enableAudio: false,
  );
  await controller.initialize();
  final dio = Dio(BaseOptions(baseUrl: apiBaseUrl));
  runApp(
    MaterialApp(
      theme: lamToTheme(Brightness.light),
      darkTheme: lamToTheme(Brightness.dark),
      home: GateReaderScreen(
        camera: CameraReader(controller),
        repositoryFor: (credential) => ReaderRepository(dio, credential),
        onBaseUrl: (url) => dio.options.baseUrl = url,
      ),
    ),
  );
}
