/** 命令面板（⌘K）：cmdk（shadcn 官方实现）+ 设计 token 样式。
 *
 * 受控/非受控双模式；⌘K / Ctrl+K 全局监听内置。条目由宿主 SPA 组装
 * （页面导航 / 平台管理 / 主题与语言切换等），资产深度链接需路由参数，
 * 属后续切片。
 */
import { useEffect, useState } from "react";
import { Command } from "cmdk";
import { useTranslation } from "react-i18next";

export interface CommandEntry {
  id: string;
  label: string;
  /** 分组标题（i18n 后的字符串） */
  group: string;
  /** 单字符图标（置于行首） */
  icon?: string;
  /** 行尾次要文本 */
  hint?: string;
  onSelect: () => void;
}

export function CommandPalette({
  entries,
  open,
  onOpenChange,
  placeholder,
}: {
  entries: CommandEntry[];
  /** 受控开关；缺省为内部状态 */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  placeholder?: string;
}) {
  const { t } = useTranslation("ui");
  const [internalOpen, setInternalOpen] = useState(false);
  const isControlled = open !== undefined;
  const isOpen = isControlled ? open : internalOpen;
  const setOpen = (v: boolean) => {
    if (!isControlled) setInternalOpen(v);
    onOpenChange?.(v);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(!isOpen);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const groups = [...new Set(entries.map((e) => e.group))];

  return (
    <Command.Dialog
      open={isOpen}
      onOpenChange={setOpen}
      label={t("palette.title")}
      overlayClassName="fixed inset-0 z-50 bg-foreground/40 backdrop-blur-[2px]"
      contentClassName="fixed left-1/2 top-24 z-50 w-full max-w-lg -translate-x-1/2 rounded-lg border border-border bg-card shadow-lg"
    >
      <Command.Input
        placeholder={placeholder ?? t("palette.placeholder")}
        className="w-full border-b border-border bg-transparent px-4 py-3.5 text-sm outline-none placeholder:text-muted-foreground"
      />
      <Command.List className="max-h-88 overflow-y-auto p-1.5">
        <Command.Empty className="py-8 text-center text-sm text-muted-foreground">{t("palette.empty")}</Command.Empty>
        {groups.map((group) => (
          <Command.Group key={group} heading={group} className="text-foreground [&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5">
            {entries
              .filter((e) => e.group === group)
              .map((e) => (
                <Command.Item
                  key={e.id}
                  onSelect={() => {
                    setOpen(false);
                    e.onSelect();
                  }}
                  className="flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 text-sm data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground"
                >
                  {e.icon && (
                    <span aria-hidden className="w-4 text-center opacity-70">
                      {e.icon}
                    </span>
                  )}
                  <span className="min-w-0 flex-1 truncate">{e.label}</span>
                  {e.hint && <span className="shrink-0 text-xs text-muted-foreground">{e.hint}</span>}
                </Command.Item>
              ))}
          </Command.Group>
        ))}
      </Command.List>
    </Command.Dialog>
  );
}
