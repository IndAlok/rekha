import type { KeyboardEvent, ThHTMLAttributes } from "react"

export function Table({ children }: { children: React.ReactNode }) {
  return (
    <div className="table-scroll">
      <table className="data">{children}</table>
    </div>
  )
}

export function Th({
  sort,
  active,
  dir,
  className = "",
  children,
  ...rest
}: ThHTMLAttributes<HTMLTableCellElement> & {
  sort?: () => void
  active?: boolean
  dir?: "asc" | "desc"
}) {
  const ariaSort = sort ? (active ? (dir === "asc" ? "ascending" : "descending") : "none") : undefined
  if (!sort) {
    return (
      <th className={className} {...rest}>
        {children}
      </th>
    )
  }
  return (
    <th className={className} aria-sort={ariaSort} {...rest}>
      <button className="th-btn" type="button" onClick={sort}>
        {children}
        {active ? (dir === "asc" ? " ^" : " v") : ""}
      </button>
    </th>
  )
}

export function Td({
  className = "",
  children,
  title,
}: {
  className?: string
  children: React.ReactNode
  title?: string
}) {
  return (
    <td className={className} title={title}>
      {children}
    </td>
  )
}

export function Tr({
  children,
  onSelect,
  selected,
}: {
  children: React.ReactNode
  onSelect?: () => void
  selected?: boolean
}) {
  const onKey = (e: KeyboardEvent<HTMLTableRowElement>) => {
    if (!onSelect) return
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault()
      onSelect()
    }
  }
  return (
    <tr
      className={onSelect ? "clickable" : undefined}
      tabIndex={onSelect ? 0 : undefined}
      aria-selected={onSelect ? Boolean(selected) : undefined}
      onClick={onSelect}
      onKeyDown={onKey}
    >
      {children}
    </tr>
  )
}

export function Pager({
  page,
  pages,
  total,
  onPage,
}: {
  page: number
  pages: number
  total: number
  onPage: (n: number) => void
}) {
  if (pages <= 1) return <p className="pager muted">{total} rows</p>
  return (
    <div className="pager">
      <span>
        {total} rows, page {page} of {pages}
      </span>
      <span className="btn-row">
        <button className="btn" type="button" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          Previous
        </button>
        <button className="btn" type="button" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Next
        </button>
      </span>
    </div>
  )
}
