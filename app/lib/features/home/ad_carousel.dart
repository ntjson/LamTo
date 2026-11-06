import 'dart:async';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../l10n/app_localizations.dart';
import 'home_ads.dart';

/// The Home ad carousel: swipeable, and advancing on its own while the
/// resident leaves it alone.
///
/// A touch pauses it; [interval] after the last touch it moves on again. It
/// stops at the last slide rather than wrapping, and never moves on its own
/// with reduced motion or a screen reader on, in the background, or on a
/// tab that is not showing. Renders nothing when there are no ads.
class AdCarousel extends StatefulWidget {
  const AdCarousel({
    required this.ads,
    this.interval = const Duration(seconds: 5),
    super.key,
  });

  final List<HomeAd> ads;
  final Duration interval;

  @override
  State<AdCarousel> createState() => _AdCarouselState();
}

class _AdCarouselState extends State<AdCarousel> with WidgetsBindingObserver {
  final _controller = PageController(viewportFraction: 0.88);
  Timer? _timer;
  int _page = 0;
  bool _held = false;
  bool _foreground = true;
  bool _still = false;
  bool _tickerOn = true;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _still =
        MediaQuery.disableAnimationsOf(context) ||
        MediaQuery.accessibleNavigationOf(context);
    _tickerOn = TickerMode.valuesOf(context).enabled;
    _schedule();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _foreground = state == AppLifecycleState.resumed;
    _schedule();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _timer?.cancel();
    _controller.dispose();
    super.dispose();
  }

  bool get _mayAdvance =>
      mounted &&
      _foreground &&
      _tickerOn &&
      !_held &&
      !_still &&
      _page < widget.ads.length - 1;

  void _schedule() {
    _timer?.cancel();
    if (!_mayAdvance) return;
    _timer = Timer(widget.interval, () {
      if (!_mayAdvance || !_controller.hasClients) return;
      _controller.animateToPage(
        _page + 1,
        duration: const Duration(milliseconds: 450),
        curve: Curves.easeOutCubic,
      );
    });
  }

  void _hold(bool held) {
    _held = held;
    _schedule();
  }

  @override
  Widget build(BuildContext context) {
    if (widget.ads.isEmpty) return const SizedBox.shrink();
    final l10n = AppLocalizations.of(context)!;
    final theme = Theme.of(context);
    return Semantics(
      container: true,
      label: l10n.homeAdsLabel,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Listener(
            onPointerDown: (_) => _hold(true),
            onPointerUp: (_) => _hold(false),
            onPointerCancel: (_) => _hold(false),
            child: LayoutBuilder(
              builder: (context, constraints) => SizedBox(
                // 2:1 slides at the page's viewport fraction.
                height: constraints.maxWidth * 0.88 / 2,
                child: PageView.builder(
                  controller: _controller,
                  itemCount: widget.ads.length,
                  onPageChanged: (page) {
                    setState(() => _page = page);
                    _schedule();
                  },
                  itemBuilder: (context, i) => Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 6),
                    child: _AdSlide(ad: widget.ads[i]),
                  ),
                ),
              ),
            ),
          ),
          const SizedBox(height: 10),
          ExcludeSemantics(
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                for (var i = 0; i < widget.ads.length; i++)
                  AnimatedContainer(
                    duration: const Duration(milliseconds: 250),
                    margin: const EdgeInsets.symmetric(horizontal: 3),
                    width: i == _page ? 18 : 6,
                    height: 6,
                    decoration: BoxDecoration(
                      color: i == _page
                          ? theme.colorScheme.primary
                          : theme.colorScheme.primary.withValues(alpha: 0.25),
                      borderRadius: BorderRadius.circular(3),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _AdSlide extends StatelessWidget {
  const _AdSlide({required this.ad});

  final HomeAd ad;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final text = Theme.of(context).textTheme;
    final link = ad.link;
    const white = Color(0xFFFFFFFF);
    return Semantics(
      label: l10n.homeAdSemantics(ad.advertiser, ad.title),
      button: link != null,
      excludeSemantics: true,
      child: Material(
        clipBehavior: Clip.antiAlias,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
        child: InkWell(
          onTap: link == null
              ? null
              : () => launchUrl(link, mode: LaunchMode.externalApplication),
          child: Ink(
            decoration: BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: ad.colors,
              ),
            ),
            // The slide stands in for an advertiser's finished image, and an
            // image does not grow with the system text size. The semantics
            // label above carries the text for whoever needs it larger.
            child: MediaQuery.withNoTextScaling(
              child: Stack(
                children: [
                  Positioned(
                    right: -18,
                    bottom: -22,
                    child: Icon(
                      ad.icon,
                      size: 150,
                      color: white.withValues(alpha: 0.18),
                    ),
                  ),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          ad.advertiser.toUpperCase(),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: text.labelSmall?.copyWith(
                            color: white.withValues(alpha: 0.85),
                            fontWeight: FontWeight.w700,
                            letterSpacing: 0.6,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          ad.title,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: text.titleLarge?.copyWith(
                            color: white,
                            fontWeight: FontWeight.w800,
                            height: 1.15,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          ad.subtitle,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: text.bodySmall?.copyWith(
                            color: white.withValues(alpha: 0.9),
                          ),
                        ),
                        const Spacer(),
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 10,
                            vertical: 4,
                          ),
                          decoration: BoxDecoration(
                            color: white,
                            borderRadius: BorderRadius.circular(999),
                          ),
                          child: Text(
                            ad.offer,
                            style: text.labelMedium?.copyWith(
                              color: ad.colors.first,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  // Disclosure the creative cannot cover.
                  Positioned(
                    top: 10,
                    right: 10,
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 7,
                        vertical: 2,
                      ),
                      decoration: BoxDecoration(
                        color: const Color(0x73000000),
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Text(
                        l10n.homeAdTag,
                        style: text.labelSmall?.copyWith(
                          color: white,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
