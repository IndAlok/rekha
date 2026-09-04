"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import {
  BookOpen,
  CheckSquare,
  Clock,
  Handshake,
  LayoutDashboard,
  List,
  Phone,
  Play,
  Radio,
  ScrollText,
  Settings,
  ShieldOff,
  Webhook,
} from "lucide-react"
import { useEffect, useState } from "react"
import { api, ApiError, type Status } from "@/lib/api"
import { Banner } from "./ui/Banner"
import { StatusBar } from "./StatusBar"
import { ToastProvider } from "./ui/Toast"

const GROUPS = [
  {
    label: "Recovery",
    items: [
      { href: "/", label: "Overview", icon: LayoutDashboard },
      { href: "/cases", label: "Cases", icon: List },
      { href: "/live", label: "Live", icon: Radio },
      { href: "/approvals", label: "Approvals", icon: CheckSquare },
      { href: "/ptp", label: "Promises", icon: Handshake },
      { href: "/jobs", label: "Jobs", icon: Clock },
    ],
  },
  {
    label: "Assurance",
    items: [
      { href: "/audit", label: "Audit chain", icon: BookOpen },
      { href: "/compliance", label: "Blocked actions", icon: ShieldOff },
      { href: "/ledger", label: "Ledger", icon: ScrollText },
      { href: "/policy", label: "Policy", icon: ShieldOff },
    ],
  },
  {
    label: "Tools",
    items: [
      { href: "/webhooks", label: "Webhook console", icon: Webhook },
      { href: "/awaaz", label: "Awaaz", icon: Phone },
      { href: "/run", label: "Run case", icon: Play },
    ],
  },
]

function active(pathname: string, href: string) {
  if (href === "/") return pathname === "/"
  return pathname === href || pathname.startsWith(`${href}/`)
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const [status, setStatus] = useState<Status | null>(null)
  const [apiPhase, setApiPhase] = useState<"pending" | "up" | "down">("pending")
  const [pending, setPending] = useState(0)
  const [authNeeded, setAuthNeeded] = useState(false)

  useEffect(() => {
    const onUnauth = () => setAuthNeeded(true)
    window.addEventListener("rekha:unauthorized", onUnauth)
    return () => window.removeEventListener("rekha:unauthorized", onUnauth)
  }, [])

  useEffect(() => {
    setAuthNeeded(false)
  }, [pathname])

  useEffect(() => {
    let cancelled = false
    const tick = () => {
      if (document.hidden) return
      api
        .status()
        .then((row) => {
          if (!cancelled) {
            setStatus(row)
            setApiPhase("up")
          }
        })
        .catch(() => {
          if (!cancelled) {
            setStatus(null)
            setApiPhase("down")
          }
        })
      api
        .approvals("pending")
        .then((rows) => {
          if (!cancelled) setPending(rows.length)
        })
        .catch((e) => {
          if (e instanceof ApiError && e.code === "UNAUTHORIZED") setAuthNeeded(true)
        })
    }
    tick()
    const id = setInterval(tick, 8000)
    const vis = () => {
      if (!document.hidden) tick()
    }
    document.addEventListener("visibilitychange", vis)
    return () => {
      cancelled = true
      clearInterval(id)
      document.removeEventListener("visibilitychange", vis)
    }
  }, [])

  return (
    <ToastProvider>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <div className="shell">
        <aside className="sidebar">
          <div className="brand">
            <span className="brand-mark" aria-hidden />
            <div>
              <div className="brand-name">Rekha</div>
              <div className="brand-sub">revenue recovery</div>
            </div>
          </div>
          <nav className="nav-groups" aria-label="Desk">
            {GROUPS.map((g) => (
              <div className="nav-group" key={g.label}>
                <span className="nav-label">{g.label}</span>
                {g.items.map((item) => {
                  const Icon = item.icon
                  const on = active(pathname, item.href)
                  return (
                    <Link key={item.href} href={item.href} className={`nav-item${on ? " active" : ""}`} aria-current={on ? "page" : undefined}>
                      <Icon />
                      <span>{item.label}</span>
                      {item.href === "/approvals" && pending > 0 ? <span className="nav-count">{pending}</span> : null}
                    </Link>
                  )
                })}
              </div>
            ))}
          </nav>
          <div className="sidebar-foot">
            <Link href="/ops" className={`nav-item${active(pathname, "/ops") ? " active" : ""}`}>
              <Settings />
              <span>Status</span>
            </Link>
            <div className="btn-row">
              <span className={`pill ${status?.kill_switch ? "hot" : ""}`}>
                {status?.kill_switch ? "kill switch on" : "kill switch off"}
              </span>
            </div>
            <StatusBar status={status} phase={apiPhase} />
          </div>
        </aside>
        <div className="content">
          <main id="main" className="page">
            {authNeeded ? (
              <Banner kind="danger">
                Ops token missing or wrong. Mutating calls need <code>X-Ops-Token</code>. Set it on{" "}
                <Link href="/ops">Status</Link>.
              </Banner>
            ) : null}
            {children}
          </main>
        </div>
      </div>
    </ToastProvider>
  )
}
