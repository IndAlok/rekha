"use client"

import { Badge } from "@/components/ui/Badge"
import { EvalGate } from "@/components/EvalGate"
import { JsonView } from "@/components/ui/JsonView"
import { PageHeader } from "@/components/ui/PageHeader"
import { Panel } from "@/components/ui/Panel"
import { Table, Td } from "@/components/ui/DataTable"
import { TableSkeleton } from "@/components/ui/Skeleton"
import { api } from "@/lib/api"
import { hashShort } from "@/lib/format"
import { useFetch } from "@/lib/useLoad"

export default function PolicyPage() {
  const { data, err, loading, reload } = useFetch((signal) => api.policy(signal))
  if (err) return <EvalGate error={err} onReady={reload} />
  const rules = data?.rules || []
  const counts = data?.blocked_counts || {}

  return (
    <>
      <PageHeader
        title="Policy"
        lede={
          data
            ? `Version ${data.version}. Hash ${hashShort(data.policy_hash)}. YAML decides. The model may write a reason. It cannot pick a different tool.`
            : "Loading policy."
        }
      />
      {loading || !data ? <TableSkeleton /> : null}
      {data ? (
        <>
          <Panel title="Blocked in last eval">
            {Object.keys(counts).length === 0 ? (
              <p className="muted">No DENY rows in the last batch, or eval is empty.</p>
            ) : (
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {Object.entries(counts)
                  .sort((a, b) => b[1] - a[1])
                  .map(([rule, n]) => (
                    <li key={rule}>
                      <Badge>{rule}</Badge> {n}
                    </li>
                  ))}
              </ul>
            )}
          </Panel>
          <Panel title={`${rules.length} rules`}>
            <Table>
              <thead>
                <tr>
                  <th>id</th>
                  <th>effect</th>
                  <th>reason</th>
                  <th>applies</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((r) => (
                  <tr key={String(r.id)}>
                    <Td className="mono">{String(r.id)}</Td>
                    <Td>
                      <Badge>{String(r.effect)}</Badge>
                    </Td>
                    <Td>{String(r.reason_code || "")}</Td>
                    <Td className="muted">{Array.isArray(r.applies_to) ? r.applies_to.join(", ") : String(r.applies_to || "")}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Panel>
          <Panel title="Constants">
            <JsonView value={data.constants} label="constants.yaml" />
          </Panel>
          <Panel title="Caps">
            <JsonView value={data.caps} label="caps" />
          </Panel>
        </>
      ) : null}
    </>
  )
}
