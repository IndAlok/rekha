export function Skeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="stack" aria-hidden>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skel" style={{ height: i === 0 ? 28 : 14, width: i === 0 ? "40%" : "100%" }} />
      ))}
    </div>
  )
}

export function TableSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <div className="stack" aria-hidden>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skel" style={{ height: 36 }} />
      ))}
    </div>
  )
}
