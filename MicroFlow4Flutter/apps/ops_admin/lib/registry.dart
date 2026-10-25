/// 运营管理平台的基础资源注册面（§23）：Tier A 必备元组件契约。
///
/// 渲染由解释器 primitive table 承载（§38.1 预览实现）；注册用于静态校验
/// 与依赖发现（§23.6）。`Stack` 契约声明 `onEnter` 事件：页面生命周期绑定
/// 的 §39 锚点对象是页面根节点（与页面同 id），运行时在页面打开时直接
/// 执行该绑定（见 habit_tracker/lib/registry.dart 同款说明）。
library;

import 'package:microflow4_flutter/microflow4_flutter.dart';

MFRegistry buildBaseRegistry() {
  final registry = MFRegistry();
  for (final id in MFTierA.required) {
    registry.register(
      'primitive',
      id,
      ComponentContract(
        props: switch (id) {
          'Text' => {'text': const TString()},
          'Button' => {
              'label': const TString(),
              'variant': const TEnum(['primary', 'secondary', 'danger']),
            },
          'Input' => {
              'placeholder': const TString(),
              'value': const TString(),
              'readOnly': const TBool(),
            },
          'Icon' => {'name': const TString(), 'size': const TNumber(), 'color': const TString()},
          'Image' => {'src': const TString()},
          'Checkbox' => {'value': const TBool()},
          'Select' => {'label': const TString(), 'options': const TList(), 'value': const TString()},
          'Modal' => {'background': const TString()},
          _ => const {},
        },
        events: switch (id) {
          'Button' => {'press': const TString()},
          'Input' => {'change': const TString()},
          'Checkbox' => {'change': const TBool()},
          'Select' => {'change': const TString()},
          'Stack' => const {'press': TString(), 'onEnter': TBool()},
          _ => const {},
        },
        states: switch (id) {
          'Button' => const ['enabled', 'disabled', 'busy'],
          _ => const [],
        },
        slots: const ['content'],
        layout: const LayoutCapability(
          display: ['block', 'inline'],
          sizing: ['hug', 'fill', 'fixed'],
        ),
      ),
      MFHostComponentImpl((children, props) => Object()),
      description: 'Tier A 元组件（§38.1）：渲染由解释器 primitive table 承载',
    );
  }
  return registry;
}
