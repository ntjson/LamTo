import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'providers.dart';

/// Fetches a signed relative URL through the shared Dio (knox token attached)
/// and renders the bytes. Image.network cannot carry our auth header.
///
/// The GET is memoized per [url]: parent rebuilds with the same URL reuse the
/// in-flight or completed future (no re-fetch).
class AuthenticatedImage extends ConsumerStatefulWidget {
  const AuthenticatedImage(this.url, {this.width, this.height, super.key});

  final String url;
  final double? width;
  final double? height;

  @override
  ConsumerState<AuthenticatedImage> createState() => _AuthenticatedImageState();
}

class _AuthenticatedImageState extends ConsumerState<AuthenticatedImage> {
  Future<Response<List<int>>>? _future;
  String? _url;

  Future<Response<List<int>>> _startFetch(Dio dio, String url) {
    return dio.get<List<int>>(
      url,
      options: Options(responseType: ResponseType.bytes),
    );
  }

  Future<Response<List<int>>> _futureFor(Dio dio) {
    if (_future == null || _url != widget.url) {
      _url = widget.url;
      _future = _startFetch(dio, widget.url);
    }
    return _future!;
  }

  @override
  void didUpdateWidget(covariant AuthenticatedImage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.url != widget.url) {
      _future = null;
      _url = null;
    }
  }

  @override
  Widget build(BuildContext context) {
    final dio = ref.watch(dioProvider);
    return FutureBuilder<Response<List<int>>>(
      future: _futureFor(dio),
      builder: (context, snapshot) {
        if (snapshot.hasData && snapshot.data?.data != null) {
          return Image.memory(
            Uint8List.fromList(snapshot.data!.data!),
            width: widget.width,
            height: widget.height,
            fit: BoxFit.cover,
          );
        }
        final placeholder = snapshot.hasError
            ? const Icon(Icons.broken_image_outlined)
            : const Center(child: CircularProgressIndicator.adaptive());
        return SizedBox(
          width: widget.width,
          height: widget.height,
          child: placeholder,
        );
      },
    );
  }
}
