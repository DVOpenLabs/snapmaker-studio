import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Inside a pane that already provides its own frame, nested cards drop their border, shadow and padding so the
 * pane reads as one surface. The cards' logic and content are untouched.
 */
const FlatContext = React.createContext(false);
export function FlatCards({ children }: { children: React.ReactNode }) {
  return <FlatContext.Provider value={true}>{children}</FlatContext.Provider>;
}

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  const flat = React.useContext(FlatContext);
  return <div className={cn(flat ? "text-card-foreground" : "rounded-lg border border-border bg-card text-card-foreground shadow-sm", className)} {...props} />;
}
export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-5 pb-3", className)} {...props} />;
}
export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn("text-[15px] font-semibold leading-none", className)} {...props} />;
}
export function CardDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("mt-1 text-sm text-muted-foreground", className)} {...props} />;
}
export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  const flat = React.useContext(FlatContext);
  // A flat card keeps its own vertical rhythm but no padding box: the pane supplies the padding.
  return <div className={cn("p-5 pt-0", className, flat && "!p-0")} {...props} />;
}
