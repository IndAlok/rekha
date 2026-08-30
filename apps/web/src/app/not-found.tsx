import Link from "next/link"
import { PageHeader } from "@/components/ui/PageHeader"
import { Panel } from "@/components/ui/Panel"

export default function NotFound() {
  return (
    <>
      <PageHeader title="Page not found" lede="That route is not in this app." />
      <Panel>
        <Link className="btn btn-primary" href="/">
          Back to overview
        </Link>
      </Panel>
    </>
  )
}
