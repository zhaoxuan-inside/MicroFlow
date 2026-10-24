/// 标准运营事件族（§24.2，基线 29）：登记名的单一来源。运行时零埋点发射、
/// 采集注记静态校验与查询协议共用本清单。
library;

/// Standard operational event families (§24.2, baseline 29).
abstract final class MFStandardEvents {
  static const pageViewed = 'ops.page.viewed';
  static const pageLeft = 'ops.page.left';
  static const featureUsed = 'ops.feature.used';
  static const contentExposed = 'ops.content.exposed';
  static const feedbackSubmitted = 'ops.feedback.submitted';
  static const feedbackResolved = 'ops.feedback.resolved';
  static const campaignAttributed = 'ops.campaign.attributed';

  static const all = {
    pageViewed,
    pageLeft,
    featureUsed,
    contentExposed,
    feedbackSubmitted,
    feedbackResolved,
    campaignAttributed,
  };
}
