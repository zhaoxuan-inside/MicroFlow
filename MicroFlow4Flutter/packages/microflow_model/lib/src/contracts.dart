/// Public contracts for primitives, host components and containers
/// (frontend-framework-design §2.2, §5, §23.2).
///
/// A contract is the only surface framework orchestration depends on:
/// props, slots, events, states, layout capabilities, exposed styles,
/// accessibility requirements and the container info facet (§2.8).
library;

/// Declared state of a property / event payload / info shape.
sealed class MFTypes {
  const MFTypes();
  bool check(Object? value);
}

class TString extends MFTypes {
  const TString();
  @override
  bool check(Object? value) => value is String;
}

class TNumber extends MFTypes {
  const TNumber();
  @override
  bool check(Object? value) => value is num;
}

class TBool extends MFTypes {
  const TBool();
  @override
  bool check(Object? value) => value is bool;
}

class TEnum extends MFTypes {
  const TEnum(this.values);
  final List<String> values;
  @override
  bool check(Object? value) => value is String && values.contains(value);
}

class TObject extends MFTypes {
  const TObject({this.requiredKeys = const []});
  final List<String> requiredKeys;
  @override
  bool check(Object? value) =>
      value is Map && requiredKeys.every((k) => value.containsKey(k));
}

class TList extends MFTypes {
  const TList({this.item});
  final MFTypes? item;
  @override
  bool check(Object? value) =>
      value is List && (item == null || value.every(item!.check));
}

/// Container info facet (§2.8): information the container provides to its
/// subtree after assembly, and information it consumes from upstream.
class InfoContract {
  const InfoContract({
    this.provides = const {},
    this.consumes = const {},
  });

  /// info id -> declared shape (validated when provided).
  final Map<String, String> provides;

  /// info id -> required flag. Unresolvable required consumes are a static
  /// error (ghost dependency, baseline 16).
  final Map<String, bool> consumes;

  bool get isDeclared => provides.isNotEmpty || consumes.isNotEmpty;
}

/// Layout capability declaration (§7.2 sizing/display subset).
class LayoutCapability {
  const LayoutCapability({
    this.display = const ['block'],
    this.sizing = const ['hug'],
  });

  final List<String> display;
  final List<String> sizing;

  bool supports(String capability, String kind) {
    return switch (kind) {
      'display' => display.contains(capability),
      'sizing' => sizing.contains(capability),
      _ => false,
    };
  }
}

/// Public contract of a component or primitive.
class ComponentContract {
  const ComponentContract({
    this.props = const {},
    this.slots = const [],
    this.events = const {},
    this.states = const [],
    this.layout = const LayoutCapability(),
    this.exposedStyles = const [],
    this.accessibilityRole,
    this.requiresLabel = false,
    this.info = const InfoContract(),
  });

  /// prop name -> type spec.
  final Map<String, MFTypes> props;

  /// Declared slot names. Providing undeclared slots is an error (§23.9).
  final List<String> slots;

  /// event name -> payload type spec.
  final Map<String, MFTypes> events;

  final List<String> states;
  final LayoutCapability layout;
  final List<String> exposedStyles;
  final String? accessibilityRole;
  final bool requiresLabel;
  final InfoContract info;

  bool declaresEvent(String event) => events.containsKey(event);

  bool declaresProp(String prop) => props.containsKey(prop);
}
