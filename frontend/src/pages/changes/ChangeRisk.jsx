/*
 * Change Risk - risk assessment component for a change.
 * Route: #/changes/:id/risk
 */

import React, { useEffect, useState } from 'react';
import api from '../../api';
import { PageHeader } from '../../components';
import { useAuth } from '../../auth';
import { parseApiError } from '../../shared/changes-utils';

const FACTORS = [
  {
    key: 'service_impact_score',
    label: 'Service impact',
    help: '1 = minimal impact; 5 = widespread service outage.',
  },
  {
    key: 'user_impact_score',
    label: 'User impact',
    help: '1 = few users affected; 5 = organisation-wide impact.',
  },
  {
    key: 'complexity_score',
    label: 'Implementation complexity',
    help: '1 = simple, standard change; 5 = complex or novel change.',
  },
  {
    key: 'reversibility_score',
    label: 'Reversibility',
    help: '1 = easy rollback; 5 = difficult or impossible to reverse.',
  },
  {
    key: 'test_coverage_score',
    label: 'Test coverage',
    help: '1 = comprehensive testing; 5 = untested or unclear testing.',
  },
  {
    key: 'implementation_experience_score',
    label: 'Implementation experience',
    help: '1 = repeated, proven procedure; 5 = first-time implementation.',
  },
  {
    key: 'timing_risk_score',
    label: 'Timing risk',
    help: '1 = low-risk window; 5 = peak or business-critical window.',
  },
  {
    key: 'dependency_risk_score',
    label: 'Dependency risk',
    help: '1 = no dependencies; 5 = many blocking dependencies.',
  },
  {
    key: 'security_risk_score',
    label: 'Security risk',
    help: '1 = no security change; 5 = significant security configuration change.',
  },
  {
    key: 'data_integrity_risk_score',
    label: 'Data integrity risk',
    help: '1 = no data change; 5 = data migration or potential data-loss risk.',
  },
];

const RISK_LEVELS = [
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
  { value: 'critical', label: 'Critical' },
];

const EMPTY_SCORES = Object.fromEntries(
  FACTORS.map(({ key }) => [key, '']),
);

function getErrorMessage(error) {
  const parsed = parseApiError(error);

  return (
    parsed?.global ||
    error?.response?.data?.detail ||
    error?.response?.data?.message ||
    error?.message ||
    'Something went wrong. Please try again.'
  );
}

function getRecords(data) {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.results)) return data.results;
  return [];
}

function scoresFromAssessment(assessment) {
  if (!assessment) return { ...EMPTY_SCORES };

  return Object.fromEntries(
    FACTORS.map(({ key }) => [
      key,
      assessment[key] == null ? '' : String(assessment[key]),
    ]),
  );
}

function formatRiskLevel(level) {
  if (!level) return '—';
  return level.charAt(0).toUpperCase() + level.slice(1);
}

export function ChangeRisk({ match }) {
  const { role, isManagerOrAdmin } = useAuth();
  const id = match?.params?.id;

  const canManageRisk = isManagerOrAdmin ?? (
    role === 'it_manager' || role === 'system_admin'
  );

  const [change, setChange] = useState(null);
  const [assessments, setAssessments] = useState([]);
  const [scores, setScores] = useState({ ...EMPTY_SCORES });
  const [overrideLevel, setOverrideLevel] = useState('');
  const [overrideReason, setOverrideReason] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const latestAssessment = assessments[0] ?? null;
  const canCalculate = (
    canManageRisk &&
    change &&
    ['submitted', 'risk_assessment'].includes(change.status)
  );
  const canConfirm = (
    canManageRisk &&
    change?.status === 'risk_assessment' &&
    !!latestAssessment
  );

  async function loadData(changeId, showLoading = true) {
    if (!changeId) {
      setError('A change ID is required.');
      setLoading(false);
      return;
    }

    if (showLoading) setLoading(true);
    setError('');

    try {
      const [changeResponse, assessmentResponse] = await Promise.all([
        api.get(`/changes/${changeId}/`),
        api.get(`/changes/risk-assessments/?change=${changeId}`),
      ]);

      const nextChange = changeResponse.data;
      const nextAssessments = getRecords(assessmentResponse.data);

      setChange(nextChange);
      setAssessments(nextAssessments);
      setScores(scoresFromAssessment(nextAssessments[0]));
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setChange(null);
    setAssessments([]);
    setScores({ ...EMPTY_SCORES });
    setNotice('');
    loadData(id);
  }, [id]);

  function updateScore(key, value) {
    setScores((current) => ({ ...current, [key]: value }));
  }

  async function handleCalculate(event) {
    event.preventDefault();
    setError('');
    setNotice('');

    const missingFactor = FACTORS.find(({ key }) => {
      const value = Number(scores[key]);
      return !scores[key] || !Number.isInteger(value) || value < 1 || value > 5;
    });

    if (missingFactor) {
      setError(`Please select a score for ${missingFactor.label}.`);
      return;
    }

    if (overrideLevel && !overrideReason.trim()) {
      setError('Please provide a reason when overriding the calculated risk level.');
      return;
    }

    const payload = Object.fromEntries(
      FACTORS.map(({ key }) => [key, Number(scores[key])]),
    );

    if (overrideLevel) {
      payload.override_level = overrideLevel;
      payload.override_reason = overrideReason.trim();
    }

    setBusy(true);

    try {
      await api.post(`/changes/${id}/calculate_risk/`, payload);
      setNotice('Risk assessment calculated and saved successfully.');
      await loadData(id, false);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirm() {
    setError('');
    setNotice('');
    setBusy(true);

    try {
      await api.post(`/changes/${id}/confirm_risk/`, {});
      setNotice('Risk assessment confirmed. The change has moved to Technical Review.');
      await loadData(id, false);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return <div className="mt-3"><p>Loading risk assessment…</p></div>;
  }

  if (error && !change) {
    return (
      <div className="mt-3">
        <p className="text-danger" role="alert">{error}</p>
      </div>
    );
  }

  if (!change) {
    return <div className="mt-3"><p>Change request not found.</p></div>;
  }

  return (
    <div>
      <PageHeader
        title="Risk Assessment"
        sub={change.change_number || ''}
      />

      <div className="mt-3">
        <div className="mb-3">
          <p><strong>Change Number:</strong> {change.change_number || '—'}</p>
          <p><strong>Title:</strong> {change.title || '—'}</p>
          <p>
            <strong>Status:</strong>{' '}
            {String(change.status || '—').replaceAll('_', ' ')}
          </p>
          <p>
            <strong>Current risk level:</strong>{' '}
            {formatRiskLevel(change.risk_level)}
          </p>
          <p>
            <strong>Calculated risk score:</strong>{' '}
            {change.calculated_risk_score ?? '—'}
          </p>
        </div>

        {error && (
          <div className="alert alert-danger" role="alert">
            {error}
          </div>
        )}

        {notice && (
          <div className="alert alert-success" role="status">
            {notice}
          </div>
        )}

        <hr />

        <h4>Risk questionnaire</h4>
        <p>
          Score each factor from 1 (lowest risk) to 5 (highest risk).
          All ten factors are required for an assessment.
        </p>

        {canManageRisk ? (
          <form onSubmit={handleCalculate}>
            <div className="row">
              {FACTORS.map((factor) => (
                <div className="col-md-6 mb-3" key={factor.key}>
                  <label
                    className="form-label fw-semibold"
                    htmlFor={factor.key}
                  >
                    {factor.label}
                  </label>
                  <select
                    id={factor.key}
                    className="form-select"
                    value={scores[factor.key]}
                    onChange={(event) => updateScore(factor.key, event.target.value)}
                    disabled={busy}
                    required
                  >
                    <option value="">Choose a score</option>
                    {[1, 2, 3, 4, 5].map((score) => (
                      <option value={score} key={score}>
                        {score}
                      </option>
                    ))}
                  </select>
                  <small className="form-text text-muted">
                    {factor.help}
                  </small>
                </div>
              ))}
            </div>

            <div className="border rounded p-3 mt-2 mb-3">
              <h5>Risk level override (optional)</h5>
              <p className="text-muted">
                Leave this blank to use the automatically calculated risk level.
              </p>

              <div className="mb-3">
                <label className="form-label" htmlFor="override-level">
                  Override level
                </label>
                <select
                  id="override-level"
                  className="form-select"
                  value={overrideLevel}
                  onChange={(event) => setOverrideLevel(event.target.value)}
                  disabled={busy}
                >
                  <option value="">No override</option>
                  {RISK_LEVELS.map((level) => (
                    <option value={level.value} key={level.value}>
                      {level.label}
                    </option>
                  ))}
                </select>
              </div>

              {overrideLevel && (
                <div className="mb-3">
                  <label className="form-label" htmlFor="override-reason">
                    Override reason
                  </label>
                  <textarea
                    id="override-reason"
                    className="form-control"
                    rows="3"
                    value={overrideReason}
                    onChange={(event) => setOverrideReason(event.target.value)}
                    disabled={busy}
                    required
                  />
                </div>
              )}
            </div>

            {canCalculate ? (
              <button
                type="submit"
                className="btn btn-primary"
                disabled={busy}
              >
                {busy ? 'Saving…' : 'Calculate risk'}
              </button>
            ) : (
              <p className="text-muted">
                Risk calculation is available when the change is Submitted or
                already in Risk Assessment.
              </p>
            )}
          </form>
        ) : (
          <p className="text-muted">
            You have read-only access to this risk assessment.
          </p>
        )}

        <hr />

        <h4>Latest assessment</h4>

        {latestAssessment ? (
          <div className="card mb-3">
            <div className="card-body">
              <p>
                <strong>Assessment version:</strong>{' '}
                {latestAssessment.assessment_version}
              </p>
              <p>
                <strong>Total score:</strong>{' '}
                {latestAssessment.total_score}
              </p>
              <p>
                <strong>Calculated risk:</strong>{' '}
                {formatRiskLevel(latestAssessment.calculated_level)}
              </p>
              <p>
                <strong>Override level:</strong>{' '}
                {formatRiskLevel(latestAssessment.override_level)}
              </p>
              {latestAssessment.override_reason && (
                <p>
                  <strong>Override reason:</strong>{' '}
                  {latestAssessment.override_reason}
                </p>
              )}
              {latestAssessment.assessed_by_email && (
                <p>
                  <strong>Assessed by:</strong>{' '}
                  {latestAssessment.assessed_by_email}
                </p>
              )}
              {latestAssessment.assessed_at && (
                <p>
                  <strong>Assessed at:</strong>{' '}
                  {new Date(latestAssessment.assessed_at).toLocaleString()}
                </p>
              )}

              <h5 className="mt-3">Factor scores</h5>
              <ul className="mb-0">
                {FACTORS.map((factor) => (
                  <li key={factor.key}>
                    {factor.label}: {latestAssessment[factor.key] ?? '—'}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        ) : (
          <p>No risk assessment has been recorded for this change yet.</p>
        )}

        {canConfirm && (
          <div className="mb-4">
            <button
              type="button"
              className="btn btn-success"
              onClick={handleConfirm}
              disabled={busy}
            >
              {busy ? 'Processing…' : 'Confirm risk assessment'}
            </button>
          </div>
        )}

        <h4>Assessment history</h4>

        {assessments.length ? (
          <div className="table-responsive">
            <table className="table table-striped">
              <thead>
                <tr>
                  <th>Version</th>
                  <th>Total score</th>
                  <th>Calculated level</th>
                  <th>Override</th>
                  <th>Assessed at</th>
                </tr>
              </thead>
              <tbody>
                {assessments.map((assessment) => (
                  <tr key={assessment.id}>
                    <td>{assessment.assessment_version}</td>
                    <td>{assessment.total_score}</td>
                    <td>{formatRiskLevel(assessment.calculated_level)}</td>
                    <td>{formatRiskLevel(assessment.override_level)}</td>
                    <td>
                      {assessment.assessed_at
                        ? new Date(assessment.assessed_at).toLocaleString()
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p>No previous assessments.</p>
        )}
      </div>
    </div>
  );
}