import 'package:intl/intl.dart';

/// Integer VND with Vietnamese grouping (DESIGN.md: tabular numerals come
/// from the Amount text style; this handles digits + currency sign).
final _vnd = NumberFormat.decimalPattern('vi');

String formatVnd(int amount) => '${_vnd.format(amount)} ₫';
