"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * Sidebar navigation.
 *
 * Grouped to mirror the DCR lifecycle rather than alphabetically: a first-time
 * user should be able to read the sidebar top-to-bottom and understand the order
 * of operations.
 */

const GROUPS: { label: string; items: { href: string; label: string; num: string }[] }[] = [
  {
    label: "Setup",
    items: [
      { href: "/health", label: "Health Check", num: "0" },
      { href: "/my-data", label: "My Data", num: "1" },
    ],
  },
  {
    label: "Collaboration",
    items: [
      { href: "/collaborations", label: "Create", num: "2" },
      { href: "/invitations", label: "Invitations", num: "3" },
      { href: "/link", label: "Link Data", num: "4" },
    ],
  },
  {
    label: "Analysis",
    items: [
      { href: "/analyze", label: "Run Overlap", num: "5" },
      { href: "/activate", label: "Activate", num: "6" },
      { href: "/inbox", label: "Activation Inbox", num: "7" },
    ],
  },
  {
    label: "Manage",
    items: [
      { href: "/history", label: "History", num: "8" },
      { href: "/admin", label: "Admin", num: "9" },
    ],
  },
];

export function Nav() {
  const pathname = usePathname();
  return (
    <nav className="sidebar">
      <Link href="/" className="brand" style={{ color: "inherit", textDecoration: "none" }}>
        <span>
          DCR Console
          <small>Audience Overlap · API v2</small>
        </span>
      </Link>

      {GROUPS.map((g) => (
        <div className="nav-group" key={g.label}>
          <div className="nav-group-label">{g.label}</div>
          {g.items.map((i) => (
            <Link
              key={i.href}
              href={i.href}
              className={`nav-item${pathname === i.href ? " active" : ""}`}
            >
              <span className="nav-num">{i.num}</span>
              {i.label}
            </Link>
          ))}
        </div>
      ))}
    </nav>
  );
}
