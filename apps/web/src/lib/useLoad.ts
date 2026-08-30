"use client"

import { useCallback, useEffect, useRef, useState } from "react"

type Opts = {
  deps?: unknown[]
  pollMs?: number
}

export function useFetch<T>(fn: (signal?: AbortSignal) => Promise<T>, opts: Opts = {}) {
  const { deps = [], pollMs } = opts
  const [data, setData] = useState<T | null>(null)
  const [err, setErr] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const fnRef = useRef(fn)
  const hasData = useRef(false)
  fnRef.current = fn

  const reload = useCallback(() => {
    const ctrl = new AbortController()
    setErr(null)
    if (!hasData.current) setLoading(true)
    fnRef
      .current(ctrl.signal)
      .then((row) => {
        if (ctrl.signal.aborted) return
        hasData.current = true
        setData(row)
        setErr(null)
      })
      .catch((e) => {
        if (ctrl.signal.aborted) return
        if (!hasData.current) setData(null)
        setErr(e)
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false)
      })
    return ctrl
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => {
    hasData.current = false
    let ctrl = reload()
    const onVis = () => {
      if (document.hidden) return
      ctrl.abort()
      ctrl = reload()
    }
    document.addEventListener("visibilitychange", onVis)
    let id: ReturnType<typeof setInterval> | undefined
    if (pollMs && pollMs > 0) {
      id = setInterval(() => {
        if (document.hidden) return
        ctrl.abort()
        ctrl = reload()
      }, pollMs)
    }
    return () => {
      ctrl.abort()
      document.removeEventListener("visibilitychange", onVis)
      if (id) clearInterval(id)
    }
  }, [reload, pollMs])

  return { data, err, loading, reload, setData }
}

export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  return useFetch((signal) => {
    void signal
    return fn()
  }, { deps })
}
