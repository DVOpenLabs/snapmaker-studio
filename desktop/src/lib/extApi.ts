import { post } from "@/api";

/** Thin extension client over the desktop's existing authenticated POST helper. */
export function callExt<T>(path: string, body: unknown, label: string): Promise<T> {
  return post<T>(path, body, label);
}
