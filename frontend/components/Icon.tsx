import type { ReactNode } from "react";

type IconName =
  | "arrow"
  | "bell"
  | "book"
  | "chart"
  | "check"
  | "chevron"
  | "clock"
  | "folder"
  | "help"
  | "home"
  | "layers"
  | "library"
  | "plus"
  | "search"
  | "settings"
  | "shield"
  | "tag"
  | "upload"
  | "users"
  | "workflow";

const paths: Record<IconName, ReactNode> = {
  arrow: <path d="M5 12h14m-6-6 6 6-6 6" />,
  bell: (
    <>
      <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" />
      <path d="M10 21h4" />
    </>
  ),
  book: <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v17H6.5A2.5 2.5 0 0 1 4 17.5zm0 12A2.5 2.5 0 0 1 6.5 15H20M8 7h8m-8 4h7" />,
  chart: (
    <>
      <path d="M4 19V5m0 14h17" />
      <path d="M8 15v-4m5 4V7m5 8v-6" />
    </>
  ),
  check: <path d="m5 12 4 4L19 6" />,
  chevron: <path d="m9 18 6-6-6-6" />,
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  folder: <path d="M3 6a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />,
  help: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.6 9a2.5 2.5 0 1 1 4.4 1.6c-1.1 1.1-2 1.4-2 3.1m0 3h.01" />
    </>
  ),
  home: <path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7h-6v7H4a1 1 0 0 1-1-1z" />,
  layers: (
    <>
      <path d="m12 3 9 5-9 5-9-5z" />
      <path d="m3 12 9 5 9-5M3 16l9 5 9-5" />
    </>
  ),
  library: (
    <>
      <path d="M4 5h16v15H4zM8 5V3h8v2" />
      <path d="M8 9h8m-8 4h8m-8 4h5" />
    </>
  ),
  plus: <path d="M12 5v14m-7-7h14" />,
  search: (
    <>
      <circle cx="10.8" cy="10.8" r="6.8" />
      <path d="m16 16 5 5" />
    </>
  ),
  settings: (
    <>
      <path d="M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z" />
      <path d="m19.4 15 .1.1 1.1 1.8-1.8 3.1-2.1-.4a8 8 0 0 1-1.5.9l-.9 1.9h-3.6l-.9-1.9a8 8 0 0 1-1.5-.9l-2.1.4-1.8-3.1 1.1-1.8a8 8 0 0 1 0-1.8l-1.1-1.8 1.8-3.1 2.1.4a8 8 0 0 1 1.5-.9l.9-1.9h3.6l.9 1.9a8 8 0 0 1 1.5.9l2.1-.4 1.8 3.1-1.1 1.8a8 8 0 0 1 0 1.8Z" />
    </>
  ),
  shield: <path d="M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Zm-3-11 2 2 4-4" />,
  tag: <path d="M20 13 13 20 3 10V4h6zM7.5 7.5h.01" />,
  upload: <path d="M12 16V4m-5 5 5-5 5 5M4 15v5h16v-5" />,
  users: (
    <>
      <path d="M16 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2m6-10a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm6-7.5a4 4 0 0 1 0 7.8m2 3.7a4 4 0 0 1 3 3.9V21" />
    </>
  ),
  workflow: (
    <>
      <circle cx="6" cy="6" r="2.5" />
      <circle cx="18" cy="6" r="2.5" />
      <circle cx="12" cy="18" r="2.5" />
      <path d="M8.5 6h7M7.4 8.2l3.2 7.5m6-7.5-3.2 7.5" />
    </>
  ),
};

export function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      focusable="false"
    >
      {paths[name]}
    </svg>
  );
}

export type { IconName };
