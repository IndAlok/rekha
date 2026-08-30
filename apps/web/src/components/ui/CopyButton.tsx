"use client"

import { useState } from "react"
import { Copy } from "lucide-react"

export function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false)
  return (
    <button
      type="button"
      className="btn btn-ghost"
      aria-label="Copy"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text)
          setDone(true)
          setTimeout(() => setDone(false), 1200)
        } catch {
          setDone(false)
        }
      }}
    >
      <Copy size={14} />
      {done ? "Copied" : "Copy"}
    </button>
  )
}
