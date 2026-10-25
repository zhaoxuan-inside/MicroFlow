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
    this.telemetry,
    this.trace,
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

  /// 采集注记（§24.7）：声明式注记决定定向内容。注记事件仍走完整采集管道
  /// （Schema 校验、身份注入、队列、隐私检查），业务代码零埋点（基线 8）。
  final MFTelemetryAnnotation? telemetry;

  /// 追踪传播声明（§24.8）：声明传播的适配器调用由运行时注入追踪上下文，
  /// 业务代码与适配器实现不得自行构造或改写追踪身份（基线 11）。
  final MFTracePropagation? trace;

  bool declaresEvent(String event) => events.containsKey(event);

  bool declaresProp(String prop) => props.containsKey(prop);
}

/// 允许的隐私分类（§24.2、§32）：模型静态检查与观测面校验共用同一枚举。
const Set<String> mfAllowedPrivacyClasses = {'operational', 'sensitive', 'restricted'};

/// 采集注记（§24.7）：同一触点上关联的事件引用、隐私分类与采样策略。
/// 注记只携带声明，不携带可执行逻辑；引用的事件必须已登记，采样与隐私
/// 策略必须通过检查，否则是静态错误（mf.tele.annotation-invalid）。
class MFTelemetryAnnotation {
  const MFTelemetryAnnotation({
    this.events = const {},
    this.privacyClass = 'operational',
    this.samplingRatio,
    this.args = const [],
  });

  /// 触点 -> 已登记事件名（§24.7 示例：entry / success / failure）。
  final Map<String, String> events;

  final String privacyClass;

  /// ratio 采样（(0,1]）；null = 全量。命中判定由运行时按请求标识确定性执行。
  final double? samplingRatio;

  /// 声明进入事件 payload 的动作参数键（§24.7 定向内容）：只有显式声明的
  /// 参数键会随注记事件上报，未声明参数不进入采集面。
  final List<String> args;
}

/// 追踪传播声明（§24.8）：方向（出站、回传或双向）与载体字段。出站上下文
/// 至少包含 trace_id、release_id、页面实例标识和 action_request_id。
class MFTracePropagation {
  const MFTracePropagation({this.direction = 'outbound', this.carrier = const ['mf_trace']});

  final String direction; // outbound | inbound | bidirectional

  /// 载体字段名：运行时注入到适配器参数中的追踪上下文键。
  final List<String> carrier;
}

/// 启动元组件集（§38.1）：合规实现必须提供的最小元组件集。Tier B 客户端
/// 必备、允许替换实现；缺失时按 §12/§38.1 声明降级或产生明确错误。
/// 单一来源在模型层，渲染器与校验器共用（§38.1）。
abstract final class MFTierA {
  static const Set<String> required = {
    'Text', 'Icon', 'Image', 'Button', 'Input', 'Select', 'Checkbox',
    'Stack', 'Scroll', 'Overlay', 'List', 'Modal',
  };
  static const Set<String> tierB = {'Grid', 'Split', 'Anchor', 'Tabs', 'Drawer', 'Table'};
}
