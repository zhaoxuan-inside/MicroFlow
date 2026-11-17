import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { host } from "@microflow4kit/api";

type Theme = "light" | "dark";
const ThemeContext = createContext<{ theme: Theme; toggle: () => void }>({
  theme: "dark",
  toggle: () => {},
});

export function ThemeProvider({ children }: { children: ReactNode }) {
  // 暗色优先（2025-26 开发者工具控制台共识）；用户显式选择过则持久化生效
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem(host.themeKey) as Theme) || "dark",
  );
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    localStorage.setItem(host.themeKey, theme);
  }, [theme]);
  return (
    <ThemeContext.Provider
      value={{ theme, toggle: () => setTheme((t) => (t === "dark" ? "light" : "dark")) }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

export const useTheme = () => useContext(ThemeContext);
