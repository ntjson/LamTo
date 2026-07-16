import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/intl.dart' as intl;

import 'app_localizations_en.dart';
import 'app_localizations_vi.dart';

// ignore_for_file: type=lint

/// Callers can lookup localized strings with an instance of AppLocalizations
/// returned by `AppLocalizations.of(context)`.
///
/// Applications need to include `AppLocalizations.delegate()` in their app's
/// `localizationDelegates` list, and the locales they support in the app's
/// `supportedLocales` list. For example:
///
/// ```dart
/// import 'l10n/app_localizations.dart';
///
/// return MaterialApp(
///   localizationsDelegates: AppLocalizations.localizationsDelegates,
///   supportedLocales: AppLocalizations.supportedLocales,
///   home: MyApplicationHome(),
/// );
/// ```
///
/// ## Update pubspec.yaml
///
/// Please make sure to update your pubspec.yaml to include the following
/// packages:
///
/// ```yaml
/// dependencies:
///   # Internationalization support.
///   flutter_localizations:
///     sdk: flutter
///   intl: any # Use the pinned version from flutter_localizations
///
///   # Rest of dependencies
/// ```
///
/// ## iOS Applications
///
/// iOS applications define key application metadata, including supported
/// locales, in an Info.plist file that is built into the application bundle.
/// To configure the locales supported by your app, you’ll need to edit this
/// file.
///
/// First, open your project’s ios/Runner.xcworkspace Xcode workspace file.
/// Then, in the Project Navigator, open the Info.plist file under the Runner
/// project’s Runner folder.
///
/// Next, select the Information Property List item, select Add Item from the
/// Editor menu, then select Localizations from the pop-up menu.
///
/// Select and expand the newly-created Localizations item then, for each
/// locale your application supports, add a new item and select the locale
/// you wish to add from the pop-up menu in the Value field. This list should
/// be consistent with the languages listed in the AppLocalizations.supportedLocales
/// property.
abstract class AppLocalizations {
  AppLocalizations(String locale)
    : localeName = intl.Intl.canonicalizedLocale(locale.toString());

  final String localeName;

  static AppLocalizations? of(BuildContext context) {
    return Localizations.of<AppLocalizations>(context, AppLocalizations);
  }

  static const LocalizationsDelegate<AppLocalizations> delegate =
      _AppLocalizationsDelegate();

  /// A list of this localizations delegate along with the default localizations
  /// delegates.
  ///
  /// Returns a list of localizations delegates containing this delegate along with
  /// GlobalMaterialLocalizations.delegate, GlobalCupertinoLocalizations.delegate,
  /// and GlobalWidgetsLocalizations.delegate.
  ///
  /// Additional delegates can be added by appending to this list in
  /// MaterialApp. This list does not have to be used at all if a custom list
  /// of delegates is preferred or required.
  static const List<LocalizationsDelegate<dynamic>> localizationsDelegates =
      <LocalizationsDelegate<dynamic>>[
        delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
      ];

  /// A list of this localizations delegate's supported locales.
  static const List<Locale> supportedLocales = <Locale>[
    Locale('en'),
    Locale('vi'),
  ];

  /// No description provided for @appTitle.
  ///
  /// In en, this message translates to:
  /// **'LamTo'**
  String get appTitle;

  /// No description provided for @loginTitle.
  ///
  /// In en, this message translates to:
  /// **'Sign in'**
  String get loginTitle;

  /// No description provided for @loginIdentifier.
  ///
  /// In en, this message translates to:
  /// **'Phone or email'**
  String get loginIdentifier;

  /// No description provided for @loginPassword.
  ///
  /// In en, this message translates to:
  /// **'Password'**
  String get loginPassword;

  /// No description provided for @loginSubmit.
  ///
  /// In en, this message translates to:
  /// **'Sign in'**
  String get loginSubmit;

  /// No description provided for @occupancyPickerTitle.
  ///
  /// In en, this message translates to:
  /// **'Choose your home'**
  String get occupancyPickerTitle;

  /// No description provided for @bootstrapRetry.
  ///
  /// In en, this message translates to:
  /// **'Retry'**
  String get bootstrapRetry;

  /// No description provided for @signOut.
  ///
  /// In en, this message translates to:
  /// **'Sign out'**
  String get signOut;

  /// No description provided for @noOccupancyTitle.
  ///
  /// In en, this message translates to:
  /// **'No home linked'**
  String get noOccupancyTitle;

  /// No description provided for @noOccupancyBody.
  ///
  /// In en, this message translates to:
  /// **'Your account is signed in, but no apartment is linked yet. Contact your building management, or sign out and try another account.'**
  String get noOccupancyBody;

  /// No description provided for @errAuthFailed.
  ///
  /// In en, this message translates to:
  /// **'The phone/email or password is incorrect. Nothing was submitted. Please try again.'**
  String get errAuthFailed;

  /// No description provided for @errThrottled.
  ///
  /// In en, this message translates to:
  /// **'Too many attempts. Nothing was submitted. Please wait a few minutes and try again.'**
  String get errThrottled;

  /// No description provided for @errOccupancyRequired.
  ///
  /// In en, this message translates to:
  /// **'Please choose which home this applies to.'**
  String get errOccupancyRequired;

  /// No description provided for @errNetwork.
  ///
  /// In en, this message translates to:
  /// **'No connection. Your action was not sent. Check your network and retry.'**
  String get errNetwork;

  /// No description provided for @errServer.
  ///
  /// In en, this message translates to:
  /// **'Something went wrong on our side. Your action may not have been saved. Please try again shortly.'**
  String get errServer;

  /// No description provided for @errGeneric.
  ///
  /// In en, this message translates to:
  /// **'Something went wrong. Please try again.'**
  String get errGeneric;

  /// No description provided for @tabHome.
  ///
  /// In en, this message translates to:
  /// **'Home'**
  String get tabHome;

  /// No description provided for @tabReport.
  ///
  /// In en, this message translates to:
  /// **'Report'**
  String get tabReport;

  /// No description provided for @tabIssues.
  ///
  /// In en, this message translates to:
  /// **'Issues'**
  String get tabIssues;

  /// No description provided for @tabLedger.
  ///
  /// In en, this message translates to:
  /// **'Ledger'**
  String get tabLedger;

  /// No description provided for @tabAccount.
  ///
  /// In en, this message translates to:
  /// **'Account'**
  String get tabAccount;

  /// No description provided for @locationPickerTitle.
  ///
  /// In en, this message translates to:
  /// **'Where is the issue?'**
  String get locationPickerTitle;

  /// No description provided for @locationChooseHere.
  ///
  /// In en, this message translates to:
  /// **'Choose this area'**
  String get locationChooseHere;

  /// No description provided for @commonRetry.
  ///
  /// In en, this message translates to:
  /// **'Try again'**
  String get commonRetry;

  /// No description provided for @reportFormTitle.
  ///
  /// In en, this message translates to:
  /// **'Report an issue'**
  String get reportFormTitle;

  /// No description provided for @reportTextLabel.
  ///
  /// In en, this message translates to:
  /// **'What happened?'**
  String get reportTextLabel;

  /// No description provided for @reportLocationLabel.
  ///
  /// In en, this message translates to:
  /// **'Location'**
  String get reportLocationLabel;

  /// No description provided for @reportLocationEmpty.
  ///
  /// In en, this message translates to:
  /// **'Choose a location'**
  String get reportLocationEmpty;

  /// No description provided for @reportPhotosLabel.
  ///
  /// In en, this message translates to:
  /// **'Photos (up to {max})'**
  String reportPhotosLabel(int max);

  /// No description provided for @reportAddPhoto.
  ///
  /// In en, this message translates to:
  /// **'Add photo'**
  String get reportAddPhoto;

  /// No description provided for @reportPhotoCamera.
  ///
  /// In en, this message translates to:
  /// **'Take a photo'**
  String get reportPhotoCamera;

  /// No description provided for @reportPhotoGallery.
  ///
  /// In en, this message translates to:
  /// **'Choose from gallery'**
  String get reportPhotoGallery;

  /// No description provided for @reportSubmit.
  ///
  /// In en, this message translates to:
  /// **'Send report'**
  String get reportSubmit;

  /// No description provided for @reportSubmitted.
  ///
  /// In en, this message translates to:
  /// **'Your report was received.'**
  String get reportSubmitted;

  /// No description provided for @reportPhotosPending.
  ///
  /// In en, this message translates to:
  /// **'Some photos did not upload. Your report text is saved — retry each photo below.'**
  String get reportPhotosPending;

  /// No description provided for @reportPhotoRetry.
  ///
  /// In en, this message translates to:
  /// **'Retry'**
  String get reportPhotoRetry;

  /// No description provided for @reportConflict.
  ///
  /// In en, this message translates to:
  /// **'This report was already sent. Your edits will be sent as a new report — tap Send again.'**
  String get reportConflict;

  /// No description provided for @reportMissingFields.
  ///
  /// In en, this message translates to:
  /// **'Please describe the issue and choose a location. Nothing was sent yet.'**
  String get reportMissingFields;

  /// No description provided for @reportViewIssue.
  ///
  /// In en, this message translates to:
  /// **'View this issue'**
  String get reportViewIssue;

  /// No description provided for @reportAnother.
  ///
  /// In en, this message translates to:
  /// **'Report another issue'**
  String get reportAnother;

  /// No description provided for @issuesTitle.
  ///
  /// In en, this message translates to:
  /// **'My issues'**
  String get issuesTitle;

  /// No description provided for @issuesEmpty.
  ///
  /// In en, this message translates to:
  /// **'You have not reported any issues yet.'**
  String get issuesEmpty;

  /// No description provided for @issuesLoadMore.
  ///
  /// In en, this message translates to:
  /// **'Load more'**
  String get issuesLoadMore;

  /// No description provided for @statusOpen.
  ///
  /// In en, this message translates to:
  /// **'Open'**
  String get statusOpen;

  /// No description provided for @statusResolved.
  ///
  /// In en, this message translates to:
  /// **'Resolved'**
  String get statusResolved;

  /// No description provided for @timelineSubmitted.
  ///
  /// In en, this message translates to:
  /// **'Report submitted'**
  String get timelineSubmitted;

  /// No description provided for @timelineTriagePending.
  ///
  /// In en, this message translates to:
  /// **'Waiting for staff review'**
  String get timelineTriagePending;

  /// No description provided for @timelineTriageDone.
  ///
  /// In en, this message translates to:
  /// **'Reviewed by staff'**
  String get timelineTriageDone;

  /// No description provided for @timelineCase.
  ///
  /// In en, this message translates to:
  /// **'Grouped into case: {category}'**
  String timelineCase(String category);

  /// No description provided for @timelineWork.
  ///
  /// In en, this message translates to:
  /// **'Work order {status}, deadline {deadline}'**
  String timelineWork(String status, String deadline);

  /// No description provided for @timelineCompleted.
  ///
  /// In en, this message translates to:
  /// **'Work completed'**
  String get timelineCompleted;

  /// No description provided for @rateWorkCta.
  ///
  /// In en, this message translates to:
  /// **'Rate this work'**
  String get rateWorkCta;

  /// No description provided for @rateWorkTitle.
  ///
  /// In en, this message translates to:
  /// **'How was the work?'**
  String get rateWorkTitle;

  /// No description provided for @rateCommentLabel.
  ///
  /// In en, this message translates to:
  /// **'Comment (optional)'**
  String get rateCommentLabel;

  /// No description provided for @rateSubmit.
  ///
  /// In en, this message translates to:
  /// **'Send rating'**
  String get rateSubmit;

  /// No description provided for @rateThanks.
  ///
  /// In en, this message translates to:
  /// **'Thank you for your rating.'**
  String get rateThanks;

  /// No description provided for @workStatusAssigned.
  ///
  /// In en, this message translates to:
  /// **'Assigned'**
  String get workStatusAssigned;

  /// No description provided for @workStatusInProgress.
  ///
  /// In en, this message translates to:
  /// **'In progress'**
  String get workStatusInProgress;

  /// No description provided for @workStatusAwaiting.
  ///
  /// In en, this message translates to:
  /// **'Awaiting acceptance'**
  String get workStatusAwaiting;

  /// No description provided for @workStatusAccepted.
  ///
  /// In en, this message translates to:
  /// **'Accepted'**
  String get workStatusAccepted;

  /// No description provided for @workStatusClosed.
  ///
  /// In en, this message translates to:
  /// **'Closed'**
  String get workStatusClosed;

  /// No description provided for @workStatusCancelled.
  ///
  /// In en, this message translates to:
  /// **'Cancelled'**
  String get workStatusCancelled;
}

class _AppLocalizationsDelegate
    extends LocalizationsDelegate<AppLocalizations> {
  const _AppLocalizationsDelegate();

  @override
  Future<AppLocalizations> load(Locale locale) {
    return SynchronousFuture<AppLocalizations>(lookupAppLocalizations(locale));
  }

  @override
  bool isSupported(Locale locale) =>
      <String>['en', 'vi'].contains(locale.languageCode);

  @override
  bool shouldReload(_AppLocalizationsDelegate old) => false;
}

AppLocalizations lookupAppLocalizations(Locale locale) {
  // Lookup logic when only language code is specified.
  switch (locale.languageCode) {
    case 'en':
      return AppLocalizationsEn();
    case 'vi':
      return AppLocalizationsVi();
  }

  throw FlutterError(
    'AppLocalizations.delegate failed to load unsupported locale "$locale". This is likely '
    'an issue with the localizations generation tool. Please file an issue '
    'on GitHub with a reproducible sample app and the gen-l10n configuration '
    'that was used.',
  );
}
