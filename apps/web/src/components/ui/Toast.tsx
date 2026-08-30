"use client"

import { createContext, useCallback, useContext, useState } from "react"

type Kind = "ok" | "bad" | "info"
type Item = { id: number; kind: Kind; message: string }

const Ctx = createContext<(kind: Kind, message: string) => void>(() => undefined)

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<Item[]>([])
  const push = useCallback((kind: Kind, message: string) => {
    const id = Date.now() + Math.random()
    setItems((cur) => [...cur, { id, kind, message }])
    setTimeout(() => setItems((cur) => cur.filter((x) => x.id !== id)), 3200)
  }, [])
  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="toast-wrap" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>
            {t.message}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  )
}

export function useToast() {
  return useContext(Ctx)
}
