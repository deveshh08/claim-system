import { CheckCircle2, AlertTriangle, XCircle, Clock, Ban } from 'lucide-react'

const CONFIG = {
  APPROVED:      { cls: 'badge-approved', Icon: CheckCircle2, label: 'Approved' },
  PARTIAL:       { cls: 'badge-partial',  Icon: AlertTriangle, label: 'Partial' },
  REJECTED:      { cls: 'badge-rejected', Icon: XCircle,       label: 'Rejected' },
  MANUAL_REVIEW: { cls: 'badge-manual',   Icon: Clock,         label: 'Manual Review' },
  null:          { cls: 'badge-halt',     Icon: Ban,           label: 'Halted' },
}

export default function DecisionBadge({ decision, size = 'md' }) {
  const key = decision ?? 'null'
  const { cls, Icon, label } = CONFIG[key] ?? CONFIG['null']
  const iconSize = size === 'lg' ? 16 : 13

  return (
    <span className={cls}>
      <Icon size={iconSize} />
      {label}
    </span>
  )
}
