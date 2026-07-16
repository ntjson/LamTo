import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'providers.dart';

/// Fetches a signed relative URL through the shared Dio (knox token attached)
/// and renders the bytes. Image.network cannot carry our auth header.
class AuthenticatedImage extends ConsumerWidget {
  const AuthenticatedImage(this.url, {this.width, this.height, super.key});

  final String url;
  final double? width;
  final double? height;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final dio = ref.watch(dioProvider);
    return FutureBuilder<Response<List<int>>>(
      future: dio.get<List<int>>(
        url,
        options: Options(responseType: ResponseType.bytes),
      ),
      builder: (context, snapshot) {
        if (snapshot.hasData && snapshot.data?.data != null) {
          return Image.memory(
            Uint8List.fromList(snapshot.data!.data!),
            width: width,
            height: height,
            fit: BoxFit.cover,
          );
        }
        final placeholder = snapshot.hasError
            ? const Icon(Icons.broken_image_outlined)
            : const Center(child: CircularProgressIndicator.adaptive());
        return SizedBox(width: width, height: height, child: placeholder);
      },
    );
  }
}
