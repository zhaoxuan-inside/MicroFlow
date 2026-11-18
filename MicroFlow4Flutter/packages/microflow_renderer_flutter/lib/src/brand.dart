/// 框架名称词标（品牌资产）——MF 徽标方块 + 双色词标 + 可选应用名后缀。
///
/// 与 Web 侧 Kit Logo 同一语义：品牌蓝 #0070F3 固定不随主题换色（品牌资产
/// 不是主题 token），文字对比度走 Theme；camelCase 语义上 "Micro" 前景色、
/// "Flow" 品牌蓝。AppBar 经 `MicroFlowApp(appName: ...)` 消费——宿主在装配
/// （代码平面）传入应用名，框架不把它塞进项目模型。
library;

import 'package:flutter/material.dart';

class MFBrandMark extends StatelessWidget {
  const MFBrandMark({super.key, this.appName, this.compact = false});

  /// 应用名（宿主装配传入，如「运营工作台」），弱化色后缀；空则只显示框架词标。
  final String? appName;

  /// AppBar 紧凑档（徽标 26px / 词标 14px）；false 为展示档。
  final bool compact;

  static const Color brandBlue = Color(0xFF0070F3);

  @override
  Widget build(BuildContext context) {
    final badge = compact ? 26.0 : 30.0;
    final onSurface = Theme.of(context).colorScheme.onSurface;
    final onSurfaceVariant = Theme.of(context).colorScheme.onSurfaceVariant;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: badge,
          height: badge,
          decoration: BoxDecoration(color: brandBlue, borderRadius: BorderRadius.circular(6)),
          alignment: Alignment.center,
          child: Text(
            'MF',
            style: TextStyle(
              color: Colors.white,
              fontWeight: FontWeight.w700,
              fontFamily: 'monospace',
              fontSize: badge * 0.42,
            ),
          ),
        ),
        const SizedBox(width: 8),
        Text(
          'Micro',
          style: TextStyle(
            color: onSurface,
            fontWeight: FontWeight.w700,
            fontSize: compact ? 14 : 17,
            letterSpacing: 0.2,
          ),
        ),
        Text(
          'Flow',
          style: TextStyle(
            color: brandBlue,
            fontWeight: FontWeight.w700,
            fontSize: compact ? 14 : 17,
            letterSpacing: 0.2,
          ),
        ),
        if (appName != null && appName!.isNotEmpty) ...[
          const SizedBox(width: 8),
          Text(
            appName!,
            style: TextStyle(
              color: onSurfaceVariant,
              fontWeight: FontWeight.w500,
              fontSize: compact ? 14 : 15,
            ),
          ),
        ],
      ],
    );
  }
}
