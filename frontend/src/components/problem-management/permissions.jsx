import { useParams } from 'react-router-dom';
import { useAuth } from '../../auth';
import { PageHeader, Panel, PanelPad } from '../../components';

export function Permissions() {
  const params = useParams();
  const problemId = params.id;
  const { isStaff, isManagerOrAdmin, isSupportOrAbove } = useAuth();

  const roleLabel = isManagerOrAdmin ? 'Manager or administrator'
    : isStaff ? 'IT staff'
      : isSupportOrAbove ? 'Support'
        : 'Employee (read-only)';

  return (
    <div>
      <PageHeader title="Permissions" sub={problemId ? `Problem #${problemId}` : 'Role-based access'} />
      <Panel>
        <PanelPad>
          <p>Your role: {roleLabel}</p>
          <h3>Available actions</h3>
          <ul>
            {isSupportOrAbove && <li>View problems, tasks, evidence and history</li>}
            {isStaff && <li>Create problems, tasks, evidence, workarounds, validations and exceptions</li>}
            {isManagerOrAdmin && (
              <li>Submit, accept, reject, start investigation, reopen, and approve or reject a root-cause analysis</li>
            )}
          </ul>
        </PanelPad>
      </Panel>
    </div>
  );
}
