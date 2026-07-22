import 'dart:io';

import 'package:camera/camera.dart';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';

import 'plate_ocr.dart';
import 'reader_credential_store.dart';
import 'reader_repository.dart';

abstract class ReaderCamera {
  Widget get preview;
  Future<XFile> capture();
  Future<void> dispose();
}

class CameraReader implements ReaderCamera {
  CameraReader(this.controller);
  final CameraController controller;
  @override
  Widget get preview => CameraPreview(controller);
  @override
  Future<XFile> capture() => controller.takePicture();
  @override
  Future<void> dispose() => controller.dispose();
}

class GateReaderScreen extends StatefulWidget {
  const GateReaderScreen({
    super.key,
    required this.repositoryFor,
    required this.camera,
    this.store,
    this.ocr = extractPlate,
  });
  final ReaderApi Function(String) repositoryFor;
  final ReaderCamera camera;
  final ReaderCredentialStore? store;
  final Future<String?> Function(String) ocr;
  @override
  State<GateReaderScreen> createState() => _GateReaderScreenState();
}

class _GateReaderScreenState extends State<GateReaderScreen> {
  final credential = TextEditingController();
  String? token;
  String? direction;
  ReaderResult? result;
  String? message;
  bool busy = false;
  ReaderCredentialStore get store => widget.store ?? ReaderCredentialStore();

  @override
  void initState() {
    super.initState();
    store.read().then((value) {
      if (value != null) _activate(value, persist: false);
    });
  }

  @override
  void dispose() {
    credential.dispose();
    widget.camera.dispose();
    super.dispose();
  }

  Future<void> _capture(bool face) async {
    final image = await widget.camera.capture();
    setState(() {
      busy = true;
      message = null;
      result = null;
    });
    try {
      final api = widget.repositoryFor(token!);
      final value = face
          ? await api.recognizeFace(image.path)
          : await widget.ocr(image.path).then((plate) {
              if (plate == null) {
                throw const FormatException();
              }
              return api.recognizePlate(plate);
            });
      if (mounted) setState(() => result = value);
    } on FormatException {
      if (mounted) setState(() => message = 'Khong doc duoc bien so. Thu lai.');
    } on DioException catch (error) {
      if (mounted) setState(() => message = readerError(error));
    } catch (_) {
      if (mounted) {
        setState(
          () => message = 'Mat ket noi. Khung hinh khong duoc luu de gui lai.',
        );
      }
    } finally {
      try {
        await File(image.path).delete();
      } on FileSystemException {
        /* Already removed. */
      }
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> _activate(String value, {bool persist = true}) async {
    try {
      final device = await widget.repositoryFor(value).getDevice();
      if (persist) {
        await store.write(value);
      }
      if (mounted) {
        setState(() {
          token = value;
          direction = device.direction;
          message = null;
        });
      }
    } on DioException catch (error) {
      if (mounted) {
        setState(() => message = readerError(error));
      }
    } catch (_) {
      if (mounted) {
        setState(() => message = 'Mat ket noi. Khong the kich hoat dau doc.');
      }
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Dau doc cong')),
    body: token == null
        ? Center(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  TextField(
                    controller: credential,
                    obscureText: true,
                    decoration: const InputDecoration(labelText: 'Ma thiet bi'),
                  ),
                  FilledButton(
                    onPressed: () async {
                      final value = credential.text.trim();
                      if (value.isNotEmpty) {
                        await _activate(value);
                      }
                    },
                    child: const Text('Kich hoat dau doc'),
                  ),
                  if (message != null) Text(message!),
                ],
              ),
            ),
          )
        : Column(
            children: [
              Expanded(
                child: Stack(
                  fit: StackFit.expand,
                  children: [
                    widget.camera.preview,
                    Align(
                      alignment: Alignment.topCenter,
                      child: SafeArea(child: Chip(label: Text(direction!))),
                    ),
                  ],
                ),
              ),
              if (result != null)
                Card(
                  color: result!.matched
                      ? Colors.green.shade100
                      : Colors.red.shade100,
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Text(
                      result!.matched
                          ? '${result!.name}\nCan ${result!.unit}\n${result!.direction}'
                          : 'Khong nhan dien duoc\n${result!.direction}',
                      textAlign: TextAlign.center,
                    ),
                  ),
                ),
              if (message != null) Text(message!),
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  FilledButton.icon(
                    onPressed: busy ? null : () => _capture(false),
                    icon: const Icon(Icons.directions_car),
                    label: const Text('Quet bien so'),
                  ),
                  const SizedBox(width: 8),
                  FilledButton.icon(
                    onPressed: busy ? null : () => _capture(true),
                    icon: const Icon(Icons.face),
                    label: const Text('Quet khuon mat'),
                  ),
                ],
              ),
              TextButton(
                onPressed: () async {
                  await store.clear();
                  if (mounted) {
                    setState(() {
                      token = null;
                      result = null;
                    });
                  }
                },
                child: const Text('Xoa ma thiet bi'),
              ),
            ],
          ),
  );
}

String readerError(DioException error) {
  final data = error.response?.data;
  final code = data is Map ? '${data['code']}' : '';
  return switch (code) {
    'gate_device_revoked' => 'Ma thiet bi da bi thu hoi.',
    'gate_device_expired' => 'Ma thiet bi da het han.',
    'gate_no_face_detected' => 'Khong tim thay khuon mat. Thu lai.',
    'gate_multiple_faces' => 'Khung hinh chi duoc co mot khuon mat.',
    'gate_face_too_small' => 'Khuon mat qua nho. Hay lai gan hon.',
    'gate_face_too_blurry' => 'Khung hinh qua mo. Thu lai.',
    'gate_face_unusable' => 'Khung hinh khong the dung de nhan dien.',
    'gate_face_upload_too_large' => 'Khung hinh vuot qua dung luong cho phep.',
    'gate_photo_rejected' => 'Khung hinh bi tu choi truoc khi xu ly.',
    'gate_model_unavailable' => 'Dau doc dang ngoai tuyen.',
    'gate_recognition_throttled' => 'Thao tac qua nhanh. Vui long cho.',
    _ => 'Mat ket noi. Khung hinh khong duoc luu de gui lai.',
  };
}
