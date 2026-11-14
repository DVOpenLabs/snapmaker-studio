import { useNavigate } from "react-router-dom";
import { openModelDialog } from "@/api";
import { useSession } from "@/store/session";
import { JOB_ROUTE } from "@/lib/routes";

/** Returns a handler that opens the native file picker, loads the chosen
 *  STL/3MF into the session (which auto-runs Doctor), and navigates to the
 *  live workspace. No-op if the user cancels. */
export function useOpenFile() {
  const nav = useNavigate();
  const setFile = useSession((s) => s.setFile);
  return async () => {
    const path = await openModelDialog();
    if (!path) return;
    setFile(path);
    nav(JOB_ROUTE);
  };
}
