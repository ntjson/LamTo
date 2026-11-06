import 'package:flutter/material.dart';

/// One Home ad: a third-party vendor's slide in the Home carousel.
///
/// Demo only: the ads ship inside the app and are drawn rather than
/// uploaded. LamTo records no money for an ad, and nothing about a resident's
/// viewing or tapping is collected.
class HomeAd {
  const HomeAd({
    required this.advertiser,
    required this.title,
    required this.subtitle,
    required this.offer,
    required this.icon,
    required this.colors,
    this.link,
  });

  final String advertiser;
  final String title;
  final String subtitle;
  final String offer;
  final IconData icon;

  /// Slide gradient, top-left to bottom-right.
  final List<Color> colors;

  /// Optional https page, opened in the external browser.
  final Uri? link;
}

/// Made-up local vendors for the demo; no real brands.
const demoHomeAds = <HomeAd>[
  HomeAd(
    advertiser: 'Giặt Sấy Mây Trắng',
    title: 'Giặt sấy tận cửa',
    subtitle: 'Nhận đồ tại sảnh, trả trong 24 giờ',
    offer: 'Giảm 30% đơn đầu',
    icon: Icons.local_laundry_service_outlined,
    colors: [Color(0xFF0E7490), Color(0xFF22D3EE)],
  ),
  HomeAd(
    advertiser: 'Nước Suối Nguồn Xanh',
    title: 'Nước bình 19L giao tận căn',
    subtitle: 'Đặt trước 10 giờ, giao ngay trong ngày',
    offer: 'Mua 5 tặng 1',
    icon: Icons.water_drop_outlined,
    colors: [Color(0xFF1D4ED8), Color(0xFF60A5FA)],
  ),
  HomeAd(
    advertiser: 'Dọn Nhà Ong Vàng',
    title: 'Tổng vệ sinh căn hộ',
    subtitle: 'Đội 2 người, đủ dụng cụ, xong trong 3 giờ',
    offer: 'Từ 399.000 ₫',
    icon: Icons.cleaning_services_outlined,
    colors: [Color(0xFFC2410C), Color(0xFFFB923C)],
  ),
];
