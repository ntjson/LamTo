/// Path prefixes that declare X-LamTo-Occupancy in the OpenAPI schema.
const buildingScopedPathPrefixes = [
  '/api/v1/locations',
  '/api/v1/reports',
  '/api/v1/ledger',
  '/api/v1/notifications',
  '/api/v1/fund',
];

/// True when [path] is a building-scoped endpoint that may receive the header.
bool isBuildingScopedPath(String path) {
  final p = path.startsWith('http') ? Uri.parse(path).path : path;
  return buildingScopedPathPrefixes
      .any((prefix) => p == prefix || p.startsWith('$prefix/'));
}

/// Selected active occupancy id (spec 3.4). Only the occupancy id is ever sent.
class OccupancyHolder {
  int? occupancyId;
}
