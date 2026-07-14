import { createContext, useContext } from "react";
import { AppContextValue } from "../types/index";

export const AppContext = createContext<AppContextValue>({
  dark: true, setDark: () => {},
  selections: {}, setSelections: () => {},
  token: null, user: null,
  login: async () => {}, register: async () => {}, logout: async () => {},
});

export const useApp = () => useContext(AppContext);
