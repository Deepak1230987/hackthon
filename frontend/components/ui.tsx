import {
  CircleAlert,
  CircleCheck,
  Info,
  LoaderCircle,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";

export type NoticeTone = "info" | "success" | "warning" | "danger";

const NOTICE_STYLES: Record<NoticeTone, { box: string; icon: string; Icon: LucideIcon }> = {
  info: { box: "border-accent/25 bg-accent-soft", icon: "text-accent", Icon: Info },
  success: { box: "border-success/30 bg-success-soft", icon: "text-success", Icon: CircleCheck },
  warning: { box: "border-warning/30 bg-warning-soft", icon: "text-warning", Icon: TriangleAlert },
  danger: { box: "border-danger/30 bg-danger-soft", icon: "text-danger", Icon: CircleAlert },
};

export function Notice({
  tone,
  title,
  role,
  children,
}: {
  tone: NoticeTone;
  title?: ReactNode;
  role?: "alert" | "status";
  children?: ReactNode;
}) {
  const { box, icon, Icon } = NOTICE_STYLES[tone];
  return (
    <div role={role} className={`flex gap-3 rounded-xl border px-3.5 py-3 text-sm ${box}`}>
      <Icon aria-hidden className={`mt-0.5 size-5 shrink-0 ${icon}`} />
      <div className="min-w-0 flex-1">
        {title && <p className="font-semibold">{title}</p>}
        {children}
      </div>
    </div>
  );
}

export function Spinner({ className = "size-5" }: { className?: string }) {
  return (
    <LoaderCircle
      aria-hidden
      className={`animate-spin motion-reduce:animate-none ${className}`}
    />
  );
}

// The tap target stays full size while the pill it wraps looks small.
export function SourceChip({
  page,
  label,
  onClick,
}: {
  page: number;
  label?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group inline-flex min-h-11 shrink-0 items-center rounded-full"
    >
      <span className="rounded-full bg-accent-soft px-3 py-1 text-sm font-semibold whitespace-nowrap text-accent group-hover:bg-accent group-hover:text-white">
        {label ?? `Source: page ${page}`}
      </span>
    </button>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={`animate-pulse rounded-md bg-sunken motion-reduce:animate-none ${className}`}
    />
  );
}
