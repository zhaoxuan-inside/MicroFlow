/// 代码平面（宿主实现）：CLI --impls 装载；default 导出对象，键 = registry id。
export default {
  'demo.authenticate': (args) => (args.username === 'alice' ? 'alice' : null),
};
