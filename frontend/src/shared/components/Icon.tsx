import type { ReactNode, SVGProps } from "react";

type IconName =
  | "assets"
  | "findings"
  | "insights"
  | "reports"
  | "jobs"
  | "example"
  | "plus"
  | "refresh"
  | "arrow"
  | "close"
  | "workflow"
  | "package"
  | "database"
  | "check"
  | "play"
  | "pause"
  | "download"
  | "chevron"
  | "activity"
  | "link"
  | "alert"
  | "scope"
  | "users"
  | "logout"
  | "shield"
  | "external";

const paths: Record<IconName, ReactNode> = {
  workflow: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1.6" />
      <rect x="14" y="3" width="7" height="7" rx="1.6" />
      <rect x="3" y="14" width="7" height="7" rx="1.6" />
      <rect x="14" y="14" width="7" height="7" rx="1.6" />
    </>
  ),
  package: (
    <>
      <path d="m12 2.8 8.5 4.8v8.8l-8.5 4.8-8.5-4.8V7.6zM4 7.7l8 4.6 8-4.6M12 12.3v8.4M8 5.1l8.4 4.8" />
    </>
  ),
  database: (
    <>
      <ellipse cx="12" cy="5.7" rx="8" ry="3.2" />
      <path d="M4 5.7v12.6c0 4.3 16 4.3 16 0V5.7M4 12c0 4.3 16 4.3 16 0" />
    </>
  ),
  check: <path d="m4.8 12.5 4.5 4.5L19.3 7" />,
  play: <path d="m7.8 4.6 11.3 7.4-11.3 7.4z" fill="currentColor" strokeWidth="1.4" />,
  pause: <path d="M9 5v14m6-14v14" strokeWidth="2.5" />,
  download: (
    <>
      <path d="M12 3v12m-5-5 5 5 5-5M4 16v4h16v-4" />
    </>
  ),
  chevron: <path d="m7 10 5 5 5-5" />,
  activity: <path d="M2 12h5l3-8 4.2 16 3-8H22" />,
  link: (
    <>
      <path d="m10 14 4-4m-5-1 3-3a4 4 0 0 1 6 6l-2 2M15 15l-3 3a4 4 0 0 1-6-6l2-2" />
    </>
  ),
  alert: (
    <>
      <path d="m12 3 9 17H3zM12 9v4m0 3v.1" />
    </>
  ),
  scope: (
    <>
      <circle cx="12" cy="12" r="7.5" />
      <circle cx="12" cy="12" r="2.5" />
      <path d="M12 1.5v4m0 13v4M1.5 12h4m13 0h4" />
    </>
  ),
  users: (
    <>
      <circle cx="10" cy="8" r="3" />
      <path d="M3.5 20v-2c0-5 13-5 13 0v2M16 5.5a3 3 0 0 1 0 5.7m2 3c2 .6 3 2 3 4" />
    </>
  ),
  logout: <path d="M10 4H4v16h6m2-8h9m-4-4 4 4-4 4" />,
  shield: (
    <>
      <path d="m12 2.5 8 3.3v5.5c0 5.3-4.4 8.8-8 10.3-3.6-1.5-8-5-8-10.3V5.8z" />
      <path d="m8.5 11.6 2.4 2.4 4.6-5" />
    </>
  ),
  external: <path d="M13 4h7v7m0-7L9 15M9 6H4v14h14v-5" />,
  assets: (
    <>
      <rect x="3" y="4" width="18" height="6" rx="1.5" />
      <rect x="3" y="14" width="18" height="6" rx="1.5" />
      <path d="M7 7h.01M7 17h.01M11 7h6M11 17h6" />
    </>
  ),
  findings: (
    <>
      <path d="M12 3 4.5 6v5c0 4.8 3.1 8.1 7.5 10 4.4-1.9 7.5-5.2 7.5-10V6L12 3Z" />
      <path d="M12 8v4m0 3h.01" />
    </>
  ),
  insights: (
    <>
      <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H11l-4.5 4v-4A2.5 2.5 0 0 1 4 13.5v-8Z" />
      <path d="M8 8h8M8 11.5h5" />
    </>
  ),
  reports: (
    <>
      <path d="M6 3.5h8l4 4v13H6z" />
      <path d="M14 3.5v4h4M9 12h6M9 15.5h6" />
    </>
  ),
  jobs: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5v5l3.5 2" />
    </>
  ),
  example: (
    <>
      <path d="M9 3.5h6M10 3.5v6l-4.5 7.2A2 2 0 0 0 7.2 20h9.6a2 2 0 0 0 1.7-3.3L14 9.5v-6M8 15h8" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  refresh: (
    <>
      <path d="M20 7v5h-5M4 17v-5h5" />
      <path d="M5.5 9A7 7 0 0 1 18 6l2 1M4 17l2 1a7 7 0 0 0 12.5-3" />
    </>
  ),
  arrow: <path d="M5 12h13m-5-5 5 5-5 5" />,
  close: <path d="m6 6 12 12M18 6 6 18" />,
};

export function Icon({ name, ...props }: SVGProps<SVGSVGElement> & { name: IconName }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.65"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {paths[name]}
    </svg>
  );
}
