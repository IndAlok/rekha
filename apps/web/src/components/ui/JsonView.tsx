"use client"

import { CopyButton } from "./CopyButton"

export function JsonView({ value, label = "JSON" }: { value: unknown; label?: string }) {
  const text = JSON.stringify(value, null, 2)
  return (
    <div>
      <div className="btn-row" style={{ marginBottom: 8 }}>
        <CopyButton text={text} />
        <span className="faint">{label}</span>
      </div>
      <pre className="json">{text}</pre>
    </div>
  )
}
