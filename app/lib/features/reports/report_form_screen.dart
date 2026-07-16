import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/failure.dart';
import '../../core/providers.dart';
import '../../l10n/app_localizations.dart';
import 'issue_detail_screen.dart';
import 'location_picker_screen.dart';
import 'my_issues_screen.dart';
import 'report_draft.dart';
import 'report_submitter.dart';
import 'reports_repository.dart';

const maxReportPhotos = 5; // spec 6.3
const _maxPhotoEdge = 2048.0; // spec 6.3: client-side max edge before upload
const _photoQuality = 85;
const _autosaveDebounce = Duration(milliseconds: 300);

/// Spec 6.3 report compose: required text + location, ≤5 photos, draft
/// autosave/restore, submit through [ReportSubmitter], per-photo retry.
///
/// After [createReport] succeeds the form enters **committed-result**
/// (plan amendment 11): primary Send is hidden; only photo-retry and
/// "view issue" remain. Photos are imported into app-owned storage before
/// draft persistence (amendment 8); text autosave is debounced (amendment 9).
class ReportFormScreen extends ConsumerStatefulWidget {
  const ReportFormScreen({super.key});

  @override
  ConsumerState<ReportFormScreen> createState() => _ReportFormScreenState();
}

class _ReportFormScreenState extends ConsumerState<ReportFormScreen> {
  final _text = TextEditingController();
  final _picker = ImagePicker();
  ReportDraft _draft = ReportDraft.fresh();
  bool _restored = false;
  bool _busy = false;
  String? _notice;
  SubmitOutcome? _outcome;
  Timer? _autosaveTimer;
  Future<void>? _pendingPersist;
  /// Cached for dispose flush — [ref] is unsafe after unmount (Riverpod).
  ReportDraftStore? _draftStore;
  int? _cachedOccupancyId;

  /// True once create succeeded — no whole-report resubmit (amendment 11).
  bool get _committed => _outcome != null;

  int get _occupancyId =>
      _cachedOccupancyId ?? ref.read(occupancyHolderProvider).occupancyId!;

  ReportDraftStore get _store =>
      _draftStore ?? ref.read(reportDraftStoreProvider);

  void _ensureDepsCached() {
    _draftStore ??= ref.read(reportDraftStoreProvider);
    _cachedOccupancyId ??= ref.read(occupancyHolderProvider).occupancyId;
  }

  @override
  void initState() {
    super.initState();
    _text.addListener(_onTextChanged);
    WidgetsBinding.instance.addPostFrameCallback((_) => _restore());
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // Capture store/occupancy early so dispose can flush without [ref].
    _ensureDepsCached();
  }

  @override
  void dispose() {
    _autosaveTimer?.cancel();
    _autosaveTimer = null;
    // Debounce may hold the latest text; persist immediately if still editing.
    // Cannot await in dispose — store serializes writes (last enqueue wins).
    // Use cached deps only (ref is unsafe here).
    final store = _draftStore;
    final occupancyId = _cachedOccupancyId;
    if (!_committed && store != null && occupancyId != null) {
      unawaited(store.write(occupancyId, _draft));
    }
    _text.removeListener(_onTextChanged);
    _text.dispose();
    super.dispose();
  }

  Future<void> _restore() async {
    _ensureDepsCached();
    final occupancyId = _occupancyId;
    final saved = await _store.read(occupancyId);
    if (!mounted) return;
    setState(() {
      if (saved != null) {
        _draft = saved;
        _text.text = saved.text;
      }
      _restored = true;
    });
  }

  void _onTextChanged() {
    if (_committed) return;
    _draft = _draft.copyWith(text: _text.text);
    // Debounce UI-triggered saves (~300ms); store still serializes writes.
    _autosaveTimer?.cancel();
    _autosaveTimer = Timer(_autosaveDebounce, () {
      _pendingPersist = _persist();
    });
  }

  Future<void> _persist() {
    _ensureDepsCached();
    return _store.write(_occupancyId, _draft);
  }

  Future<void> _flushAutosave() async {
    _autosaveTimer?.cancel();
    _autosaveTimer = null;
    final pending = _pendingPersist;
    _pendingPersist = null;
    if (pending != null) {
      try {
        await pending;
      } catch (_) {}
    }
    await _persist();
  }

  Future<void> _pickLocation() async {
    if (_committed || _busy) return;
    final location = await Navigator.push<Location>(
      context,
      MaterialPageRoute(builder: (_) => const LocationPickerScreen()),
    );
    if (location == null) return;
    setState(() {
      _draft = _draft.copyWith(
        locationId: location.id,
        locationLabel: location.name,
      );
    });
    await _persist();
  }

  Future<void> _addPhoto(AppLocalizations l10n) async {
    if (_committed || _busy) return;
    final remaining = maxReportPhotos - _draft.photoPaths.length;
    if (remaining <= 0) return;
    final source = await showModalBottomSheet<ImageSource>(
      context: context,
      builder: (context) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              minTileHeight: 56,
              leading: const Icon(Icons.photo_camera_outlined),
              title: Text(l10n.reportPhotoCamera),
              onTap: () => Navigator.pop(context, ImageSource.camera),
            ),
            ListTile(
              minTileHeight: 56,
              leading: const Icon(Icons.photo_library_outlined),
              title: Text(l10n.reportPhotoGallery),
              onTap: () => Navigator.pop(context, ImageSource.gallery),
            ),
          ],
        ),
      ),
    );
    if (source == null) return;
    // Native downscale to max edge 2048 + JPEG re-encode (spec 6.3).
    final picked = source == ImageSource.gallery
        ? await _picker.pickMultiImage(
            maxWidth: _maxPhotoEdge,
            maxHeight: _maxPhotoEdge,
            imageQuality: _photoQuality,
          )
        : [
            await _picker.pickImage(
              source: ImageSource.camera,
              maxWidth: _maxPhotoEdge,
              maxHeight: _maxPhotoEdge,
              imageQuality: _photoQuality,
            ),
          ].nonNulls.toList();
    if (picked.isEmpty) return;

    // Amendment 8: copy into app-owned durable storage before draft paths.
    final photoStore = ref.read(reportPhotoFileStoreProvider);
    final owned = <String>[];
    for (final xfile in picked.take(remaining)) {
      final path = await photoStore.importPickerPath(
        occupancyId: _occupancyId,
        sourcePath: xfile.path,
      );
      owned.add(path);
    }
    if (!mounted) return;
    setState(() {
      _draft = _draft.copyWith(photoPaths: [
        ..._draft.photoPaths,
        ...owned,
      ]);
    });
    await _persist();
  }

  Future<void> _removePhoto(String path) async {
    if (_committed || _busy) return;
    setState(() {
      _draft = _draft.copyWith(
        photoPaths: _draft.photoPaths.where((p) => p != path).toList(),
      );
    });
    await ref.read(reportPhotoFileStoreProvider).deletePaths([path]);
    await _persist();
  }

  Future<void> _submit(AppLocalizations l10n) async {
    if (_committed || _busy) return;
    if (_draft.text.trim().isEmpty || _draft.locationId == null) {
      setState(() => _notice = l10n.reportMissingFields);
      return;
    }
    await _flushAutosave();
    setState(() {
      _busy = true;
      _notice = null;
    });
    final photoPathsSnapshot = List<String>.from(_draft.photoPaths);
    try {
      final outcome = await ref
          .read(reportSubmitterProvider)
          .submit(draft: _draft, occupancyId: _occupancyId);
      if (!mounted) return;
      // Draft already cleared by submitter on text commit. Drop owned files
      // that uploaded successfully; keep failed paths for retry UI.
      final uploaded = outcome.photos
          .where((p) => p.status == PhotoUploadStatus.uploaded)
          .map((p) => p.path);
      await ref.read(reportPhotoFileStoreProvider).deletePaths(uploaded);
      if (!mounted) return;
      // User-global my-issues list should show the new report (amendment 12).
      ref.invalidate(myReportsProvider);
      setState(() {
        _outcome = outcome;
        _notice = outcome.allPhotosUploaded
            ? l10n.reportSubmitted
            : l10n.reportPhotosPending;
        // Committed-result: leave fields as-is but hide Send (amendment 11).
        if (outcome.allPhotosUploaded) {
          unawaited(
            ref
                .read(reportPhotoFileStoreProvider)
                .deletePaths(photoPathsSnapshot),
          );
        }
      });
    } on ReportConflictException {
      // Already submitted with different content: mint a fresh ref so the
      // edited draft becomes a NEW report on the next send (spec 3.5).
      _draft = _draft.copyWith(clientRef: ReportDraft.fresh().clientRef);
      await _persist();
      if (mounted) setState(() => _notice = l10n.reportConflict);
    } catch (e) {
      if (mounted) {
        setState(() => _notice = failureMessage(
              e is Failure ? e : Failure.fromObject(e),
              l10n,
            ));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _retryPhoto(PhotoUpload photo, AppLocalizations l10n) async {
    final outcome = _outcome;
    if (outcome == null) return;
    await ref
        .read(reportSubmitterProvider)
        .retryPhoto(reportId: outcome.reportId, photo: photo);
    if (!mounted) return;
    if (photo.status == PhotoUploadStatus.uploaded) {
      await ref.read(reportPhotoFileStoreProvider).deletePaths([photo.path]);
    }
    if (!mounted) return;
    setState(() {
      // Stay in committed-result; never re-enable whole-report Send.
      if (outcome.allPhotosUploaded) {
        _notice = l10n.reportSubmitted;
      }
    });
  }

  void _openIssueDetail() {
    final outcome = _outcome;
    if (outcome == null) return;
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => IssueDetailScreen(reportId: outcome.reportId),
      ),
    );
  }

  /// Start a new compose after a successful create (committed-result secondary).
  void _startAnotherReport() {
    _autosaveTimer?.cancel();
    _autosaveTimer = null;
    final fresh = ReportDraft.fresh();
    setState(() {
      _outcome = null;
      _notice = null;
      _draft = fresh;
      // Listener copies empty text onto the fresh draft and schedules autosave.
      _text.text = '';
    });
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    if (!_restored) {
      return const Center(child: CircularProgressIndicator.adaptive());
    }
    final failedPhotos = _outcome?.photos
            .where((p) => p.status == PhotoUploadStatus.failed)
            .toList() ??
        const <PhotoUpload>[];
    final editingLocked = _busy || _committed;
    // Body-only: shell owns Scaffold/CupertinoPageScaffold chrome (no nested
    // AppBar). Material provides ink/TextField surface without a second scaffold.
    return Material(
      color: Theme.of(context).scaffoldBackgroundColor,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(
            l10n.reportFormTitle,
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _text,
            maxLines: 4,
            enabled: !editingLocked,
            decoration: InputDecoration(labelText: l10n.reportTextLabel),
          ),
          const SizedBox(height: 12),
          ListTile(
            minTileHeight: 56,
            shape: RoundedRectangleBorder(
              side: BorderSide(color: Theme.of(context).dividerColor),
              borderRadius: BorderRadius.circular(10),
            ),
            leading: const Icon(Icons.place_outlined),
            title: Text(
              _draft.locationLabel.isEmpty
                  ? l10n.reportLocationEmpty
                  : _draft.locationLabel,
            ),
            trailing: const Icon(Icons.chevron_right),
            onTap: editingLocked ? null : _pickLocation,
          ),
          const SizedBox(height: 16),
          Text(l10n.reportPhotosLabel(maxReportPhotos)),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final path in _draft.photoPaths)
                InputChip(
                  label: Text(path.split('/').last,
                      overflow: TextOverflow.ellipsis),
                  onDeleted: editingLocked ? null : () => _removePhoto(path),
                ),
              if (!_committed && _draft.photoPaths.length < maxReportPhotos)
                ActionChip(
                  avatar: const Icon(Icons.add_a_photo_outlined, size: 20),
                  label: Text(l10n.reportAddPhoto),
                  // ≥48dp touch target (spec §6.2/§6.4).
                  materialTapTargetSize: MaterialTapTargetSize.padded,
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 12),
                  onPressed: _busy ? null : () => _addPhoto(l10n),
                ),
            ],
          ),
          if (_notice != null) ...[
            const SizedBox(height: 16),
            Text(_notice!, style: Theme.of(context).textTheme.bodyMedium),
          ],
          for (final photo in failedPhotos)
            ListTile(
              minTileHeight: 48,
              leading: const Icon(Icons.error_outline),
              title: Text(photo.filename, overflow: TextOverflow.ellipsis),
              trailing: TextButton(
                onPressed: () => _retryPhoto(photo, l10n),
                child: Text(l10n.reportPhotoRetry),
              ),
            ),
          if (_committed) ...[
            const SizedBox(height: 16),
            TextButton(
              style: TextButton.styleFrom(
                minimumSize: const Size.fromHeight(48),
              ),
              onPressed: _openIssueDetail,
              child: Text(l10n.reportViewIssue),
            ),
            TextButton(
              style: TextButton.styleFrom(
                minimumSize: const Size.fromHeight(48),
              ),
              onPressed: _startAnotherReport,
              child: Text(l10n.reportAnother),
            ),
          ],
          if (!_committed) ...[
            const SizedBox(height: 24),
            FilledButton(
              onPressed: _busy ? null : () => _submit(l10n),
              child: Text(l10n.reportSubmit),
            ),
          ],
        ],
      ),
    );
  }
}
