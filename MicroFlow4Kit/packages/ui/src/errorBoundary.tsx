/** 全局错误边界：组件树崩溃时给出品牌化降级面（而非白屏）。
 * 接入点：各 SPA 在 Router/Provider 外层包一层；重试按钮清错误状态重挂子树。 */
import { Component, type ReactNode } from "react";

interface BoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends Component<{ children: ReactNode; fallback?: (error: Error, retry: () => void) => ReactNode }, BoundaryState> {
  state: BoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error };
  }

  componentDidUpdate(_: unknown, previous: BoundaryState): void {
    if (this.state.error && previous.error === null) {
      // 首次捕获：控制台留痕（诊断面后续接入统一上报）。
      console.error("[ErrorBoundary]", this.state.error);
    }
  }

  private retry = (): void => this.setState({ error: null });

  render(): ReactNode {
    const { error } = this.state;
    if (error) {
      if (this.props.fallback) return this.props.fallback(error, this.retry);
      return (
        <div role="alert" style={{ padding: 48, textAlign: "center", fontFamily: "sans-serif" }}>
          <h2 style={{ fontSize: 18, marginBottom: 8 }}>页面出错了</h2>
          <p style={{ color: "#666", fontSize: 13, marginBottom: 16 }}>
            渲染期间发生未捕获异常：{error.message}
          </p>
          <button
            onClick={this.retry}
            style={{ padding: "8px 20px", borderRadius: 8, border: "1px solid #d4d4d4", cursor: "pointer" }}
          >
            重试
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
