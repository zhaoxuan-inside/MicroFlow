/// State model (§11): layered scopes with explicit ownership.
///
/// Component state is private to component instances; page state dies with
/// the page instance; session state is owned by product runtime; persistent
/// state declares version-migration; derived state is never a second source
/// of truth. The store only exposes declared members.
library;

class MFStateStore {
  MFStateStore();

  final Map<String, Map<String, Object?>> _layers = {};

  static const scopes = ['component', 'page', 'session', 'product', 'persistent'];

  /// Read a member without adding to an active layer.
  Object? peek(String scope, String path) {
    final parts = path.isEmpty ? const <String>[] : path.split('.');
    final key = parts.isEmpty || parts.first.isEmpty ? null : parts.first;
    if (key == null) return _layers[scope];
    final layer = _layers[scope];
    if (layer == null) return null;
    Object? cur = layer[key];
    for (final p in parts.skip(1)) {
      if (cur is Map) {
        cur = cur[p];
      } else {
        return null;
      }
    }
    return cur;
  }

  void write(String scope, String member, Object? value) {
    final layer = _layers.putIfAbsent(scope, () => {});
    layer[member] = value;
  }

  void writeDeep(String scope, String path, Object? value) {
    final parts = path.split('.');
    if (parts.isEmpty || parts.first.isEmpty) {
      return;
    }
    if (parts.length == 1) {
      write(scope, path, value);
      return;
    }
    final layer = _layers.putIfAbsent(scope, () => {});
    final existing = (layer[parts.first] as Map?)?.cast<String, Object?>() ?? <String, Object?>{};
    Map<String, Object?> cur = existing;
    for (final p in parts.skip(1).take(parts.length - 2)) {
      final child = (cur[p] as Map?)?.cast<String, Object?>() ?? <String, Object?>{};
      cur[p] = child;
      cur = child;
    }
    cur[parts.last] = value;
    layer[parts.first] = existing;
  }

  /// Component-instance-scoped layer, keyed by instance id to guarantee two
  /// instances of one definition never share state (§2.6, baseline 1).
  Map<String, Object?> componentState(String componentInstanceId) =>
      _layers.putIfAbsent('component|$componentInstanceId', () => {});

  Map<String, Object?> pageState() => _layers.putIfAbsent('page', () => {});

  void dropPage() => _layers.remove('page');

  Map<String, Object?> snapshotSession() => Map.of(_layers['session'] ?? const {});

  void restoreSession(Map<String, Object?> snapshot) {
    _layers['session'] = Map.of(snapshot);
  }
}
