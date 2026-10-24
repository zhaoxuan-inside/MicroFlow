/// Unified resource registry (§23.11): runtime-resolvable implementations
/// for primitives, host components, functions, adapters and capabilities.
///
/// Registration is explicit, versioned, and the registry is the only path
/// through which implementations enter orchestration; unregistered refs are
/// static errors (§2.7).
library;

import 'package:microflow_model/microflow_model.dart';

/// Implementation of a registered resource, addressed as an opaque descriptor
/// (§23.2). The renderer-side loader resolves it to a runnable artifact.
class MFImplementation {
  const MFImplementation({required this.loader});
  final String loader;
}

/// A runner that all host implementations execute through.
typedef MFFn = Future<Object?> Function(Map<String, Object?> args);

class MFFunctionImpl extends MFImplementation {
  const MFFunctionImpl(this.fn, {super.loader = 'host-loader-default', this.timeoutMs = 5000});
  final MFFn fn;
  final int timeoutMs;
}

class MFAdapterImpl extends MFImplementation {
  const MFAdapterImpl(this.fn, {super.loader = 'host-loader-default', this.timeoutMs = 5000});
  final MFFn fn;
  final int timeoutMs;
}

class MFCapabilityImpl extends MFImplementation {
  const MFCapabilityImpl({
    this.fn,
    this.states = const <String, bool>{},
    super.loader = 'host-loader-default',
  });

  /// Defaults live in `states`. In particular, only declared non-success
  /// states degrade (§17.1).
  final Map<String, bool> states;
  final MFFn? fn;
}

/// Host-implementation component: a widget builder not carried in the
/// model (§23.2). Framework only depends on the declared contract.
typedef MFComponentBuilder = Object Function(List<MFChild> children, Map<String, Object?> props);

class MFChild {
  const MFChild({required this.id, required this.child, required this.slotOf});
  final String id;
  final Object child;
  final String? slotOf;
}

class MFHostComponentImpl extends MFImplementation {
  const MFHostComponentImpl(this.builder, {super.loader = 'host-loader-default'});
  final MFComponentBuilder builder;
}

/// One registered resource: identity, contract, implementation and version
/// (§4.2, §23.2), with explicit deprecation (§23.6).
class MFResourceEntry {
  MFResourceEntry({
    required this.kind,
    required this.id,
    required this.contract,
    required this.impl,
    required this.version,
    required this.description,
    this.deprecation,
  });

  final String kind;
  final String id;
  final ComponentContract contract;
  final MFImplementation impl;
  final String version;
  final String description;
  final String? deprecation;
}

/// Resource registry with versioned resource identity (§4.2).
class MFRegistry {
  final Map<String, MFResourceEntry> _resources = {};

  void register(
    String kind,
    String id,
    ComponentContract contract,
    MFImplementation impl, {
    String version = '1.0.0',
    String? description,
    String? deprecation,
  }) {
    _resources[id] = MFResourceEntry(
      kind: kind,
      id: id,
      contract: contract,
      impl: impl,
      version: version,
      description: description ?? '',
      deprecation: deprecation,
    );
  }

  MFResourceEntry? entry(String id) => _resources[id];

  bool has(String id) => _resources.containsKey(id);

  List<MFResourceEntry> all() => List.unmodifiable(_resources.values);

  /// Deprecation warnings collected by the validator (§23.6). The code is
  /// registered in the unified diagnostic registry (§41.3).
  List<MFDiag> deprecationWarnings() => [
        for (final e in _resources.values)
          if (e.deprecation != null)
            MFDiag(
              MFCodes.regDeprecated,
              '资源 ${e.id} 已废弃：应使用 ${e.deprecation}',
              severity: Severity.warning,
            ),
      ];
}
