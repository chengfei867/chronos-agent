// Theme context — mode toggle between dark / light.
// Dark is default (matches original palette #0d1117 + #58a6ff).
import { createContext } from "react";

export type ThemeMode = "dark" | "light";

export interface ThemeContextValue {
  mode: ThemeMode;
  setMode: (mode: ThemeMode) => void;
}

export const ThemeContext = createContext<ThemeContextValue>({
  mode: "dark",
  setMode: () => {},
});
