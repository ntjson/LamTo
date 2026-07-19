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
  String get loginMissingFields =>
      'Vui lòng nhập số điện thoại/email và mật khẩu. Chưa có gì được gửi đi.';

  @override
  String get loginShowPassword => 'Hiện mật khẩu';

  @override
  String get loginHidePassword => 'Ẩn mật khẩu';

  @override
  String get apiBaseUrlTitle => 'Máy chủ API';

  @override
  String get apiBaseUrlLabel => 'URL API';

  @override
  String get apiBaseUrlHelp =>
      'Dán URL Cloudflare tunnel (https://….trycloudflare.com). Đổi URL không cần cài APK mới. Lưu xong sẽ đăng xuất.';

  @override
  String get apiBaseUrlSave => 'Lưu URL';

  @override
  String get apiBaseUrlReset => 'Mặc định';

  @override
  String get apiBaseUrlInvalid =>
      'URL không hợp lệ. Cần dạng https://… hoặc http://…';

  @override
  String get apiBaseUrlSaved => 'Đã lưu URL máy chủ.';

  @override
  String get occupancyPickerTitle => 'Chọn căn hộ của bạn';

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
  String get reportSubmitting => 'Đang gửi…';

  @override
  String get reportDraftSaving => 'Đang lưu bản nháp…';

  @override
  String get reportDraftSaved => 'Đã lưu bản nháp';

  @override
  String get reportDraftSaveFailed =>
      'Chưa lưu được bản nháp. Nội dung vẫn còn trên màn hình; hãy kiểm tra thiết bị rồi thử lại.';

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
  String get reportEnableNotifications => 'Nhận thông báo cập nhật';

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

  @override
  String issueDetailTitle(int id) {
    return 'Phản ánh #$id';
  }

  @override
  String get timelineSubmitted => 'Đã gửi phản ánh';

  @override
  String get timelineTriagePending => 'Đang chờ ban quản lý xem xét';

  @override
  String get timelineTriageDone => 'Ban quản lý đã xem xét';

  @override
  String timelineCase(String category) {
    return 'Đã ghép vào yêu cầu xử lý: $category';
  }

  @override
  String timelineWork(String status, String deadline) {
    return 'Công việc $status, hạn $deadline';
  }

  @override
  String get timelineCompleted => 'Công việc đã hoàn thành';

  @override
  String get rateWorkCta => 'Đánh giá công việc';

  @override
  String get rateWorkTitle => 'Công việc thế nào?';

  @override
  String rateStarLabel(int score) {
    return '$score trên 5 sao';
  }

  @override
  String get rateCommentLabel => 'Nhận xét (không bắt buộc)';

  @override
  String get rateSubmit => 'Gửi đánh giá';

  @override
  String get rateThanks => 'Cảm ơn bạn đã đánh giá.';

  @override
  String get workStatusAssigned => 'Đã giao';

  @override
  String get workStatusInProgress => 'Đang thực hiện';

  @override
  String get workStatusAwaiting => 'Chờ nghiệm thu';

  @override
  String get workStatusAccepted => 'Đã nghiệm thu';

  @override
  String get workStatusClosed => 'Đã đóng';

  @override
  String get workStatusCancelled => 'Đã hủy';

  @override
  String get homeFundTitle => 'Quỹ bảo trì';

  @override
  String get homeFundInflows => 'Thu (30 ngày)';

  @override
  String get homeFundOutflows => 'Chi (30 ngày)';

  @override
  String get homeActiveReports => 'Phản ánh đang mở';

  @override
  String get homeRecentSpending => 'Khoản chi mới công bố';

  @override
  String get homeNoActiveReports => 'Không có phản ánh đang mở.';

  @override
  String get homeNoSpending => 'Chưa có khoản chi nào được công bố.';

  @override
  String get homeReportsLoading => 'Đang tải phản ánh…';

  @override
  String get homeSpendingLoading => 'Đang tải khoản chi…';

  @override
  String get notificationsTitle => 'Thông báo';

  @override
  String get notificationsEmpty => 'Chưa có thông báo nào.';

  @override
  String get notificationsLoadMore => 'Tải thêm';

  @override
  String get ledgerTitle => 'Sổ quỹ tòa nhà';

  @override
  String get ledgerDetailTitle => 'Chi tiết khoản chi';

  @override
  String get ledgerEmpty => 'Không có khoản chi nào trong kỳ này.';

  @override
  String get ledgerAllTime => 'Tất cả';

  @override
  String get ledgerLoadMore => 'Tải thêm';

  @override
  String ledgerPublishedOn(String date) {
    return 'Công bố ngày $date';
  }

  @override
  String get ledgerAmount => 'Số tiền';

  @override
  String get ledgerContractor => 'Nhà thầu';

  @override
  String get ledgerWhatFixed => 'Đã sửa gì';

  @override
  String get ledgerWhy => 'Lý do';

  @override
  String get ledgerApprovers => 'Người phê duyệt';

  @override
  String ledgerApproverBoard(String name) {
    return 'Ban quản trị: $name';
  }

  @override
  String ledgerApproverRep(String name) {
    return 'Đại diện cư dân: $name';
  }

  @override
  String ledgerApproverEmergency(String name) {
    return 'Ủy quyền khẩn cấp: $name';
  }

  @override
  String ledgerApproverGeneric(String name) {
    return '$name';
  }

  @override
  String ledgerVerifiedBy(String name) {
    return 'Thanh toán đã được $name xác nhận';
  }

  @override
  String get ledgerNotVerified => 'Thanh toán chưa được xác nhận';

  @override
  String get ledgerConclusionVerified => 'Khoản chi này đã được xác minh';

  @override
  String get ledgerConclusionVerifiedBody =>
      'Chứng từ thanh toán và tính toàn vẹn của bản ghi đã được xác nhận độc lập.';

  @override
  String get ledgerConclusionUnverified =>
      'Khoản chi này chưa được xác minh đầy đủ';

  @override
  String get ledgerConclusionUnverifiedBody =>
      'Khoản chi đã được công bố nhưng còn bước xác minh chưa hoàn tất. Xem chuỗi trách nhiệm bên dưới.';

  @override
  String get ledgerChainTitle => 'Chuỗi trách nhiệm';

  @override
  String get ledgerChainHint =>
      'Mở để xem khoản chi đi từ phản ánh đến xác minh như thế nào';

  @override
  String get ledgerChainReports => 'Phản ánh và lý do';

  @override
  String get ledgerChainWork => 'Công việc đã hoàn thành';

  @override
  String get ledgerChainApprovals => 'Phê duyệt';

  @override
  String get ledgerChainPayment => 'Chứng từ thanh toán';

  @override
  String get ledgerChainVerification => 'Xác minh độc lập';

  @override
  String get ledgerCorrections => 'Điều chỉnh';

  @override
  String get ledgerDocuments => 'Tài liệu (đã che thông tin)';

  @override
  String get ledgerDocumentOpen => 'Xem hoặc tải xuống';

  @override
  String get ledgerDocumentOffline =>
      'Bạn đang ngoại tuyến. Tài liệu chưa được tải. Kết nối mạng rồi thử lại.';

  @override
  String get ledgerDocumentUnauthorized =>
      'Bạn không có quyền mở tài liệu này. Tệp chưa được tải xuống.';

  @override
  String get ledgerDocumentFailure =>
      'Không mở được tài liệu. Tệp chưa được tải xuống; vui lòng thử lại.';

  @override
  String get ledgerProofTitle => 'Chi tiết xác thực';

  @override
  String get ledgerProofHash => 'Mã băm bản ghi';

  @override
  String get ledgerProofEvents => 'Sự kiện đã ký';

  @override
  String get evidenceChain => 'Đã neo trên blockchain';

  @override
  String get evidenceLocal => 'Đã ký — chưa bật neo blockchain';

  @override
  String get evidencePending => 'Đang chờ neo blockchain';

  @override
  String get evidenceMismatch => 'Phát hiện sai lệch dữ liệu';

  @override
  String get integrityVerified => 'Bản ghi đã xác minh';

  @override
  String get integrityMismatch => 'Phát hiện sai lệch toàn vẹn';

  @override
  String get integrityUnavailable => 'Chưa kiểm tra được tính toàn vẹn';

  @override
  String get integrityUnchecked => 'Đã công bố — chưa kiểm tra toàn vẹn';

  @override
  String get accountOccupancies => 'Căn hộ của tôi';

  @override
  String get accountPreferences => 'Thông báo';

  @override
  String get accountPrefEmail => 'Email';

  @override
  String get accountPrefPush => 'Đẩy (push)';

  @override
  String get accountSignOutAll => 'Đăng xuất mọi thiết bị';

  @override
  String get prefReportReceipt => 'Đã nhận phản ánh';

  @override
  String get prefTriageStatus => 'Phản ánh được xem xét';

  @override
  String get prefWorkCompleted => 'Công việc hoàn thành';

  @override
  String get prefLedgerPublication => 'Khoản chi được công bố';

  @override
  String get prefCorrectionStatus => 'Điều chỉnh';
}
