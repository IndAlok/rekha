"use client"

import { useState } from "react"
import { ChartTooltip } from "./ChartTooltip"

export function EstimatePlot({
  obs,
  lo,
  hi,
  format,
  caption,
}: {
  obs: number
  lo: number
  hi: number
  format: (n: number) => string
  caption: string
}) {
  const [tip, setTip] = useState<{ x: number; y: number } | null>(null)
  const pad = 28
  const w = 480
  const h = 56
  const min = Math.min(lo, hi, obs, 0)
  const max = Math.max(lo, hi, obs, 0)
  const span = max - min || 1
  const x = (v: number) => pad + ((v - min) / span) * (w - pad * 2)
  const mid = 28
  return (
    <div style={{ position: "relative" }}>
      <svg
        className="chart faint"
        viewBox={`0 0 ${w} ${h}`}
        role="img"
        aria-label={caption}
        onMouseMove={(e) => {
          const box = e.currentTarget.getBoundingClientRect()
          setTip({ x: e.clientX - box.left + 8, y: e.clientY - box.top - 36 })
        }}
        onMouseLeave={() => setTip(null)}
      >
        <line x1={x(0)} y1={10} x2={x(0)} y2={46} stroke="#ddd6c8" />
        <line x1={x(lo)} y1={mid} x2={x(hi)} y2={mid} stroke="#1c1914" strokeWidth="1.5" />
        <line x1={x(lo)} y1={mid - 6} x2={x(lo)} y2={mid + 6} stroke="#1c1914" />
        <line x1={x(hi)} y1={mid - 6} x2={x(hi)} y2={mid + 6} stroke="#1c1914" />
        <circle cx={x(obs)} cy={mid} r="4" fill="#1c1914" />
        <text x={x(lo)} y={50} fontSize="10" fill="currentColor" textAnchor="middle">
          {format(lo)}
        </text>
        <text x={x(hi)} y={50} fontSize="10" fill="currentColor" textAnchor="middle">
          {format(hi)}
        </text>
      </svg>
      <p className="lede">{caption}</p>
      {tip && (
        <ChartTooltip x={tip.x} y={tip.y}>
          <div className="tabular">{format(obs)}</div>
          <div className="muted">
            {format(lo)} to {format(hi)}
          </div>
        </ChartTooltip>
      )}
    </div>
  )
}
