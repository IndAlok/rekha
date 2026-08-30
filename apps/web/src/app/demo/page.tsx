"use client"

import Link from "next/link"
import { PageHeader } from "@/components/ui/PageHeader"
import { Panel } from "@/components/ui/Panel"

const BEATS = [
  {
    t: "00:00 to 00:40",
    title: "Live failure",
    href: "/webhooks",
    body: "Send payment.failed with insufficient_funds. Diagnosed C, Payment Doctor wants a salary-window retry. Replay the same event id. Response is deduped true.",
  },
  {
    t: "00:40 to 01:05",
    title: "Late payment",
    href: "/webhooks",
    body: "Send the payment.authorized sample for the same order. The recovery event closes the case and attributes the rupee on Ledger. No message is sent. Eval twin: c-0004, trap late_auth, tagged self_cure.",
  },
  {
    t: "01:05 to 01:30",
    title: "Blocked",
    href: "/compliance",
    body: "Point at CLASS_B_ENGINEERING_ONLY and COUPON_RECLASSIFIES_PROMOTIONAL. Read the rule id out loud.",
  },
  {
    t: "01:30 to 02:00",
    title: "Approvals",
    href: "/approvals",
    body: "Use Run a ₹50,001 voice case on Approvals, or Run case with amount_paise 5000100 and prefer_voice true. Awaaz at that amount is the FSM only and cannot create an approval. Approve. The executor runs. Reject is the other button. Pending auto-deny after 2 days.",
  },
  {
    t: "02:00 to 02:20",
    title: "Tamper",
    href: "/audit",
    body: "Verify, then tamper one row. The chain breaks against the live database rows, not a canned artifact.",
  },
  {
    t: "02:20 to 02:35",
    title: "Kill switch",
    href: "/ops",
    body: "Toggle it on Status. Every action except suppress, alert, and escalate, including silent retries, becomes KILL_SWITCH. The state persists across a restart. Approving while it is on returns 409.",
  },
  {
    t: "02:35 to 03:00",
    title: "Asha",
    href: "/awaaz",
    body: "Wrong digits hang up after two tries. The agent never reads the secret out. Distress, complaint, or escalate stops the call. Scripted transcript fixture driven by the real FSM. No audio pipeline is claimed.",
  },
  {
    t: "03:00 to 04:40",
    title: "Overview",
    href: "/",
    body: "Hash-arm holdout, treatment vs control on disjoint customers, incremental rupees, Newcombe and BCa. Rate CI excludes zero. Rupee BCa may include zero. Quiet-hour DEFER is not recovered. Eval send_after is a modeled payout only when the persona would pay. Zero violations. The MDE line. Do not claim p<0.05 on this n.",
  },
  {
    t: "04:40 to 05:00",
    title: "What you refused",
    href: "/policy",
    body: "Agent Studio clone. s.138 sender. PSTN first. ngrok. Live keys. A 70% recovery slide.",
  },
]

export default function DemoPage() {
  return (
    <>
      <PageHeader title="Demo" lede="Nine beats, under five minutes. make serve first. Eval builds on boot if the report is missing." />
      {BEATS.map((b, i) => (
        <Panel key={b.title} title={`${i + 1}. ${b.title}`} lede={b.t} actions={<Link href={b.href}>Open</Link>}>
          <p>{b.body}</p>
        </Panel>
      ))}
    </>
  )
}
