import 'package:flutter/material.dart';

class BrandIdentity extends StatelessWidget {
  const BrandIdentity({this.width = 180, super.key});

  final double width;

  @override
  Widget build(BuildContext context) {
    final logo = Image.asset(
      'assets/brand/lamto-logo.png',
      width: width,
      semanticLabel: 'LÀM TỔ',
    );
    // The navy wordmark disappears on a dark ground, so in dark mode it sits
    // on the same white plate the mark uses as an app icon.
    if (Theme.of(context).brightness != Brightness.dark) {
      return Center(child: logo);
    }
    return Center(
      child: Container(
        padding: EdgeInsets.all(width * 0.08),
        decoration: BoxDecoration(
          color: const Color(0xFFFFFFFF),
          borderRadius: BorderRadius.circular(width * 0.12),
        ),
        child: logo,
      ),
    );
  }
}

/// The mark alone on its white tile, like an app icon: the brand where the
/// full wordmark would be too small to read.
class BrandMark extends StatelessWidget {
  const BrandMark({this.size = 56, super.key});

  final double size;

  @override
  Widget build(BuildContext context) => Center(
    child: Container(
      width: size,
      height: size,
      padding: EdgeInsets.all(size * 0.12),
      decoration: BoxDecoration(
        color: const Color(0xFFFFFFFF),
        borderRadius: BorderRadius.circular(size * 0.24),
        boxShadow: const [
          BoxShadow(color: Color(0x14000000), blurRadius: 0, spreadRadius: 1),
          BoxShadow(
            color: Color(0x1F000000),
            blurRadius: 12,
            offset: Offset(0, 4),
          ),
        ],
      ),
      child: Image.asset(
        'assets/brand/lamto-mark.png',
        semanticLabel: 'LÀM TỔ',
      ),
    ),
  );
}
