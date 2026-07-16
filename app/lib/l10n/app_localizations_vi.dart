// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Vietnamese (`vi`).
class AppLocalizationsVi extends AppLocalizations {
  AppLocalizationsVi([String locale = 'vi']) : super(locale);

  @override
  String get appTitle => 'LamTo';

  @override
  String get loginTitle => 'Đăng nhập';

  @override
  String get loginIdentifier => 'Số điện thoại hoặc email';

  @override
  String get loginPassword => 'Mật khẩu';

  @override
  String get loginSubmit => 'Đăng nhập';

  @override
  String get occupancyPickerTitle => 'Chọn căn hộ của bạn';

  @override
  String get bootstrapRetry => 'Thử lại';

  @override
  String get signOut => 'Đăng xuất';

  @override
  String get noOccupancyTitle => 'Chưa có căn hộ liên kết';

  @override
  String get noOccupancyBody =>
      'Bạn đã đăng nhập nhưng chưa có căn hộ nào được liên kết. Vui lòng liên hệ ban quản lý tòa nhà, hoặc đăng xuất và thử tài khoản khác.';

  @override
  String get errAuthFailed =>
      'Số điện thoại/email hoặc mật khẩu không đúng. Chưa có gì được gửi đi. Vui lòng thử lại.';

  @override
  String get errThrottled =>
      'Bạn đã thử quá nhiều lần. Chưa có gì được gửi đi. Vui lòng đợi vài phút rồi thử lại.';

  @override
  String get errOccupancyRequired => 'Vui lòng chọn căn hộ áp dụng.';

  @override
  String get errNetwork =>
      'Không có kết nối. Thao tác chưa được gửi. Kiểm tra mạng và thử lại.';

  @override
  String get errServer =>
      'Đã có lỗi từ phía hệ thống. Thao tác có thể chưa được lưu. Vui lòng thử lại sau.';

  @override
  String get errGeneric => 'Đã có lỗi xảy ra. Vui lòng thử lại.';

  @override
  String get tabHome => 'Trang chính';

  @override
  String get tabReport => 'Phản ánh';

  @override
  String get tabIssues => 'Việc của tôi';

  @override
  String get tabLedger => 'Sổ quỹ';

  @override
  String get tabAccount => 'Tài khoản';

  @override
  String get locationPickerTitle => 'Sự cố ở đâu?';

  @override
  String get locationChooseHere => 'Chọn khu vực này';

  @override
  String get commonRetry => 'Thử lại';

  @override
  String get reportFormTitle => 'Gửi phản ánh';

  @override
  String get reportTextLabel => 'Đã xảy ra chuyện gì?';

  @override
  String get reportLocationLabel => 'Vị trí';

  @override
  String get reportLocationEmpty => 'Chọn vị trí';

  @override
  String reportPhotosLabel(int max) {
    return 'Ảnh (tối đa $max)';
  }

  @override
  String get reportAddPhoto => 'Thêm ảnh';

  @override
  String get reportPhotoCamera => 'Chụp ảnh';

  @override
  String get reportPhotoGallery => 'Chọn từ thư viện';

  @override
  String get reportSubmit => 'Gửi phản ánh';

  @override
  String get reportSubmitted => 'Phản ánh của bạn đã được ghi nhận.';

  @override
  String get reportPhotosPending =>
      'Một số ảnh chưa tải lên được. Nội dung phản ánh đã được lưu — thử lại từng ảnh bên dưới.';

  @override
  String get reportPhotoRetry => 'Thử lại';

  @override
  String get reportConflict =>
      'Phản ánh này đã được gửi trước đó. Nội dung bạn vừa sửa sẽ được gửi thành phản ánh mới — bấm Gửi lần nữa.';

  @override
  String get reportMissingFields =>
      'Vui lòng mô tả sự cố và chọn vị trí. Chưa có gì được gửi đi.';

  @override
  String get reportViewIssue => 'Xem phản ánh này';

  @override
  String get reportAnother => 'Gửi phản ánh khác';

  @override
  String get issuesTitle => 'Việc của tôi';

  @override
  String get issuesEmpty => 'Bạn chưa gửi phản ánh nào.';

  @override
  String get issuesLoadMore => 'Tải thêm';

  @override
  String get statusOpen => 'Đang mở';

  @override
  String get statusResolved => 'Đã xử lý';
}
