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
}
