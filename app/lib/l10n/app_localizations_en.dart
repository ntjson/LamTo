// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for English (`en`).
class AppLocalizationsEn extends AppLocalizations {
  AppLocalizationsEn([String locale = 'en']) : super(locale);

  @override
  String get appTitle => 'LamTo';

  @override
  String get loginTitle => 'Sign in';

  @override
  String get loginIdentifier => 'Phone or email';

  @override
  String get loginPassword => 'Password';

  @override
  String get loginSubmit => 'Sign in';

  @override
  String get apiBaseUrlTitle => 'API server';

  @override
  String get apiBaseUrlLabel => 'API URL';

  @override
  String get apiBaseUrlHelp =>
      'Paste your Cloudflare tunnel URL (https://….trycloudflare.com). No APK rebuild needed when the tunnel changes. Saving signs you out.';

  @override
  String get apiBaseUrlSave => 'Save URL';

  @override
  String get apiBaseUrlReset => 'Default';

  @override
  String get apiBaseUrlInvalid => 'Invalid URL. Use https://… or http://…';

  @override
  String get apiBaseUrlSaved => 'Server URL saved.';

  @override
  String get occupancyPickerTitle => 'Choose your home';

  @override
  String get bootstrapRetry => 'Retry';

  @override
  String get signOut => 'Sign out';

  @override
  String get noOccupancyTitle => 'No home linked';

  @override
  String get noOccupancyBody =>
      'Your account is signed in, but no apartment is linked yet. Contact your building management, or sign out and try another account.';

  @override
  String get errAuthFailed =>
      'The phone/email or password is incorrect. Nothing was submitted. Please try again.';

  @override
  String get errThrottled =>
      'Too many attempts. Nothing was submitted. Please wait a few minutes and try again.';

  @override
  String get errOccupancyRequired =>
      'Please choose which home this applies to.';

  @override
  String get errNetwork =>
      'No connection. Your action was not sent. Check your network and retry.';

  @override
  String get errServer =>
      'Something went wrong on our side. Your action may not have been saved. Please try again shortly.';

  @override
  String get errGeneric => 'Something went wrong. Please try again.';

  @override
  String get tabHome => 'Home';

  @override
  String get tabReport => 'Report';

  @override
  String get tabIssues => 'Issues';

  @override
  String get tabLedger => 'Ledger';

  @override
  String get tabAccount => 'Account';

  @override
  String get locationPickerTitle => 'Where is the issue?';

  @override
  String get locationChooseHere => 'Choose this area';

  @override
  String get commonRetry => 'Try again';

  @override
  String get reportFormTitle => 'Report an issue';

  @override
  String get reportTextLabel => 'What happened?';

  @override
  String get reportLocationLabel => 'Location';

  @override
  String get reportLocationEmpty => 'Choose a location';

  @override
  String reportPhotosLabel(int max) {
    return 'Photos (up to $max)';
  }

  @override
  String get reportAddPhoto => 'Add photo';

  @override
  String get reportPhotoCamera => 'Take a photo';

  @override
  String get reportPhotoGallery => 'Choose from gallery';

  @override
  String get reportSubmit => 'Send report';

  @override
  String get reportSubmitted => 'Your report was received.';

  @override
  String get reportPhotosPending =>
      'Some photos did not upload. Your report text is saved — retry each photo below.';

  @override
  String get reportPhotoRetry => 'Retry';

  @override
  String get reportConflict =>
      'This report was already sent. Your edits will be sent as a new report — tap Send again.';

  @override
  String get reportMissingFields =>
      'Please describe the issue and choose a location. Nothing was sent yet.';

  @override
  String get reportViewIssue => 'View this issue';

  @override
  String get reportAnother => 'Report another issue';

  @override
  String get issuesTitle => 'My issues';

  @override
  String get issuesEmpty => 'You have not reported any issues yet.';

  @override
  String get issuesLoadMore => 'Load more';

  @override
  String get statusOpen => 'Open';

  @override
  String get statusResolved => 'Resolved';

  @override
  String get timelineSubmitted => 'Report submitted';

  @override
  String get timelineTriagePending => 'Waiting for staff review';

  @override
  String get timelineTriageDone => 'Reviewed by staff';

  @override
  String timelineCase(String category) {
    return 'Grouped into case: $category';
  }

  @override
  String timelineWork(String status, String deadline) {
    return 'Work order $status, deadline $deadline';
  }

  @override
  String get timelineCompleted => 'Work completed';

  @override
  String get rateWorkCta => 'Rate this work';

  @override
  String get rateWorkTitle => 'How was the work?';

  @override
  String get rateCommentLabel => 'Comment (optional)';

  @override
  String get rateSubmit => 'Send rating';

  @override
  String get rateThanks => 'Thank you for your rating.';

  @override
  String get workStatusAssigned => 'Assigned';

  @override
  String get workStatusInProgress => 'In progress';

  @override
  String get workStatusAwaiting => 'Awaiting acceptance';

  @override
  String get workStatusAccepted => 'Accepted';

  @override
  String get workStatusClosed => 'Closed';

  @override
  String get workStatusCancelled => 'Cancelled';

  @override
  String get homeFundTitle => 'Maintenance fund';

  @override
  String get homeFundInflows => 'In (30d)';

  @override
  String get homeFundOutflows => 'Out (30d)';

  @override
  String get homeActiveReports => 'My open reports';

  @override
  String get homeRecentSpending => 'Recently published spending';

  @override
  String get homeNoActiveReports => 'No open reports.';

  @override
  String get homeNoSpending => 'No published spending yet.';

  @override
  String get notificationsTitle => 'Notifications';

  @override
  String get notificationsEmpty => 'No notifications yet.';

  @override
  String get notificationsLoadMore => 'Load more';

  @override
  String get ledgerTitle => 'Building ledger';

  @override
  String get ledgerEmpty => 'No published spending for this period.';

  @override
  String get ledgerAllTime => 'All';

  @override
  String get ledgerLoadMore => 'Load more';

  @override
  String ledgerPublishedOn(String date) {
    return 'Published $date';
  }

  @override
  String get ledgerAmount => 'Amount';

  @override
  String get ledgerContractor => 'Contractor';

  @override
  String get ledgerWhatFixed => 'What was fixed';

  @override
  String get ledgerWhy => 'Why';

  @override
  String get ledgerApprovers => 'Approved by';

  @override
  String ledgerApproverBoard(String name) {
    return 'Board: $name';
  }

  @override
  String ledgerApproverRep(String name) {
    return 'Resident representative: $name';
  }

  @override
  String ledgerApproverEmergency(String name) {
    return 'Emergency authorization: $name';
  }

  @override
  String ledgerApproverGeneric(String name) {
    return '$name';
  }

  @override
  String ledgerVerifiedBy(String name) {
    return 'Payment verified by $name';
  }

  @override
  String get ledgerNotVerified => 'Payment not yet verified';

  @override
  String get ledgerCorrections => 'Corrections';

  @override
  String get ledgerDocuments => 'Redacted documents';

  @override
  String get ledgerProofTitle => 'Verification details';

  @override
  String get ledgerProofHash => 'Record hash';

  @override
  String get ledgerProofEvents => 'Signed events';

  @override
  String get evidenceChain => 'Anchored on the blockchain';

  @override
  String get evidenceLocal =>
      'Signed and hash-locked — blockchain anchoring is off for this deployment';

  @override
  String get evidencePending => 'Waiting for blockchain anchoring';

  @override
  String get evidenceMismatch => 'Data mismatch detected';

  @override
  String get integrityVerified => 'Record verified';

  @override
  String get integrityMismatch => 'Integrity mismatch detected';

  @override
  String get integrityUnavailable => 'Integrity check unavailable';

  @override
  String get integrityUnchecked => 'Published — integrity not yet checked';

  @override
  String get accountOccupancies => 'My homes';

  @override
  String get accountPreferences => 'Notifications';

  @override
  String get accountPrefEmail => 'Email';

  @override
  String get accountPrefPush => 'Push';

  @override
  String get accountSignOutAll => 'Sign out of all devices';

  @override
  String get prefReportReceipt => 'Report received';

  @override
  String get prefTriageStatus => 'Report reviewed';

  @override
  String get prefWorkCompleted => 'Work completed';

  @override
  String get prefLedgerPublication => 'Published spending';

  @override
  String get prefCorrectionStatus => 'Corrections';
}
