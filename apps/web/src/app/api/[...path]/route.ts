import { NextRequest, NextResponse } from "next/server"

export const dynamic = "force-dynamic"
export const runtime = "nodejs"
export const maxDuration = 60

const DROP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailers",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-length",
])

function upstream(): string {
  return (process.env.API_UPSTREAM || "http://127.0.0.1:8080").replace(/\/$/, "")
}

function down() {
  return NextResponse.json(
    { detail: { code: "API_UNREACHABLE", message: "The API is not reachable from this page" } },
    { status: 503 },
  )
}

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params
  const joined = path.join("/")
  const dest = `${upstream()}/${joined}${req.nextUrl.search}`
  const headers = new Headers()
  req.headers.forEach((value, key) => {
    if (!DROP.has(key.toLowerCase())) headers.set(key, value)
  })
  const long = joined === "eval/run" || joined.startsWith("eval/run?") || joined === "webhooks/razorpay"
  try {
    const res = await fetch(dest, {
      method: req.method,
      headers,
      body: req.method === "GET" || req.method === "HEAD" ? undefined : await req.arrayBuffer(),
      cache: "no-store",
      signal: AbortSignal.timeout(long ? 120_000 : 20_000),
    })
    const out = new Headers()
    const ct = res.headers.get("content-type")
    if (ct) out.set("content-type", ct)
    out.set("cache-control", "no-store")
    out.set("x-content-type-options", "nosniff")
    out.set("x-frame-options", "DENY")
    out.set("referrer-policy", "strict-origin-when-cross-origin")
    return new NextResponse(res.body, { status: res.status, headers: out })
  } catch {
    return down()
  }
}

export const GET = proxy
export const POST = proxy
export const PUT = proxy
export const PATCH = proxy
export const DELETE = proxy
