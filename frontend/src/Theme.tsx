import {createContext, useContext, useLayoutEffect, useState, type ReactNode} from "react";

const key = "tern.theme";
const ThemeContext = createContext({dark: false, toggleDark: () => {}});

export function ThemeProvider({children}: {children: ReactNode}) {
  const [dark, setDark] = useState(() => {
    try {return localStorage.getItem(key) === "dark";}
    catch {return false;}
  });

  useLayoutEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    try {localStorage.setItem(key, dark ? "dark" : "light");} catch {}
  }, [dark]);

  return <ThemeContext.Provider value={{dark, toggleDark: () => setDark(value => !value)}}>
    {children}
  </ThemeContext.Provider>;
}

export function useTheme() {
  return useContext(ThemeContext);
}
