import { createContext, useContext } from "react";
import { AppContextValue } from "../types/index";

export const AppContext = createContext<AppContextValue>({
  dark: true, setDark: () => {},
  selections: {}, setSelections: () => {},
});

export const useApp = () => useContext(AppContext);
