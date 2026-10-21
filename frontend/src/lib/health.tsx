import { createContext, useContext } from "react";
import type { HealthResponse } from "../api/types";
import type { ApiState } from "./useApi";

export const HealthContext = createContext<ApiState<HealthResponse> | null>(null);

export function useHealth(): ApiState<HealthResponse> | null {
  return useContext(HealthContext);
}
