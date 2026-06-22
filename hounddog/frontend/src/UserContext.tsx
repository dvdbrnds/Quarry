import { createContext, useContext } from "react";
import type { AuthUser } from "./auth";

export const UserContext = createContext<AuthUser | null>(null);

export function useCurrentUser(): AuthUser | null {
  return useContext(UserContext);
}
