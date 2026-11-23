import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { LoadingRows, PageHeader, Panel, PanelPad } from '../../components';
import {
  linkedAssets, linkedCIs, linkedProducts, linkedServices, linkedTickets,
} from '../../services/problem-management';

const GROUPS = [
  ['Tickets', linkedTickets, (r) => `${r.ticket_number}: ${r.title}`],
  ['Configuration items', linkedCIs, (r) => `${r.ci_number}: ${r.name}`],
  ['Assets', linkedAssets, (r) => `${r.asset_tag}: ${r.name}`],
  ['Services', linkedServices, (r) => r.name],
  ['Software products', linkedProducts, (r) => `${r.product_code}: ${r.name}`],
];

export function LinkedRecords({ problemId: problemIdProp }) {
  const params = useParams();
  const problemId = problemIdProp ?? params.id;
  const [groups, setGroups] = useState({});
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const entries = await Promise.all(GROUPS.map(async ([label, fn]) => {
      try {
        const data = await fn(problemId);
        return [label, { ok: true, rows: Array.isArray(data) ? data : data?.results ?? [] }];
      } catch {
        return [label, { ok: false, rows: [] }];
      }
    }));
    setGroups(Object.fromEntries(entries));
    setLoading(false);
  }, [problemId]);

  useEffect(() => { load(); }, [load]); // eslint-disable-line react/set-state-in-effect

  if (loading) return <LoadingRows n={4} />;

  return (
    <div>
      <PageHeader title="Linked Records" sub="Related tickets, changes, CIs, assets, services and products" />
      {GROUPS.map(([label, , render]) => (
        <Panel key={label}>
          <PanelPad>
            <h3>{label}</h3>
            {groups[label]?.ok === false
              ? <p className="muted">Section unavailable.</p>
              : groups[label]?.rows.length === 0
                ? <p className="muted">No linked {label.toLowerCase()}.</p>
                : groups[label].rows.map((r) => <p key={r.id}>{render(r)}</p>)}
          </PanelPad>
        </Panel>
      ))}
      <Panel>
        <PanelPad>
          <h3>Changes</h3>
          <p className="muted">Linked Changes are not supported by the backend (no relation exposed).</p>
        </PanelPad>
      </Panel>
    </div>
  );
}
