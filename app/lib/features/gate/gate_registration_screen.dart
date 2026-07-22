import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import 'gate_repository.dart';
import 'plate_text.dart';

class GateRegistrationScreen extends StatefulWidget {
  const GateRegistrationScreen({super.key, required this.repository, this.picker});
  final GateRepository repository;
  final ImagePicker? picker;
  @override State<GateRegistrationScreen> createState() => _GateRegistrationScreenState();
}

class _GateRegistrationScreenState extends State<GateRegistrationScreen> {
  final plate = TextEditingController();
  Map<String, dynamic>? data;
  String? error;
  bool busy = false;
  @override void initState() { super.initState(); _load(); }
  @override void dispose() { plate.dispose(); super.dispose(); }
  Future<void> _run(Future<void> Function() action) async {
    setState(() { busy = true; error = null; });
    try { await action(); await _load(); } catch (e) { setState(() => error = gateErrorMessage(e)); } finally { if (mounted) setState(() => busy = false); }
  }
  Future<void> _load() async { try { final value = await widget.repository.registrations(); if (mounted) setState(() => data = value); } catch (e) { if (mounted) setState(() => error = gateErrorMessage(e)); } }
  @override Widget build(BuildContext context) {
    final plates = (data?['plates'] as List?) ?? const [];
    final face = data?['face'] as Map?;
    return Scaffold(appBar: AppBar(title: const Text('Dang ky cong')), body: ListView(padding: const EdgeInsets.all(16), children: [
      if (error != null) Text(error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
      TextField(controller: plate, decoration: InputDecoration(labelText: 'Bien so xe', helperText: normalizePlateText(plate.text)), onChanged: (_) => setState(() {})),
      FilledButton(onPressed: busy || !isPlausiblePlate(normalizePlateText(plate.text)) ? null : () => _run(() => widget.repository.addPlate(plate.text)), child: const Text('Gui bien so de duyet')),
      for (final item in plates.cast<Map>()) ListTile(title: Text('${item['plate']}'), subtitle: Text(statusText('${item['status']}', '${item['review_note'] ?? ''}')), trailing: IconButton(tooltip: 'Thu hoi bien so', icon: const Icon(Icons.delete), onPressed: () => _run(() => widget.repository.deletePlate(item['id'] as int)))),
      const Divider(),
      ListTile(title: const Text('Khuon mat'), subtitle: Text(face == null ? 'Chua dang ky' : statusText('${face['status']}', '${face['review_note'] ?? ''}'))),
      FilledButton(onPressed: busy ? null : () async { final photo = await (widget.picker ?? ImagePicker()).pickImage(source: ImageSource.camera); if (photo != null) await _run(() => widget.repository.submitFace(photo.path)); }, child: const Text('Chup anh dang ky')),
      if (face != null) TextButton(onPressed: () => _run(widget.repository.deleteFace), child: const Text('Thu hoi khuon mat')),
      const Text('Anh chi duoc giu de quan ly xem xet va se bi xoa sau khi co quyet dinh.'),
    ]));
  }
}

String statusText(String status, String note) => switch (status) { 'PENDING' => 'Dang cho duyet', 'APPROVED' => 'Da duyet', 'REJECTED' => 'Bi tu choi: $note', 'EXPIRED' => 'Anh da het han, vui long gui lai', _ => 'Khong ro trang thai' };
String gateErrorMessage(Object error) {
  final code = error is DioException && error.response?.data is Map ? '${(error.response!.data as Map)['code']}' : 'network_error';
  return switch (code) { 'gate_no_face_detected' => 'Khong tim thay khuon mat.', 'gate_multiple_faces' => 'Anh chi duoc co mot khuon mat.', 'gate_face_too_small' => 'Khuon mat qua nho.', 'gate_face_too_blurry' => 'Anh qua mo.', 'gate_plate_already_registered' => 'Bien so da duoc dang ky. Vui long lien he ban quan ly.', 'gate_model_unavailable' => 'Dich vu khuon mat dang tam ngung.', _ => 'Khong the ket noi. Khong co du lieu nao duoc luu.' };
}
