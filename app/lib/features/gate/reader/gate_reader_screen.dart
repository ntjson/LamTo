import 'dart:io';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'plate_ocr.dart';
import 'reader_credential_store.dart';
import 'reader_repository.dart';

class GateReaderScreen extends StatefulWidget {
  const GateReaderScreen({super.key, required this.repositoryFor, this.store, this.picker, this.ocr = extractPlate});
  final ReaderApi Function(String) repositoryFor;
  final ReaderCredentialStore? store;
  final ImagePicker? picker;
  final Future<String?> Function(String) ocr;
  @override State<GateReaderScreen> createState() => _GateReaderScreenState();
}
class _GateReaderScreenState extends State<GateReaderScreen> {
  final credential = TextEditingController(); String? token; ReaderResult? result; String? message; bool busy = false;
  ReaderCredentialStore get store => widget.store ?? ReaderCredentialStore();
  @override void initState() { super.initState(); store.read().then((value) { if (mounted) setState(() => token = value); }); }
  @override void dispose() { credential.dispose(); super.dispose(); }
  Future<void> _capture(bool face) async {
    final image = await (widget.picker ?? ImagePicker()).pickImage(source: ImageSource.camera);
    if (image == null) return;
    setState(() { busy = true; message = null; result = null; });
    try {
      final api = widget.repositoryFor(token!);
      final value = face ? await api.recognizeFace(image.path) : await widget.ocr(image.path).then((plate) { if (plate == null) throw const FormatException(); return api.recognizePlate(plate); });
      if (mounted) setState(() => result = value);
    } on FormatException { if (mounted) setState(() => message = 'Khong doc duoc bien so. Thu lai.'); }
      on DioException catch (e) { if (mounted) setState(() => message = readerError(e)); }
      catch (_) { if (mounted) setState(() => message = 'Mat ket noi. Khung hinh khong duoc luu de gui lai.'); }
    finally { try { await File(image.path).delete(); } on FileSystemException { /* Already removed by the platform. */ } if (mounted) setState(() => busy = false); }
  }
  @override Widget build(BuildContext context) => Scaffold(appBar: AppBar(title: const Text('Dau doc cong')), body: Center(child: Padding(padding: const EdgeInsets.all(24), child: token == null ? Column(mainAxisSize: MainAxisSize.min, children: [TextField(controller: credential, obscureText: true, decoration: const InputDecoration(labelText: 'Ma thiet bi')), FilledButton(onPressed: () async { final value = credential.text.trim(); if (value.isNotEmpty) { await store.write(value); setState(() => token = value); } }, child: const Text('Kich hoat dau doc'))]) : Column(mainAxisSize: MainAxisSize.min, children: [
    if (result != null) Card(color: result!.matched ? Colors.green.shade100 : Colors.red.shade100, child: Padding(padding: const EdgeInsets.all(24), child: Text(result!.matched ? '${result!.name}\nCan ${result!.unit}\n${result!.direction}\n${result!.score ?? ''}' : 'Khong nhan dien duoc\n${result!.direction}', textAlign: TextAlign.center))),
    if (message != null) Text(message!),
    FilledButton.icon(onPressed: busy ? null : () => _capture(false), icon: const Icon(Icons.directions_car), label: const Text('Quet bien so')),
    FilledButton.icon(onPressed: busy ? null : () => _capture(true), icon: const Icon(Icons.face), label: const Text('Quet khuon mat')),
    TextButton(onPressed: () async { await store.clear(); setState(() { token = null; result = null; }); }, child: const Text('Xoa ma thiet bi')),
  ]))));
}
String readerError(DioException error) { final data = error.response?.data; final code = data is Map ? '${data['code']}' : ''; return switch (code) { 'gate_device_revoked' => 'Ma thiet bi da bi thu hoi.', 'gate_device_expired' => 'Ma thiet bi da het han.', 'gate_no_face_detected' => 'Khong tim thay khuon mat. Thu lai.', 'gate_model_unavailable' => 'Dau doc dang ngoai tuyen.', 'gate_recognition_throttled' => 'Thao tac qua nhanh. Vui long cho.', _ => 'Mat ket noi. Khung hinh khong duoc luu de gui lai.' }; }
