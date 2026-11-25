import type { ReactNode } from "react";

type IconName =
  | "arrow"
  | "bell"
  | "database"
  | "drop"
  | "lock"
  | "plus"
  | "pulse"
  | "refresh"
  | "site"
  | "users";

const paths: Record<IconName, ReactNode> = {
  arrow: (
    <>
      <path d="M5 12h13" />
      <path d="m13.5 6.5 5.5 5.5-5.5 5.5" />
    </>
  ),
  bell: (
    <>
      <path d="M18 9a6 6 0 0 0-12 0c0 6-3 6-3 8h18c0-2-3-2-3-8" />
      <path d="M10 21h4" />
    </>
  ),
  database: (
    <>
      <ellipse cx="12" cy="5" rx="7" ry="3" />
      <path d="M5 5v6c0 1.7 3.1 3 7 3s7-1.3 7-3V5" />
      <path d="M5 11v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" />
    </>
  ),
  drop: (
    <path d="M12 3s6 6.2 6 10.2a6 6 0 0 1-12 0C6 9.2 12 3 12 3Z" />
  ),
  lock: (
    <>
      <rect x="5" y="10" width="14" height="10" rx="2" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3" />
    </>
  ),
  plus: (
    <>
      <path d="M12 5v14" />
      <path d="M5 12h14" />
    </>
  ),
  pulse: <path d="M3 12h4l2.2-6 4 12 2.3-6H21" />,
  refresh: (
    <>
      <path d="M20 11a8 8 0 0 0-14.4-4.8L4 8" />
      <path d="M4 4v4h4" />
      <path d="M4 13a8 8 0 0 0 14.4 4.8L20 16" />
      <path d="M20 20v-4h-4" />
    </>
  ),
  site: (
    <>
      <path d="M4 20V9l8-5 8 5v11" />
      <path d="M9 20v-6h6v6" />
    </>
  ),
  users: (
    <>
      <path d="M16 21v-2a4 4 0 0 0-8 0v2" />
      <circle cx="12" cy="7" r="4" />
      <path d="M22 21v-2a4 4 0 0 0-3-3.9" />
      <path d="M2 21v-2a4 4 0 0 1 3-3.9" />
    </>
  ),
};

export default function Icon({
  name,
  size = 18,
  className,
}: {
  name: IconName;
  size?: number;
  className?: string;
}) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      fill="none"
      height={size}
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.7"
      viewBox="0 0 24 24"
      width={size}
    >
      {paths[name]}
    </svg>
  );
}
