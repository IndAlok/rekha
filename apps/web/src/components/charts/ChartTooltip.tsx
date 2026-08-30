export function ChartTooltip({
  x,
  y,
  children,
}: {
  x: number
  y: number
  children: React.ReactNode
}) {
  return (
    <div className="chart-tip" style={{ left: x, top: y }}>
      {children}
    </div>
  )
}
