"use client"

import { Button } from "@/components/ui/Button"
import { PageHeader } from "@/components/ui/PageHeader"
import { Panel } from "@/components/ui/Panel"

export default function ErrorView({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <>
      <PageHeader title="This page broke" />
      <Panel>
        <p className="lede">{error.message}</p>
        <Button variant="primary" onClick={() => reset()}>
          Retry
        </Button>
      </Panel>
    </>
  )
}
