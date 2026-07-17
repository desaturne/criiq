import { createContext, useContext } from "react";
import { AdminCtxValue } from "../../types/index";

export const AdminContext = createContext<AdminCtxValue>({ users: [], setUsers: () => {} });

export const useAdminCtx = () => useContext(AdminContext);
