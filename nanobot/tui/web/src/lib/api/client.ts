export type ApiEnv = {
  DEV?: boolean;
  VITE_NANOBOT_API_BASE?: string;
};

function trimTrailingSlash(value: string) {
  return value.replace(/\/+$/, "");
}

export function resolveApiBase(env: ApiEnv = import.meta.env): string {
  if (env.DEV) {
    return "/api";
  }

  return trimTrailingSlash(env.VITE_NANOBOT_API_BASE ?? "");
}

export function resolveApiPath(path: string, env?: ApiEnv): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${resolveApiBase(env)}${normalizedPath}`;
}

export async function fetchJson<T>(path: string, init?: RequestInit, env?: ApiEnv): Promise<T> {
  const response = await fetch(resolveApiPath(path, env), init);

  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }

  return (await response.json()) as T;
}
