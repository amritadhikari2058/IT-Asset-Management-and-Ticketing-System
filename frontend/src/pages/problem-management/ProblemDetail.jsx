import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import api from '../../api';
import { AssetSelect, Badge, Button, Field, Input, LoadingRows, PageHeader, Panel, PanelPad, Select, Textarea } from '../../components';
import { Evidence } from '../../components/problem-management/evidence';
import { RCA } from '../../components/problem-management/rca';
import { Actions } from '../../components/problem-management/actions';
import { Workarounds } from '../../components/problem-management/workarounds';
import { Timeline } from '../../components/problem-management/timeline';
import { Exceptions } from '../../components/problem-management/exceptions';
import { Validations } from '../../components/problem-management/validations';
import { GovernedTransitions } from '../../components/problem-management/governed-transitions';
import { useAuth } from '../../auth';
import {
  createAssetLink, createCiLink, createKbLink, createServiceLink, createSoftwareLink,
  createTicketLink, deleteAssetLink, deleteCiLink, deleteKbLink, deleteServiceLink,
  deleteSoftwareLink, deleteTicketLink, linkedAssets, linkedCIs, linkedKBs, linkedProducts,
  linkedServices, linkedTickets, listTasks,
  problemDetail, problemHistory, problemReadiness, updateProblem,
} from '../../services/problem-management';
import { safeResults } from '../../shared/licensing-utils';

function Section({ title, state, children }) {
  return (
    <Panel>
      <PanelPad>
        <h3>{title}</h3>
        {state?.ok === false ? <p className="muted">Section unavailable.</p> : children}
      </PanelPad>
    </Panel>
  );
}

function listOf(value) {
  if (Array.isArray(value)) return value;
  return value?.results ?? [];
}

const PROBLEM_ROWS = [
  ['status', 'Status'],
  ['priority', 'Priority'],
  ['problem_type', 'Type'],
  ['owner_username', 'Owner'],
  ['service_name', 'Service'],
  ['category_name', 'Category'],
  ['environment', 'Environment'],
];

// Backend contract (ProblemKbArticleLink model/serializer): verified choices.
const KB_RELATION_TYPE_CHOICES = [
  ['reference', 'Reference'],
  ['workaround_source', 'Workaround Source'],
  ['root_cause_reference', 'Root-Cause Reference'],
  ['known_error_reference', 'Known-Error Reference'],
  ['procedure', 'Procedure'],
  ['other', 'Other'],
];

const KB_RELEVANCE_CHOICES = [
  ['confirmed', 'Confirmed'],
  ['high', 'High'],
  ['medium', 'Medium'],
  ['low', 'Low'],
  ['candidate', 'Candidate'],
];

// Backend contract (ProblemTicketLink model/serializer): verified choices.
// Ticket metadata fields are read-only; only the relationship fields below
// may be sent when creating a link.
const TICKET_RELATIONSHIP_TYPE_CHOICES = [
  ['caused_by', 'Caused By'],
  ['symptom_of', 'Symptom Of'],
  ['related_incident', 'Related Incident'],
  ['major_incident', 'Major Incident'],
  ['recurring_incident', 'Recurring Incident'],
  ['duplicate_pattern', 'Duplicate Pattern'],
  ['resolved_by_fix', 'Resolved By Fix'],
  ['validation_incident', 'Validation Incident'],
  ['monitoring_generated', 'Monitoring Generated'],
  ['other', 'Other'],
];

const TICKET_RELEVANCE_CHOICES = [
  ['confirmed', 'Confirmed'],
  ['high', 'High'],
  ['medium', 'Medium'],
  ['low', 'Low'],
  ['candidate', 'Candidate'],
];

// Backend contract (ProblemServiceLink model/serializer): verified choices.
const SERVICE_IMPACT_TYPE_CHOICES = [
  ['direct', 'Direct'],
  ['indirect', 'Indirect'],
  ['dependency', 'Dependency'],
  ['suspected', 'Suspected'],
  ['confirmed', 'Confirmed'],
  ['validation', 'Validation'],
  ['permanent_fix', 'Permanent Fix'],
];

const SERVICE_ROLE_CHOICES = [
  ['affected', 'Affected'],
  ['suspected_cause', 'Suspected Cause'],
  ['root_cause', 'Root Cause'],
  ['workaround_target', 'Workaround Target'],
  ['fix_target', 'Fix Target'],
  ['validation_target', 'Validation Target'],
  ['monitoring_target', 'Monitoring Target'],
];

const SERVICE_CONFIDENCE_CHOICES = [
  ['confirmed', 'Confirmed'],
  ['high', 'High'],
  ['medium', 'Medium'],
  ['low', 'Low'],
  ['unknown', 'Unknown'],
];

// The catalogue endpoint has no server-side text search and ignores page-size
// overrides, so the picker fetches a bounded number of 20-row pages and
// filters them locally.
const SERVICE_CATALOGUE_MAX_PAGES = 5;
const SERVICE_SEARCH_MAX_RESULTS = 20;

function serviceRows(value) {
  if (Array.isArray(value)) return value;
  return value?.results ?? [];
}

function matchesService(item, query) {
  const haystack = [
    item?.name, item?.description, item?.category, item?.ticket_category_name,
  ].filter(Boolean).join(' ').toLowerCase();
  return haystack.includes(query);
}

function toLabel(value) {
  return String(value || '').replaceAll('_', ' ').replace(/^./, (c) => c.toUpperCase());
}

function kbArticleHref(articleId) {
  return `#/kb/${articleId}`;
}

function assetHref(assetId) {
  return `#/assets/${assetId}`;
}

function ticketHref(ticketId) {
  return `#/tickets/${ticketId}`;
}

function serviceCatalogueHref() {
  return '#/services';
}

function ciHref(ciId) {
  return `#/cmdb/items/${ciId}`;
}

function softwareProductHref(productId) {
  return `#/software/products/${productId}`;
}

// Backend contract (ProblemAssetLink model/serializer): verified choices.
const ASSET_IMPACT_TYPE_CHOICES = [
  ['direct', 'Direct'],
  ['indirect', 'Indirect'],
  ['dependency', 'Dependency'],
  ['suspected', 'Suspected'],
  ['confirmed', 'Confirmed'],
  ['validation', 'Validation'],
  ['permanent_fix', 'Permanent Fix'],
];

const ASSET_ROLE_CHOICES = [
  ['affected', 'Affected'],
  ['suspected_cause', 'Suspected Cause'],
  ['root_cause', 'Root Cause'],
  ['workaround_target', 'Workaround Target'],
  ['fix_target', 'Fix Target'],
  ['validation_target', 'Validation Target'],
  ['monitoring_target', 'Monitoring Target'],
];

const ASSET_CONFIDENCE_CHOICES = [
  ['confirmed', 'Confirmed'],
  ['high', 'High'],
  ['medium', 'Medium'],
  ['low', 'Low'],
  ['unknown', 'Unknown'],
];

export function ProblemDetail({ problemId: problemIdProp }) {
  const params = useParams();
  const problemId = problemIdProp ?? params.id;
  const { user, isStaff, isManagerOrAdmin, isSupportOrAbove } = useAuth();
  const [problem, setProblem] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [sections, setSections] = useState({});
  const [kbSearch, setKbSearch] = useState('');
  const [kbResults, setKbResults] = useState([]);
  const [kbSearching, setKbSearching] = useState(false);
  const [kbSearchError, setKbSearchError] = useState('');
  const [kbForm, setKbForm] = useState({
    article: null, relation_type: 'reference', relevance: 'medium', note: '',
  });
  const [kbAdding, setKbAdding] = useState(false);
  const [kbRemoving, setKbRemoving] = useState(new Set());
  const [kbMessage, setKbMessage] = useState('');
  const [kbError, setKbError] = useState('');
  const [serviceSearch, setServiceSearch] = useState('');
  const [serviceSelectedLabel, setServiceSelectedLabel] = useState('');
  const serviceCatalogueCache = useRef({ loaded: false, items: [] });
  const [serviceResults, setServiceResults] = useState([]);
  const [serviceSearching, setServiceSearching] = useState(false);
  const [serviceSearchError, setServiceSearchError] = useState('');
  const [serviceForm, setServiceForm] = useState({
    service: null, impact_type: 'direct', role: 'affected', confidence: 'medium', notes: '',
  });
  const [serviceAdding, setServiceAdding] = useState(false);
  const [serviceRemoving, setServiceRemoving] = useState(new Set());
  const [serviceMessage, setServiceMessage] = useState('');
  const [serviceError, setServiceError] = useState('');
  const [ticketSearch, setTicketSearch] = useState('');
  const [ticketSelectedLabel, setTicketSelectedLabel] = useState('');
  const [ticketResults, setTicketResults] = useState([]);
  const [ticketSearching, setTicketSearching] = useState(false);
  const [ticketSearchError, setTicketSearchError] = useState('');
  const [ticketForm, setTicketForm] = useState({
    ticket: null, relationship_type: 'related_incident', relevance: 'medium',
    is_primary: false, note: '',
  });
  const [ticketAdding, setTicketAdding] = useState(false);
  const [ticketRemoving, setTicketRemoving] = useState(new Set());
  const [ticketMessage, setTicketMessage] = useState('');
  const [ticketError, setTicketError] = useState('');
  const [assetForm, setAssetForm] = useState({
    asset: '', impact_type: 'direct', role: 'affected', confidence: 'medium', notes: '',
  });
  const [assetAdding, setAssetAdding] = useState(false);
  const [assetRemoving, setAssetRemoving] = useState(new Set());
  const [assetMessage, setAssetMessage] = useState('');
  const [assetError, setAssetError] = useState('');
  const [ciSearch, setCiSearch] = useState('');
  const [ciResults, setCiResults] = useState([]);
  const [ciSearching, setCiSearching] = useState(false);
  const [ciSearchError, setCiSearchError] = useState('');
  const [ciForm, setCiForm] = useState({
    ci: null, impact_type: 'direct', role: 'affected', confidence: 'medium', notes: '',
  });
  const [ciAdding, setCiAdding] = useState(false);
  const [ciRemoving, setCiRemoving] = useState(new Set());
  const [ciMessage, setCiMessage] = useState('');
  const [ciError, setCiError] = useState('');
  const [productSearch, setProductSearch] = useState('');
  const [productResults, setProductResults] = useState([]);
  const [productSearching, setProductSearching] = useState(false);
  const [productSearchError, setProductSearchError] = useState('');
  const [productForm, setProductForm] = useState({
    product: null, impact_type: 'direct', role: 'affected', confidence: 'medium', notes: '',
  });
  const [productAdding, setProductAdding] = useState(false);
  const [productRemoving, setProductRemoving] = useState(new Set());
  const [productMessage, setProductMessage] = useState('');
  const [productError, setProductError] = useState('');
  const [editingProblemFields, setEditingProblemFields] = useState(false);
  const [savingProblemFields, setSavingProblemFields] = useState(false);
  const problemSaveLock = useRef(false);
  const [problemFieldsError, setProblemFieldsError] = useState('');
  const [problemFields, setProblemFields] = useState({
    title: problem?.title ?? '',
    description: problem?.description ?? '',
    priority: problem?.priority ?? '',
    severity: problem?.severity ?? '',
    impact: problem?.impact ?? '',
    urgency: problem?.urgency ?? '',
    criticality: problem?.criticality ?? '',
    owner: problem?.owner_username ?? '',
    problem_manager: problem?.problem_manager_username ?? '',
    assigned_group: problem?.assigned_group ?? '',
    department: problem?.department_name ?? '',
    service: problem?.service_name ?? '',
    category: problem?.category_name ?? '',
    subcategory: problem?.subcategory ?? '',
    environment: problem?.environment ?? '',
    detection_method: problem?.detection_method ?? '',
    target_resolution_date: problem?.target_resolution_date ? problem.target_resolution_date.slice(0, 10) : '',
    next_review_at: problem?.next_review_at ? problem.next_review_at.slice(0, 10) : '',
  });

  useEffect(() => {
    let active = true;
    setLoading(true);
    problemDetail(problemId)
      .then((data) => {
        if (active) {
          const p = data?.data ?? data;
          setProblem(p);
          // Initialize form with current problem values
          setProblemFields({
            title: p.title ?? '',
            description: p.description ?? '',
            priority: p.priority ?? '',
            severity: p.severity ?? '',
            impact: p.impact ?? '',
            urgency: p.urgency ?? '',
            criticality: p.criticality ?? '',
            owner: p.owner?.toString() ?? '',
            problem_manager: p.problem_manager?.toString() ?? '',
            assigned_group: p.assigned_group ?? '',
            department: p.department ?? '',
            service: p.service?.toString() ?? '',
            category: p.category?.toString() ?? '',
            subcategory: p.subcategory ?? '',
            environment: p.environment ?? '',
            detection_method: p.detection_method ?? '',
            target_resolution_date: p.target_resolution_date ? p.target_resolution_date.slice(0, 10) : '',
            next_review_at: p.next_review_at ? p.next_review_at.slice(0, 10) : '',
          });
        }
      })
      .catch(() => { if (active) setError('Could not load problem detail.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [problemId]);

  const loadSection = useCallback(async (key, fn) => {
    try {
      const data = await fn();
      setSections((s) => ({ ...s, [key]: { ok: true, data } }));
      return data;
    } catch {
      setSections((s) => ({ ...s, [key]: { ok: false, data: null } }));
      return null;
    }
  }, []);

  // Each section loads independently: one failing endpoint degrades that
  // section only and never blanks the page.
  useEffect(() => {
    if (!problemId) return () => {};
    let active = true;
    const loaders = [
      ['tasks', () => listTasks(problemId)],
      ['history', () => problemHistory(problemId)],
      ['readiness', () => problemReadiness(problemId)],
      ['tickets', () => linkedTickets(problemId)],
      ['cis', () => linkedCIs(problemId)],
      ['assets', () => linkedAssets(problemId)],
      ['services', () => linkedServices(problemId)],
      ['products', () => linkedProducts(problemId)],
      ['kbs', () => linkedKBs(problemId)],
    ];
    loaders.forEach(([key, fn]) => {
      Promise.resolve()
        .then(fn)
        .then((data) => { if (active) setSections((s) => ({ ...s, [key]: { ok: true, data } })); })
        .catch(() => { if (active) setSections((s) => ({ ...s, [key]: { ok: false, data: null } })); });
    });
    return () => { active = false; };
  }, [problemId, loadSection]);

  useEffect(() => {
    if (!isStaff) return () => {};
    const q = kbSearch.trim();
    if (q.length < 2) {
      setKbResults([]);
      setKbSearchError('');
      setKbSearching(false);
      return () => {};
    }
    let active = true;
    const controller = new AbortController();
    setKbSearching(true);
    setKbSearchError('');
    const timer = setTimeout(async () => {
      try {
        const response = await api.get('/assets/knowledge-base/', {
          params: { q, page_size: 8 },
          signal: controller.signal,
        });
        if (!active) return;
        const data = response?.data;
        setKbResults(Array.isArray(data) ? data : data?.results ?? []);
      } catch (err) {
        if (!active || controller.signal.aborted) return;
        setKbResults([]);
        setKbSearchError('Could not search knowledge base articles.');
      } finally {
        if (active) setKbSearching(false);
      }
    }, 250);
    return () => {
      active = false;
      clearTimeout(timer);
      controller.abort();
    };
  }, [isStaff, kbSearch]);

  // Tickets are searched per problem detail with the verified backend query
  // parameter. The abort flag drops responses from superseded queries.
  useEffect(() => {
    if (!isStaff) return undefined;
    const q = ticketSearch.trim();
    if (q.length < 2 || q === ticketSelectedLabel) {
      setTicketResults([]);
      setTicketSearching(false);
      setTicketSearchError('');
      return undefined;
    }
    let active = true;
    const controller = new AbortController();
    setTicketSearching(true);
    setTicketSearchError('');
    const timer = setTimeout(async () => {
      try {
        const response = await api.get('/tickets/', {
          params: { q },
          signal: controller.signal,
        });
        if (!active || controller.signal.aborted) return;
        const data = response?.data;
        setTicketResults(Array.isArray(data) ? data : data?.results ?? []);
      } catch (err) {
        if (!active || controller.signal.aborted) return;
        setTicketResults([]);
        setTicketSearchError('Could not search tickets.');
      } finally {
        if (active) setTicketSearching(false);
      }
    }, 300);
    return () => {
      active = false;
      clearTimeout(timer);
      controller.abort();
    };
  }, [isStaff, ticketSearch, ticketSelectedLabel]);

  const loadServiceCatalogue = useCallback(async (signal) => {
    const rows = [];
    for (let page = 1; page <= SERVICE_CATALOGUE_MAX_PAGES; page += 1) {
      // eslint-disable-next-line no-await-in-loop
      const response = await api.get('/services/catalogue/', {
        params: { page },
        signal,
      });
      if (signal?.aborted) return rows;
      const data = response?.data;
      const pageRows = serviceRows(data);
      rows.push(...pageRows);
      if (!Array.isArray(data) && data?.next == null) break;
      if (pageRows.length === 0) break;
    }
    return rows;
  }, []);

  // The catalogue has no usable text filter, so a debounced bounded fetch is
  // cached once and filtered locally. Abort/active checks drop stale queries.
  useEffect(() => {
    if (!isStaff) return undefined;
    const query = serviceSearch.trim().toLowerCase();
    if (query.length < 2 || query === serviceSelectedLabel.trim().toLowerCase()) {
      setServiceResults([]);
      setServiceSearching(false);
      setServiceSearchError('');
      return undefined;
    }
    let active = true;
    const controller = new AbortController();
    setServiceSearching(true);
    setServiceSearchError('');
    const timer = setTimeout(async () => {
      const cache = serviceCatalogueCache.current;
      try {
        const items = cache.loaded
          ? cache.items
          : await loadServiceCatalogue(controller.signal);
        if (!active || controller.signal.aborted) return;
        if (!cache.loaded) {
          cache.items = items;
          cache.loaded = true;
        }
        setServiceResults(
          items.filter((item) => matchesService(item, query)).slice(0, SERVICE_SEARCH_MAX_RESULTS),
        );
      } catch (err) {
        if (!active || controller.signal.aborted) return;
        cache.items = [];
        cache.loaded = false;
        setServiceResults([]);
        setServiceSearchError('Could not search services.');
      } finally {
        if (active) setServiceSearching(false);
      }
    }, 300);
    return () => {
      active = false;
      clearTimeout(timer);
      controller.abort();
    };
  }, [isStaff, serviceSearch, serviceSelectedLabel, loadServiceCatalogue]);

  const handleProblemFieldsChange = useCallback((e) => {
    const { name, value } = e.target;
    setProblemFields((prev) => ({ ...prev, [name]: value }));
  }, []);

  const handleEditProblemFields = useCallback(() => {
    if (!isStaff) return;

    setProblemFields({
      title: problem?.title ?? '',
      description: problem?.description ?? '',
      priority: problem?.priority ?? '',
      severity: problem?.severity ?? '',
      impact: problem?.impact ?? '',
      urgency: problem?.urgency ?? '',
      criticality: problem?.criticality ?? '',
      owner: problem?.owner?.toString() ?? '',
      problem_manager: problem?.problem_manager?.toString() ?? '',
      assigned_group: problem?.assigned_group?.toString() ?? '',
      department: problem?.department?.toString() ?? '',
      service: problem?.service?.toString() ?? '',
      category: problem?.category?.toString() ?? '',
      subcategory: problem?.subcategory ?? '',
      environment: problem?.environment ?? '',
      detection_method: problem?.detection_method ?? '',
      target_resolution_date: problem?.target_resolution_date
        ? problem.target_resolution_date.slice(0, 10) : '',
      next_review_at: problem?.next_review_at
        ? problem.next_review_at.slice(0, 10) : '',
    });
    setProblemFieldsError('');
    setEditingProblemFields(true);
  }, [isStaff, problem]);

  const handleCancelProblemFields = useCallback(() => {
    setProblemFields({
      title: problem?.title ?? '',
      description: problem?.description ?? '',
      priority: problem?.priority ?? '',
      severity: problem?.severity ?? '',
      impact: problem?.impact ?? '',
      urgency: problem?.urgency ?? '',
      criticality: problem?.criticality ?? '',
      owner: problem?.owner?.toString() ?? '',
      problem_manager: problem?.problem_manager?.toString() ?? '',
      assigned_group: problem?.assigned_group?.toString() ?? '',
      department: problem?.department?.toString() ?? '',
      service: problem?.service?.toString() ?? '',
      category: problem?.category?.toString() ?? '',
      subcategory: problem?.subcategory ?? '',
      environment: problem?.environment ?? '',
      detection_method: problem?.detection_method ?? '',
      target_resolution_date: problem?.target_resolution_date
        ? problem.target_resolution_date.slice(0, 10) : '',
      next_review_at: problem?.next_review_at
        ? problem.next_review_at.slice(0, 10) : '',
    });
    setProblemFieldsError('');
    setEditingProblemFields(false);
  }, [problem]);

  const handleSaveProblemFields = useCallback(async () => {
    if (!isStaff || problemSaveLock.current) return;

    problemSaveLock.current = true;
    setSavingProblemFields(true);
    setProblemFieldsError('');

    try {
      const updatePayload = {
        title: problemFields.title,
        description: problemFields.description,
        priority: problemFields.priority,
        severity: problemFields.severity,
        impact: problemFields.impact,
        urgency: problemFields.urgency,
        criticality: problemFields.criticality,
        subcategory: problemFields.subcategory,
        environment: problemFields.environment,
        detection_method: problemFields.detection_method,
        ...(isManagerOrAdmin ? {
          target_resolution_date: problemFields.target_resolution_date || null,
          next_review_at: problemFields.next_review_at || null,
        } : {}),
      };

      await updateProblem(problemId, updatePayload, problem?.record_version);
      setProblem((current) => ({ ...current, ...updatePayload }));
      setEditingProblemFields(false);

      try {
        const data = await problemDetail(problemId);
        setProblem(data?.data ?? data);
      } catch {
        // The update succeeded; retain the locally updated record.
      }
    } catch (e) {
      const status = e.response?.status;

      if (status === 409) {
        try {
          const data = await problemDetail(problemId);
          setProblem(data?.data ?? data);
        } catch {
          // Keep the user's entered values if refresh fails.
        }
        setProblemFieldsError(
          'The problem record changed while you were editing. Review the latest record and try again.'
        );
      } else if (status === 400) {
        setProblemFieldsError(
          'Could not save problem fields. Please check the submitted values.'
        );
      } else if (status === 403) {
        setProblemFieldsError('You do not have permission to edit problem fields.');
      } else {
        setProblemFieldsError('Failed to save problem fields. Please try again.');
      }
    } finally {
      problemSaveLock.current = false;
      setSavingProblemFields(false);
    }
  }, [isStaff, isManagerOrAdmin, problemId, problemFields, problem?.record_version]);

  const refreshKbLinks = useCallback(async () => {
    await loadSection('kbs', () => linkedKBs(problemId));
  }, [loadSection, problemId]);

  const refreshTicketLinks = useCallback(async () => {
    await loadSection('tickets', () => linkedTickets(problemId));
  }, [loadSection, problemId]);

  const refreshServiceLinks = useCallback(async () => {
    await loadSection('services', () => linkedServices(problemId));
  }, [loadSection, problemId]);

  const refreshAssetLinks = useCallback(async () => {
    await loadSection('assets', () => linkedAssets(problemId));
  }, [loadSection, problemId]);

  const refreshCiLinks = useCallback(async () => {
    await loadSection('cis', () => linkedCIs(problemId));
  }, [loadSection, problemId]);

  const refreshProductLinks = useCallback(async () => {
    await loadSection('products', () => linkedProducts(problemId));
  }, [loadSection, problemId]);

  const handleKbSearchChange = useCallback((e) => {
    setKbSearch(e.target.value);
    setKbError('');
  }, []);

  const handleSelectKbArticle = useCallback((article) => {
    setKbForm((prev) => ({ ...prev, article }));
    setKbSearch(article?.title ?? '');
    setKbResults([]);
    setKbSearchError('');
    setKbError('');
  }, []);

  const handleKbFormChange = useCallback((e) => {
    const { name, value } = e.target;
    setKbForm((prev) => ({ ...prev, [name]: value }));
  }, []);

  const formatKbError = useCallback((err, fallback = 'Failed to update KB article link.') => {
    const data = err?.response?.data;
    if (!data) return fallback;
    if (typeof data === 'string') return data;
    if (data.detail) return String(data.detail);
    const fieldMessages = Object.entries(data)
      .flatMap(([field, value]) => {
        const messages = Array.isArray(value) ? value : [value];
        return messages.map((m) => `${field}: ${m}`);
      })
      .filter(Boolean);
    return fieldMessages[0] || fallback;
  }, []);

  const handleTicketSearchChange = useCallback((e) => {
    setTicketSearch(e.target.value);
    setTicketSelectedLabel('');
    setTicketForm((prev) => ({ ...prev, ticket: null }));
    setTicketError('');
  }, []);

  const handleSelectTicket = useCallback((ticket) => {
    const ticketId = Number(ticket?.id);
    if (!Number.isInteger(ticketId) || !ticketId) return;
    setTicketForm((prev) => ({ ...prev, ticket: ticketId }));
    const label = ticket.title ? `${ticket.title} (#${ticketId})` : `Ticket #${ticketId}`;
    setTicketSearch(label);
    setTicketSelectedLabel(label);
    setTicketResults([]);
    setTicketSearchError('');
    setTicketError('');
  }, []);

  const handleTicketFormChange = useCallback((e) => {
    const { name, value, type, checked } = e.target;
    setTicketForm((prev) => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value,
    }));
  }, []);

  const handleAddTicketLink = useCallback(async (e) => {
    e.preventDefault();
    if (!isStaff || ticketAdding) return;
    const ticketId = Number(ticketForm.ticket);
    if (!Number.isInteger(ticketId) || !ticketId) {
      setTicketError('Select a ticket from search results before linking.');
      return;
    }
    setTicketAdding(true);
    setTicketError('');
    setTicketMessage('');
    try {
      await createTicketLink({
        problem: Number(problemId),
        ticket: ticketId,
        relationship_type: ticketForm.relationship_type,
        relevance: ticketForm.relevance,
        is_primary: Boolean(ticketForm.is_primary),
        note: ticketForm.note?.trim() || '',
      });
      setTicketForm({
        ticket: null, relationship_type: 'related_incident', relevance: 'medium',
        is_primary: false, note: '',
      });
      setTicketSearch('');
      setTicketSelectedLabel('');
      setTicketResults([]);
      setTicketSearchError('');
      setTicketMessage('Ticket linked.');
      await refreshTicketLinks();
    } catch (err) {
      setTicketError(formatKbError(err, 'Failed to update ticket link.'));
    } finally {
      setTicketAdding(false);
    }
  }, [isStaff, ticketAdding, ticketForm, problemId, refreshTicketLinks, formatKbError]);

  const handleRemoveTicketLink = useCallback(async (linkId) => {
    if (!isStaff || ticketRemoving.has(linkId)) return;
    const confirmed = typeof window !== 'undefined' && typeof window.confirm === 'function'
      ? window.confirm('Remove this ticket link?')
      : true;
    if (!confirmed) return;
    setTicketRemoving((prev) => new Set([...prev, linkId]));
    setTicketError('');
    setTicketMessage('');
    try {
      await deleteTicketLink(linkId);
      setTicketMessage('Ticket link removed.');
      await refreshTicketLinks();
    } catch (err) {
      setTicketError(formatKbError(err, 'Failed to update ticket link.'));
    } finally {
      setTicketRemoving((prev) => {
        const next = new Set(prev);
        next.delete(linkId);
        return next;
      });
    }
  }, [isStaff, ticketRemoving, refreshTicketLinks, formatKbError]);

  const handleServiceSearchChange = useCallback((e) => {
    setServiceSearch(e.target.value);
    setServiceSelectedLabel('');
    setServiceForm((prev) => ({ ...prev, service: null }));
    setServiceError('');
  }, []);

  const handleSelectService = useCallback((service) => {
    const serviceId = Number(service?.id);
    if (!Number.isInteger(serviceId) || !serviceId) return;
    setServiceForm((prev) => ({ ...prev, service: serviceId }));
    const label = service.name ? `${service.name} (#${serviceId})` : `Service #${serviceId}`;
    setServiceSearch(label);
    setServiceSelectedLabel(label);
    setServiceResults([]);
    setServiceSearchError('');
    setServiceError('');
  }, []);

  const handleServiceFormChange = useCallback((e) => {
    const { name, value } = e.target;
    setServiceForm((prev) => ({ ...prev, [name]: value }));
  }, []);

  const handleAddServiceLink = useCallback(async (e) => {
    e.preventDefault();
    if (!isStaff || serviceAdding) return;
    const serviceId = Number(serviceForm.service);
    if (!Number.isInteger(serviceId) || !serviceId) {
      setServiceError('Select a service from search results before linking.');
      return;
    }
    setServiceAdding(true);
    setServiceError('');
    setServiceMessage('');
    try {
      await createServiceLink({
        problem: Number(problemId),
        service: serviceId,
        impact_type: serviceForm.impact_type,
        role: serviceForm.role,
        confidence: serviceForm.confidence,
        notes: serviceForm.notes?.trim() || '',
      });
      setServiceForm({
        service: null, impact_type: 'direct', role: 'affected', confidence: 'medium', notes: '',
      });
      setServiceSearch('');
      setServiceSelectedLabel('');
      setServiceResults([]);
      setServiceSearchError('');
      setServiceMessage('Service linked.');
      await refreshServiceLinks();
    } catch (err) {
      setServiceError(formatKbError(err, 'Failed to update service link.'));
    } finally {
      setServiceAdding(false);
    }
  }, [
    isStaff, serviceAdding, serviceForm, problemId, refreshServiceLinks, formatKbError,
  ]);

  const handleRemoveServiceLink = useCallback(async (linkId) => {
    if (!isStaff || serviceRemoving.has(linkId)) return;
    const confirmed = typeof window !== 'undefined' && typeof window.confirm === 'function'
      ? window.confirm('Remove this service link?')
      : true;
    if (!confirmed) return;
    setServiceRemoving((prev) => new Set([...prev, linkId]));
    setServiceError('');
    setServiceMessage('');
    try {
      await deleteServiceLink(linkId);
      setServiceMessage('Service link removed.');
      await refreshServiceLinks();
    } catch (err) {
      setServiceError(formatKbError(err, 'Failed to update service link.'));
    } finally {
      setServiceRemoving((prev) => {
        const next = new Set(prev);
        next.delete(linkId);
        return next;
      });
    }
  }, [isStaff, serviceRemoving, refreshServiceLinks, formatKbError]);

  const handleAddKbLink = useCallback(async (e) => {
    e.preventDefault();
    if (!isStaff || kbAdding) return;
    if (!kbForm.article?.id) {
      setKbError('Select a KB article from search results before linking.');
      return;
    }
    setKbAdding(true);
    setKbError('');
    setKbMessage('');
    try {
      await createKbLink({
        problem: Number(problemId),
        article: kbForm.article.id,
        relation_type: kbForm.relation_type,
        relevance: kbForm.relevance,
        note: kbForm.note?.trim() || '',
      });
      setKbForm({ article: null, relation_type: 'reference', relevance: 'medium', note: '' });
      setKbSearch('');
      setKbResults([]);
      setKbSearchError('');
      setKbMessage('KB article linked.');
      await refreshKbLinks();
    } catch (err) {
      setKbError(formatKbError(err));
    } finally {
      setKbAdding(false);
    }
  }, [isStaff, kbAdding, kbForm, problemId, refreshKbLinks, formatKbError]);

  const handleRemoveKbLink = useCallback(async (linkId) => {
    if (!isStaff || kbRemoving.has(linkId)) return;
    const confirmed = typeof window !== 'undefined' && typeof window.confirm === 'function'
      ? window.confirm('Remove this KB article link?')
      : true;
    if (!confirmed) return;
    setKbRemoving((prev) => new Set([...prev, linkId]));
    setKbError('');
    setKbMessage('');
    try {
      await deleteKbLink(linkId);
      setKbMessage('KB article link removed.');
      await refreshKbLinks();
    } catch (err) {
      setKbError(formatKbError(err));
    } finally {
      setKbRemoving((prev) => {
        const next = new Set(prev);
        next.delete(linkId);
        return next;
      });
    }
  }, [isStaff, kbRemoving, refreshKbLinks, formatKbError]);

  const handleAssetFormChange = useCallback((e) => {
    const { name, value } = e.target;
    setAssetForm((prev) => ({ ...prev, [name]: value }));
  }, []);

  const handleAssetSelect = useCallback((value) => {
    setAssetForm((prev) => ({ ...prev, asset: value }));
    setAssetError('');
  }, []);

  const handleAddAssetLink = useCallback(async (e) => {
    e.preventDefault();
    if (!isStaff || assetAdding) return;
    const assetId = Number(assetForm.asset);
    if (!assetId) {
      setAssetError('Select an asset before linking.');
      return;
    }
    setAssetAdding(true);
    setAssetError('');
    setAssetMessage('');
    try {
      await createAssetLink({
        problem: Number(problemId),
        asset: assetId,
        impact_type: assetForm.impact_type,
        role: assetForm.role,
        confidence: assetForm.confidence,
        notes: assetForm.notes?.trim() || '',
      });
      setAssetForm({ asset: '', impact_type: 'direct', role: 'affected', confidence: 'medium', notes: '' });
      setAssetMessage('Asset linked.');
      await refreshAssetLinks();
    } catch (err) {
      setAssetError(formatKbError(err));
    } finally {
      setAssetAdding(false);
    }
  }, [isStaff, assetAdding, assetForm, problemId, refreshAssetLinks, formatKbError]);

  const handleRemoveAssetLink = useCallback(async (linkId) => {
    if (!isStaff || assetRemoving.has(linkId)) return;
    const confirmed = typeof window !== 'undefined' && typeof window.confirm === 'function'
      ? window.confirm('Remove this asset link?')
      : true;
    if (!confirmed) return;
    setAssetRemoving((prev) => new Set([...prev, linkId]));
    setAssetError('');
    setAssetMessage('');
    try {
      await deleteAssetLink(linkId);
      setAssetMessage('Asset link removed.');
      await refreshAssetLinks();
    } catch (err) {
      setAssetError(formatKbError(err));
    } finally {
      setAssetRemoving((prev) => {
        const next = new Set(prev);
        next.delete(linkId);
        return next;
      });
    }
  }, [isStaff, assetRemoving, refreshAssetLinks, formatKbError]);

  useEffect(() => {
    const q = ciSearch.trim();
    if (!isStaff || q.length < 2) {
      setCiResults([]);
      setCiSearching(false);
      setCiSearchError('');
      return undefined;
    }
    let active = true;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setCiSearching(true);
      setCiSearchError('');
      try {
        const response = await api.get('/cmdb/items/', {
          params: { search: q },
          signal: controller.signal,
        });
        if (!active) return;
        const data = response.data;
        setCiResults(Array.isArray(data) ? data : (data?.results ?? []));
      } catch (err) {
        if (!active || controller.signal.aborted) return;
        setCiResults([]);
        setCiSearchError('Failed to search configuration items.');
      } finally {
        if (active) setCiSearching(false);
      }
    }, 300);
    return () => {
      active = false;
      clearTimeout(timer);
      controller.abort();
    };
  }, [isStaff, ciSearch]);

  useEffect(() => {
    const q = productSearch.trim();
    if (!isStaff || q.length < 2) {
      setProductResults([]);
      setProductSearching(false);
      setProductSearchError('');
      return undefined;
    }
    let active = true;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setProductSearching(true);
      setProductSearchError('');
      try {
        const response = await api.get('/licensing/products/', {
          params: { search: q, page_size: 10 },
          signal: controller.signal,
        });
        if (!active) return;
        const data = response.data;
        setProductResults(safeResults(data).slice(0, 10));
      } catch (err) {
        if (!active || controller.signal.aborted) return;
        setProductResults([]);
        setProductSearchError('Failed to search software products.');
      } finally {
        if (active) setProductSearching(false);
      }
    }, 300);
    return () => {
      active = false;
      clearTimeout(timer);
      controller.abort();
    };
  }, [isStaff, productSearch]);

  const handleCiSearchChange = useCallback((e) => {
    setCiSearch(e.target.value);
    setCiError('');
  }, []);

  const handleSelectCi = useCallback((ci) => {
    setCiForm((prev) => ({ ...prev, ci }));
    setCiSearch(ci?.name ? `${ci.ci_number ? `${ci.ci_number} - ` : ''}${ci.name}` : (ci?.ci_number ?? ''));
    setCiResults([]);
    setCiSearchError('');
    setCiError('');
  }, []);

  const handleCiFormChange = useCallback((e) => {
    const { name, value } = e.target;
    setCiForm((prev) => ({ ...prev, [name]: value }));
  }, []);

  const handleAddCiLink = useCallback(async (e) => {
    e.preventDefault();
    if (!isStaff || ciAdding) return;
    if (!ciForm.ci?.id) {
      setCiError('Select a configuration item from search results before linking.');
      return;
    }
    setCiAdding(true);
    setCiError('');
    setCiMessage('');
    try {
      await createCiLink({
        problem: Number(problemId),
        configuration_item: ciForm.ci.id,
        impact_type: ciForm.impact_type,
        role: ciForm.role,
        confidence: ciForm.confidence,
        notes: ciForm.notes?.trim() || '',
      });
      setCiForm({ ci: null, impact_type: 'direct', role: 'affected', confidence: 'medium', notes: '' });
      setCiSearch('');
      setCiResults([]);
      setCiSearchError('');
      setCiMessage('Configuration item linked.');
      await refreshCiLinks();
    } catch (err) {
      setCiError(formatKbError(err));
    } finally {
      setCiAdding(false);
    }
  }, [isStaff, ciAdding, ciForm, problemId, refreshCiLinks, formatKbError]);

  const handleRemoveCiLink = useCallback(async (linkId) => {
    if (!isStaff || ciRemoving.has(linkId)) return;
    const confirmed = typeof window !== 'undefined' && typeof window.confirm === 'function'
      ? window.confirm('Remove this configuration item link?')
      : true;
    if (!confirmed) return;
    setCiRemoving((prev) => new Set([...prev, linkId]));
    setCiError('');
    setCiMessage('');
    try {
      await deleteCiLink(linkId);
      setCiMessage('Configuration item link removed.');
      await refreshCiLinks();
    } catch (err) {
      setCiError(formatKbError(err));
    } finally {
      setCiRemoving((prev) => {
        const next = new Set(prev);
        next.delete(linkId);
        return next;
      });
    }
  }, [isStaff, ciRemoving, refreshCiLinks, formatKbError]);

  const handleProductSearchChange = useCallback((e) => {
    setProductSearch(e.target.value);
    setProductError('');
  }, []);

  const handleSelectProduct = useCallback((product) => {
    setProductForm((prev) => ({ ...prev, product }));
    const label = [product?.code, product?.name].filter(Boolean).join(' - ') || product?.name || `Product #${product?.id}`;
    setProductSearch(label);
    setProductResults([]);
    setProductSearchError('');
    setProductError('');
  }, []);

  const handleProductFormChange = useCallback((e) => {
    const { name, value } = e.target;
    setProductForm((prev) => ({ ...prev, [name]: value }));
  }, []);

  const handleAddProductLink = useCallback(async (e) => {
    e.preventDefault();
    if (!isStaff || productAdding) return;
    if (!productForm.product?.id) {
      setProductError('Select a software product from search results before linking.');
      return;
    }
    setProductAdding(true);
    setProductError('');
    setProductMessage('');
    try {
      await createSoftwareLink({
        problem: Number(problemId),
        software_product: productForm.product.id,
        impact_type: productForm.impact_type,
        role: productForm.role,
        confidence: productForm.confidence,
        notes: productForm.notes?.trim() || '',
      });
      setProductForm({ product: null, impact_type: 'direct', role: 'affected', confidence: 'medium', notes: '' });
      setProductSearch('');
      setProductResults([]);
      setProductSearchError('');
      setProductMessage('Software product linked.');
      await refreshProductLinks();
    } catch (err) {
      setProductError(formatKbError(err));
    } finally {
      setProductAdding(false);
    }
  }, [isStaff, productAdding, productForm, problemId, refreshProductLinks, formatKbError]);

  const handleRemoveProductLink = useCallback(async (linkId) => {
    if (!isStaff || productRemoving.has(linkId)) return;
    const confirmed = typeof window !== 'undefined' && typeof window.confirm === 'function'
      ? window.confirm('Remove this software product link?')
      : true;
    if (!confirmed) return;
    setProductRemoving((prev) => new Set([...prev, linkId]));
    setProductError('');
    setProductMessage('');
    try {
      await deleteSoftwareLink(linkId);
      setProductMessage('Software product link removed.');
      await refreshProductLinks();
    } catch (err) {
      setProductError(formatKbError(err));
    } finally {
      setProductRemoving((prev) => {
        const next = new Set(prev);
        next.delete(linkId);
        return next;
      });
    }
  }, [isStaff, productRemoving, refreshProductLinks, formatKbError]);

  if (loading) return <LoadingRows n={6} />;
  if (error) return <div className="error-summary" role="alert">{error}</div>;
  if (!problem) return <div className="error-summary" role="alert">Problem not available.</div>;

  const readiness = sections.readiness?.data;
  const counts = readiness?.counts ?? {};
  const ticketLinks = listOf(sections.tickets?.data);
  const serviceLinks = listOf(sections.services?.data);
  const kbLinks = listOf(sections.kbs?.data);
  const assetLinks = listOf(sections.assets?.data);
  const ciLinks = listOf(sections.cis?.data);
  const productLinks = listOf(sections.products?.data);

  return (
    <div>
      <PageHeader title={problem.problem_number} sub={problem.title} />

      <Section title="Overview">
        {editingProblemFields ? (
          <>
            <h3>Edit Problem Fields</h3>

            {problemFieldsError && (
              <div className="error-summary" role="alert">
                {problemFieldsError}
              </div>
            )}

            <form
              className="form"
              aria-label="Edit problem fields"
              onSubmit={(e) => {
                e.preventDefault();
                handleSaveProblemFields();
              }}
            >
              <Field label="Title" required>
                <Input
                  name="title"
                  value={problemFields.title}
                  onChange={handleProblemFieldsChange}
                  required
                  disabled={savingProblemFields}
                />
              </Field>

              <Field label="Description">
                <Textarea
                  name="description"
                  value={problemFields.description}
                  onChange={handleProblemFieldsChange}
                  rows={3}
                  disabled={savingProblemFields}
                />
              </Field>

              <Field label="Priority">
                <Select
                  name="priority"
                  value={problemFields.priority}
                  onChange={handleProblemFieldsChange}
                  disabled={savingProblemFields}
                >
                  <option value="">—</option>
                  <option value="p1">P1 — Critical</option>
                  <option value="p2">P2 — High</option>
                  <option value="p3">P3 — Medium</option>
                  <option value="p4">P4 — Low</option>
                </Select>
              </Field>

              <Field label="Severity">
                <Select
                  name="severity"
                  value={problemFields.severity}
                  onChange={handleProblemFieldsChange}
                  disabled={savingProblemFields}
                >
                  <option value="">—</option>
                  <option value="minor">Minor</option>
                  <option value="major">Major</option>
                  <option value="critical">Critical</option>
                </Select>
              </Field>

              <Field label="Impact">
                <Textarea
                  name="impact"
                  value={problemFields.impact}
                  onChange={handleProblemFieldsChange}
                  rows={3}
                  disabled={savingProblemFields}
                />
              </Field>

              <Field label="Urgency">
                <Select
                  name="urgency"
                  value={problemFields.urgency}
                  onChange={handleProblemFieldsChange}
                  disabled={savingProblemFields}
                >
                  <option value="">—</option>
                  <option value="urgent">Urgent</option>
                  <option value="high">High</option>
                  <option value="medium">Medium</option>
                  <option value="low">Low</option>
                </Select>
              </Field>

              <Field label="Criticality">
                <Select
                  name="criticality"
                  value={problemFields.criticality}
                  onChange={handleProblemFieldsChange}
                  disabled={savingProblemFields}
                >
                  <option value="">—</option>
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                </Select>
              </Field>

              <Field label="Subcategory">
                <Input
                  name="subcategory"
                  value={problemFields.subcategory}
                  onChange={handleProblemFieldsChange}
                  disabled={savingProblemFields}
                />
              </Field>

              <Field label="Environment">
                <Input
                  name="environment"
                  value={problemFields.environment}
                  onChange={handleProblemFieldsChange}
                  disabled={savingProblemFields}
                />
              </Field>

              <Field label="Detection Method">
                <Input
                  name="detection_method"
                  value={problemFields.detection_method}
                  onChange={handleProblemFieldsChange}
                  disabled={savingProblemFields}
                />
              </Field>

              {isManagerOrAdmin && (
                <>
                  <Field label="Target Resolution Date">
                    <Input
                      type="date"
                      name="target_resolution_date"
                      value={problemFields.target_resolution_date}
                      onChange={handleProblemFieldsChange}
                      disabled={savingProblemFields}
                    />
                  </Field>

                  <Field label="Next Review Date">
                    <Input
                      type="date"
                      name="next_review_at"
                      value={problemFields.next_review_at}
                      onChange={handleProblemFieldsChange}
                      disabled={savingProblemFields}
                    />
                  </Field>
                </>
              )}

              <div className="row-gap">
                <Button type="submit" disabled={savingProblemFields}>
                  {savingProblemFields ? 'Saving...' : 'Save changes'}
                </Button>

                <Button
                  type="button"
                  onClick={handleCancelProblemFields}
                  disabled={savingProblemFields}
                >
                  Cancel
                </Button>
              </div>
            </form>
          </>
        ) : (
          <>
            {PROBLEM_ROWS.map(([key, label]) => (
              <p key={key}>
                {label}: {key === 'status' || key === 'priority'
                  ? <Badge kind="status-warning" value={problem[key]} />
                  : (problem[key] || '—')}
              </p>
            ))}
            {problem.description && <p>{problem.description}</p>}
          </>
        )}

        {isStaff && !editingProblemFields && (
          <div style={{ marginTop: '0.5rem' }}>
            <Button onClick={handleEditProblemFields}>
              Edit problem fields
            </Button>
          </div>
        )}
      </Section>
      <GovernedTransitions problemId={problemId} problem={problem} />

      <Section title="Tasks" state={sections.tasks}>
        {listOf(sections.tasks?.data).length === 0
          ? <p className="muted">No tasks.</p>
          : listOf(sections.tasks?.data).map((t) => <p key={t.id}>{t.title} — {t.status}</p>)}
      </Section>

      <Evidence problemId={problemId} />

      <section>
        <h3>RCA Workflow</h3>
        <RCA
          rcaId={problem.root_cause_analysis ?? undefined}
          problemId={problemId}
          problemTitle={problem.title}
        />
      </section>

      <Timeline problemId={problemId} embedded />

      <Actions problemId={problemId} embedded />

      <Workarounds problemId={problemId} embedded />

      <Validations problemId={problemId} embedded />

      <Exceptions problemId={problemId} embedded />

      <Section title="Readiness State" state={sections.readiness}>
        <p>Ready for resolution: {readiness?.ready_for_resolution ? 'Yes' : 'No'}</p>
        <p>Ready for closure: {readiness?.ready_for_closure ? 'Yes' : 'No'}</p>
        <p>Blockers: {(readiness?.blockers ?? []).join(', ') || 'None'}</p>
        {readiness?.warnings?.length && <p>Warnings: {readiness.warnings.join(', ') || 'None'}</p>}
        <p>Open required actions: {counts.open_required_actions ?? 0}</p>
        <p>Open blocking tasks: {counts.open_blocking_tasks ?? 0}</p>
        <p>Failed validations: {counts.failed_validations ?? 0}</p>
        <p>Open critical tickets: {counts.open_critical_tickets ?? 0}</p>
        <p>Active exceptions: {counts.active_exceptions ?? 0}</p>
      </Section>

      <Section title="Problem History" state={sections.history}>
        {listOf(sections.history?.data).length === 0
          ? <p className="muted">No history events.</p>
          : listOf(sections.history?.data).map((h) => (
              <p key={h.id}>{h.event_type}: {h.previous_status || '—'} → {h.new_status || '—'}</p>
            ))}
      </Section>

      <Section title="Linked Records">
        <p className="muted">Linked Changes are not supported by the backend.</p>

        <div style={{ marginTop: '1rem' }}>
          <h4>Services</h4>

          {isStaff && (
            <form
              className="form"
              aria-label="Link service"
              onSubmit={handleAddServiceLink}
              style={{ marginBottom: '1rem' }}
            >
              <Field label="Search services">
                <Input
                  name="service_search"
                  value={serviceSearch}
                  onChange={handleServiceSearchChange}
                  placeholder="Search by name, category, or description"
                  disabled={serviceAdding}
                  aria-label="Search services"
                />
              </Field>

              {serviceSearching && <p className="muted">Searching services...</p>}
              {serviceSearchError && (
                <p className="error-summary" role="alert">{serviceSearchError}</p>
              )}
              {!serviceSearching && serviceSearch.trim().length >= 2 && serviceResults.length > 0 && (
                <div role="listbox" aria-label="Service search results" style={{ marginBottom: '0.75rem' }}>
                  {serviceResults.map((service) => (
                    <button
                      key={service.id}
                      type="button"
                      className="btn btn-ghost"
                      onClick={() => handleSelectService(service)}
                      disabled={serviceAdding}
                      style={{ display: 'block', width: '100%', textAlign: 'left', marginBottom: '0.25rem' }}
                    >
                      {service.name || `Service #${service.id}`} (#{service.id})
                      {service.category ? ` (${service.category})` : ''}
                      {service.is_active === false ? ' (inactive)' : ''}
                    </button>
                  ))}
                </div>
              )}
              {!serviceSearching && serviceSearch.trim().length >= 2 && !serviceSearchError
                && serviceResults.length === 0 && !serviceForm.service && (
                <p className="muted">No services found.</p>
              )}

              {serviceForm.service && (
                <p className="muted">
                  Selected service: <strong>{serviceSelectedLabel}</strong> (ID {serviceForm.service})
                </p>
              )}

              <div style={{ display: 'grid', gap: '0.75rem', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
                <Field label="Impact type">
                  <Select
                    name="impact_type"
                    value={serviceForm.impact_type}
                    onChange={handleServiceFormChange}
                    disabled={serviceAdding}
                  >
                    {SERVICE_IMPACT_TYPE_CHOICES.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </Select>
                </Field>

                <Field label="Service role">
                  <Select
                    name="role"
                    value={serviceForm.role}
                    onChange={handleServiceFormChange}
                    disabled={serviceAdding}
                  >
                    {SERVICE_ROLE_CHOICES.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </Select>
                </Field>

                <Field label="Confidence">
                  <Select
                    name="confidence"
                    value={serviceForm.confidence}
                    onChange={handleServiceFormChange}
                    disabled={serviceAdding}
                  >
                    {SERVICE_CONFIDENCE_CHOICES.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </Select>
                </Field>
              </div>

              <Field label="Relationship notes">
                <Textarea
                  name="notes"
                  value={serviceForm.notes}
                  onChange={handleServiceFormChange}
                  rows={2}
                  disabled={serviceAdding}
                />
              </Field>

              <div>
                <Button type="submit" disabled={serviceAdding || !serviceForm.service}>
                  {serviceAdding ? 'Linking...' : 'Link service'}
                </Button>
              </div>
            </form>
          )}

          {serviceMessage && <p className="success">{serviceMessage}</p>}
          {serviceError && <p className="error-summary" role="alert">{serviceError}</p>}

          {sections.services?.ok === false ? (
            <p className="muted">Unable to load linked services.</p>
          ) : serviceLinks.length === 0 ? (
            <p className="muted">No services linked.</p>
          ) : (
            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {serviceLinks.map((link) => {
                const display = link.target_display || `Service #${link.service}`;
                return (
                  <li key={link.id} style={{ padding: '0.75rem 0', borderBottom: '1px solid rgba(128,128,128,0.2)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'flex-start' }}>
                      <div>
                        <div>
                          <a href={serviceCatalogueHref()}>{display}</a>
                          {' '}<span className="muted">#{link.service}</span>
                        </div>
                        <div className="muted">
                          Impact: {toLabel(link.impact_type)} | Role: {toLabel(link.role)}
                          {' '}| Confidence: {toLabel(link.confidence)}
                        </div>
                        <div className="muted">
                          Linked by: {link.created_by ?? '—'} | Linked at: {link.created_at || '—'}
                        </div>
                        {link.notes && <div className="muted">Notes: {link.notes}</div>}
                      </div>
                      {isStaff && (
                        <Button
                          type="button"
                          className="btn btn-ghost"
                          onClick={() => handleRemoveServiceLink(link.id)}
                          disabled={serviceRemoving.has(link.id)}
                          aria-label={`Remove service link ${display}`}
                        >
                          {serviceRemoving.has(link.id) ? 'Removing...' : 'Remove'}
                        </Button>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div style={{ marginTop: '1rem' }}>
          <h4>Tickets</h4>

          {isStaff && (
            <form
              className="form"
              aria-label="Link ticket"
              onSubmit={handleAddTicketLink}
              style={{ marginBottom: '1rem' }}
            >
              <Field label="Search tickets">
                <Input
                  name="ticket_search"
                  value={ticketSearch}
                  onChange={handleTicketSearchChange}
                  placeholder="Search by subject or description"
                  disabled={ticketAdding}
                  aria-label="Search tickets"
                />
              </Field>

              {ticketSearching && <p className="muted">Searching tickets...</p>}
              {ticketSearchError && <p className="error-summary" role="alert">{ticketSearchError}</p>}
              {!ticketSearching && ticketSearch.trim().length >= 2 && ticketResults.length > 0 && (
                <div role="listbox" aria-label="Ticket search results" style={{ marginBottom: '0.75rem' }}>
                  {ticketResults.map((ticket) => (
                    <button
                      key={ticket.id}
                      type="button"
                      className="btn btn-ghost"
                      onClick={() => handleSelectTicket(ticket)}
                      disabled={ticketAdding}
                      style={{ display: 'block', width: '100%', textAlign: 'left', marginBottom: '0.25rem' }}
                    >
                      {ticket.title || `Ticket #${ticket.id}`} (#{ticket.id}){ticket.status ? ` (${ticket.status})` : ''}
                    </button>
                  ))}
                </div>
              )}
              {!ticketSearching && ticketSearch.trim().length >= 2 && !ticketSearchError
                && ticketResults.length === 0 && !ticketForm.ticket && (
                <p className="muted">No tickets found.</p>
              )}

              {ticketForm.ticket && (
                <p className="muted">
                  Selected ticket: <strong>{ticketSelectedLabel}</strong> (ID {ticketForm.ticket})
                </p>
              )}

              <div style={{ display: 'grid', gap: '0.75rem', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
                <Field label="Relationship type">
                  <Select
                    name="relationship_type"
                    value={ticketForm.relationship_type}
                    onChange={handleTicketFormChange}
                    disabled={ticketAdding}
                  >
                    {TICKET_RELATIONSHIP_TYPE_CHOICES.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </Select>
                </Field>

                <Field label="Ticket relevance">
                  <Select
                    name="relevance"
                    value={ticketForm.relevance}
                    onChange={handleTicketFormChange}
                    disabled={ticketAdding}
                  >
                    {TICKET_RELEVANCE_CHOICES.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </Select>
                </Field>
              </div>

              <Field label="Primary ticket link">
                <Input
                  type="checkbox"
                  name="is_primary"
                  checked={ticketForm.is_primary}
                  onChange={handleTicketFormChange}
                  disabled={ticketAdding}
                />
              </Field>

              <Field label="Relationship note">
                <Textarea
                  name="note"
                  value={ticketForm.note}
                  onChange={handleTicketFormChange}
                  rows={2}
                  disabled={ticketAdding}
                />
              </Field>

              <div>
                <Button type="submit" disabled={ticketAdding || !ticketForm.ticket}>
                  {ticketAdding ? 'Linking...' : 'Link ticket'}
                </Button>
              </div>
            </form>
          )}

          {ticketMessage && <p className="success">{ticketMessage}</p>}
          {ticketError && <p className="error-summary" role="alert">{ticketError}</p>}

          {sections.tickets?.ok === false ? (
            <p className="muted">Unable to load linked tickets.</p>
          ) : ticketLinks.length === 0 ? (
            <p className="muted">No tickets linked.</p>
          ) : (
            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {ticketLinks.map((link) => {
                const ticketId = Number(link.ticket);
                const display = link.ticket_display || (ticketId ? `#${ticketId}` : 'Ticket');
                return (
                  <li key={link.id} style={{ padding: '0.75rem 0', borderBottom: '1px solid rgba(128,128,128,0.2)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'flex-start' }}>
                      <div>
                        <div>
                          {ticketId ? (
                            <a href={ticketHref(ticketId)}>{link.ticket_title || display}</a>
                          ) : (
                            <span>{link.ticket_title || display}</span>
                          )}
                          {' '}<span className="muted">{display}</span>
                        </div>
                        <div className="muted">
                          Status: {toLabel(link.ticket_status)} | Priority: {toLabel(link.ticket_priority)}
                          {link.ticket_category_name ? ` | Category: ${link.ticket_category_name}` : ''}
                        </div>
                        <div className="muted">
                          Relationship: {toLabel(link.relationship_type)} | Relevance: {toLabel(link.relevance)}
                          {' '}| Primary: {link.is_primary ? 'Yes' : 'No'}
                        </div>
                        {link.note && <div className="muted">Note: {link.note}</div>}
                      </div>
                      {isStaff && (
                        <Button
                          type="button"
                          className="btn btn-ghost"
                          onClick={() => handleRemoveTicketLink(link.id)}
                          disabled={ticketRemoving.has(link.id)}
                          aria-label={`Remove ticket link ${link.ticket_title || display}`}
                        >
                          {ticketRemoving.has(link.id) ? 'Removing...' : 'Remove'}
                        </Button>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div style={{ marginTop: '1rem' }}>
          <h4>Configuration Items</h4>

          {isStaff && (
            <form
              className="form"
              aria-label="Link configuration item"
              onSubmit={handleAddCiLink}
              style={{ marginBottom: '1rem' }}
            >
              <Field label="Search configuration items">
                <Input
                  name="ci_search"
                  value={ciSearch}
                  onChange={handleCiSearchChange}
                  placeholder="Search by CI number, name, hostname, or serial"
                  disabled={ciAdding}
                  aria-label="Search configuration items"
                />
              </Field>

              {ciSearching && <p className="muted">Searching configuration items...</p>}
              {ciSearchError && <p className="error-summary" role="alert">{ciSearchError}</p>}
              {!ciSearching && ciSearch.trim().length >= 2 && ciResults.length > 0 && (
                <div role="listbox" aria-label="CI search results" style={{ marginBottom: '0.75rem' }}>
                  {ciResults.map((ci) => (
                    <button
                      key={ci.id}
                      type="button"
                      className="btn btn-ghost"
                      onClick={() => handleSelectCi(ci)}
                      disabled={ciAdding}
                      style={{ display: 'block', width: '100%', textAlign: 'left', marginBottom: '0.25rem' }}
                    >
                      {(ci.ci_number ? `${ci.ci_number} - ` : '') + (ci.name || `CI #${ci.id}`)} {ci.status ? `(${ci.status})` : ''}
                    </button>
                  ))}
                </div>
              )}
              {!ciSearching && ciSearch.trim().length >= 2 && !ciSearchError && ciResults.length === 0 && !ciForm.ci && (
                <p className="muted">No configuration items found.</p>
              )}

              {ciForm.ci && (
                <p className="muted">
                  Selected CI: <strong>{(ciForm.ci.ci_number ? `${ciForm.ci.ci_number} - ` : '') + (ciForm.ci.name || `CI #${ciForm.ci.id}`)}</strong> (ID {ciForm.ci.id})
                </p>
              )}

              <div style={{ display: 'grid', gap: '0.75rem', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
                <Field label="Impact type">
                  <Select name="impact_type" value={ciForm.impact_type} onChange={handleCiFormChange} disabled={ciAdding}>
                    {ASSET_IMPACT_TYPE_CHOICES.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </Select>
                </Field>
                <Field label="Role">
                  <Select name="role" value={ciForm.role} onChange={handleCiFormChange} disabled={ciAdding}>
                    {ASSET_ROLE_CHOICES.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </Select>
                </Field>
                <Field label="Confidence">
                  <Select name="confidence" value={ciForm.confidence} onChange={handleCiFormChange} disabled={ciAdding}>
                    {ASSET_CONFIDENCE_CHOICES.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </Select>
                </Field>
              </div>

              <Field label="Notes">
                <Textarea name="notes" value={ciForm.notes} onChange={handleCiFormChange} rows={2} disabled={ciAdding} />
              </Field>

              <div>
                <Button type="submit" disabled={ciAdding || !ciForm.ci}>
                  {ciAdding ? 'Linking...' : 'Link configuration item'}
                </Button>
              </div>
            </form>
          )}

          {ciMessage && <p className="success">{ciMessage}</p>}
          {ciError && <p className="error-summary" role="alert">{ciError}</p>}

          {sections.cis?.ok === false ? (
            <p className="muted">Unable to load linked configuration items.</p>
          ) : ciLinks.length === 0 ? (
            <p className="muted">No configuration items linked.</p>
          ) : (
            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {ciLinks.map((link) => {
                const ciId = link.configuration_item ?? link.configuration_item_id;
                return (
                  <li key={link.id} style={{ padding: '0.75rem 0', borderBottom: '1px solid rgba(128,128,128,0.2)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'flex-start' }}>
                      <div>
                        <div>
                          {ciId ? (
                            <a href={ciHref(ciId)}>{link.target_display || `CI #${ciId}`}</a>
                          ) : (
                            <span>{link.target_display || 'Configuration item'}</span>
                          )}
                        </div>
                        <div className="muted">
                          Impact: {toLabel(link.impact_type)} | Role: {toLabel(link.role)} | Confidence: {toLabel(link.confidence)}
                        </div>
                        {link.notes && <div className="muted">Notes: {link.notes}</div>}
                      </div>
                      {isStaff && (
                        <Button
                          type="button"
                          className="btn btn-ghost"
                          onClick={() => handleRemoveCiLink(link.id)}
                          disabled={ciRemoving.has(link.id)}
                          aria-label={`Remove CI link ${link.target_display || link.id}`}
                        >
                          {ciRemoving.has(link.id) ? 'Removing...' : 'Remove'}
                        </Button>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div style={{ marginTop: '1rem' }}>
          <h4>Software Products</h4>

          {isStaff && (
            <form
              className="form"
              aria-label="Link software product"
              onSubmit={handleAddProductLink}
              style={{ marginBottom: '1rem' }}
            >
              <Field label="Search software products">
                <Input
                  name="product_search"
                  value={productSearch}
                  onChange={handleProductSearchChange}
                  placeholder="Search by name, code, publisher, or version"
                  disabled={productAdding}
                  aria-label="Search software products"
                />
              </Field>

              {productSearching && <p className="muted">Searching software products...</p>}
              {productSearchError && <p className="error-summary" role="alert">{productSearchError}</p>}
              {!productSearching && productSearch.trim().length >= 2 && productResults.length > 0 && (
                <div role="listbox" aria-label="Software product search results" style={{ marginBottom: '0.75rem' }}>
                  {productResults.map((product) => {
                    const primary = [product.code, product.name].filter(Boolean).join(' - ') || product.name || `Product #${product.id}`;
                    const detail = [product.publisher, product.version].filter(Boolean).join(' • ');
                    return (
                      <button
                        key={product.id}
                        type="button"
                        className="btn btn-ghost"
                        onClick={() => handleSelectProduct(product)}
                        disabled={productAdding}
                        style={{ display: 'block', width: '100%', textAlign: 'left', marginBottom: '0.25rem' }}
                      >
                        {primary}{detail ? ` (${detail})` : ''}
                      </button>
                    );
                  })}
                </div>
              )}
              {!productSearching && productSearch.trim().length >= 2 && !productSearchError && productResults.length === 0 && !productForm.product && (
                <p className="muted">No software products found.</p>
              )}

              {productForm.product && (
                <p className="muted">
                  Selected product: <strong>{[productForm.product.code, productForm.product.name].filter(Boolean).join(' - ') || productForm.product.name || `Product #${productForm.product.id}`}</strong> (ID {productForm.product.id})
                </p>
              )}

              <div style={{ display: 'grid', gap: '0.75rem', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
                <Field label="Impact type">
                  <Select name="impact_type" value={productForm.impact_type} onChange={handleProductFormChange} disabled={productAdding}>
                    {ASSET_IMPACT_TYPE_CHOICES.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </Select>
                </Field>
                <Field label="Role">
                  <Select name="role" value={productForm.role} onChange={handleProductFormChange} disabled={productAdding}>
                    {ASSET_ROLE_CHOICES.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </Select>
                </Field>
                <Field label="Confidence">
                  <Select name="confidence" value={productForm.confidence} onChange={handleProductFormChange} disabled={productAdding}>
                    {ASSET_CONFIDENCE_CHOICES.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </Select>
                </Field>
              </div>

              <Field label="Notes">
                <Textarea name="notes" value={productForm.notes} onChange={handleProductFormChange} rows={2} disabled={productAdding} />
              </Field>

              <div>
                <Button type="submit" disabled={productAdding || !productForm.product}>
                  {productAdding ? 'Linking...' : 'Link software product'}
                </Button>
              </div>
            </form>
          )}

          {productMessage && <p className="success">{productMessage}</p>}
          {productError && <p className="error-summary" role="alert">{productError}</p>}

          {sections.products?.ok === false ? (
            <p className="muted">Unable to load linked software products.</p>
          ) : productLinks.length === 0 ? (
            <p className="muted">No software products linked.</p>
          ) : (
            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {productLinks.map((link) => {
                const productId = link.software_product ?? link.software_product_id;
                return (
                  <li key={link.id} style={{ padding: '0.75rem 0', borderBottom: '1px solid rgba(128,128,128,0.2)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'flex-start' }}>
                      <div>
                        <div>
                          {productId ? (
                            <a href={softwareProductHref(productId)}>{link.target_display || `Product #${productId}`}</a>
                          ) : (
                            <span>{link.target_display || 'Software product'}</span>
                          )}
                        </div>
                        <div className="muted">
                          Impact: {toLabel(link.impact_type)} | Role: {toLabel(link.role)} | Confidence: {toLabel(link.confidence)}
                        </div>
                        {link.notes && <div className="muted">Notes: {link.notes}</div>}
                      </div>
                      {isStaff && (
                        <Button
                          type="button"
                          className="btn btn-ghost"
                          onClick={() => handleRemoveProductLink(link.id)}
                          disabled={productRemoving.has(link.id)}
                          aria-label={`Remove software product link ${link.target_display || link.id}`}
                        >
                          {productRemoving.has(link.id) ? 'Removing...' : 'Remove'}
                        </Button>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div style={{ marginTop: '1rem' }}>
          <h4>Assets</h4>

          {isStaff && (
            <form
              className="form"
              aria-label="Link asset"
              onSubmit={handleAddAssetLink}
              style={{ marginBottom: '1rem' }}
            >
              <Field label="Asset">
                <AssetSelect
                  value={assetForm.asset}
                  onChange={handleAssetSelect}
                  disabled={assetAdding}
                />
              </Field>

              <div style={{ display: 'grid', gap: '0.75rem', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
                <Field label="Impact type">
                  <Select name="impact_type" value={assetForm.impact_type} onChange={handleAssetFormChange} disabled={assetAdding}>
                    {ASSET_IMPACT_TYPE_CHOICES.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </Select>
                </Field>
                <Field label="Role">
                  <Select name="role" value={assetForm.role} onChange={handleAssetFormChange} disabled={assetAdding}>
                    {ASSET_ROLE_CHOICES.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </Select>
                </Field>
                <Field label="Confidence">
                  <Select name="confidence" value={assetForm.confidence} onChange={handleAssetFormChange} disabled={assetAdding}>
                    {ASSET_CONFIDENCE_CHOICES.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </Select>
                </Field>
              </div>

              <Field label="Notes">
                <Textarea name="notes" value={assetForm.notes} onChange={handleAssetFormChange} rows={2} disabled={assetAdding} />
              </Field>

              <div>
                <Button type="submit" disabled={assetAdding || !assetForm.asset}>
                  {assetAdding ? 'Linking...' : 'Link asset'}
                </Button>
              </div>
            </form>
          )}

          {assetMessage && <p className="success">{assetMessage}</p>}
          {assetError && <p className="error-summary" role="alert">{assetError}</p>}

          {sections.assets?.ok === false ? (
            <p className="muted">Unable to load linked assets.</p>
          ) : assetLinks.length === 0 ? (
            <p className="muted">No assets linked.</p>
          ) : (
            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {assetLinks.map((link) => {
                const assetId = link.asset ?? link.asset_id;
                return (
                  <li key={link.id} style={{ padding: '0.75rem 0', borderBottom: '1px solid rgba(128,128,128,0.2)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'flex-start' }}>
                      <div>
                        <div>
                          {assetId ? (
                            <a href={assetHref(assetId)}>{link.target_display || `Asset #${assetId}`}</a>
                          ) : (
                            <span>{link.target_display || 'Asset'}</span>
                          )}
                        </div>
                        <div className="muted">
                          Impact: {toLabel(link.impact_type)} | Role: {toLabel(link.role)} | Confidence: {toLabel(link.confidence)}
                        </div>
                        {link.notes && <div className="muted">Notes: {link.notes}</div>}
                      </div>
                      {isStaff && (
                        <Button
                          type="button"
                          className="btn btn-ghost"
                          onClick={() => handleRemoveAssetLink(link.id)}
                          disabled={assetRemoving.has(link.id)}
                          aria-label={`Remove asset link ${link.target_display || link.id}`}
                        >
                          {assetRemoving.has(link.id) ? 'Removing...' : 'Remove'}
                        </Button>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div style={{ marginTop: '1rem' }}>
          <h4>Knowledge Base Articles</h4>

          {isStaff && (
            <form
              className="form"
              aria-label="Link KB article"
              onSubmit={handleAddKbLink}
              style={{ marginBottom: '1rem' }}
            >
              <Field label="Search KB articles">
                <Input
                  name="kb_search"
                  value={kbSearch}
                  onChange={handleKbSearchChange}
                  placeholder="Search by title, summary, or content"
                  disabled={kbAdding}
                  aria-label="Search KB articles"
                />
              </Field>

              {kbSearching && <p className="muted">Searching KB articles...</p>}
              {kbSearchError && <p className="error-summary" role="alert">{kbSearchError}</p>}
              {!kbSearching && kbSearch.trim().length >= 2 && kbResults.length > 0 && (
                <div role="listbox" aria-label="KB search results" style={{ marginBottom: '0.75rem' }}>
                  {kbResults.map((article) => (
                    <button
                      key={article.id}
                      type="button"
                      className="btn btn-ghost"
                      onClick={() => handleSelectKbArticle(article)}
                      disabled={kbAdding}
                      style={{ display: 'block', width: '100%', textAlign: 'left', marginBottom: '0.25rem' }}
                    >
                      {article.title} {article.status ? `(${article.status})` : ''}
                    </button>
                  ))}
                </div>
              )}
              {!kbSearching && kbSearch.trim().length >= 2 && !kbSearchError && kbResults.length === 0 && !kbForm.article && (
                <p className="muted">No KB articles found.</p>
              )}

              {kbForm.article && (
                <p className="muted">
                  Selected article: <strong>{kbForm.article.title}</strong> (ID {kbForm.article.id})
                </p>
              )}

              <div style={{ display: 'grid', gap: '0.75rem', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
                <Field label="Relation type">
                  <Select
                    name="relation_type"
                    value={kbForm.relation_type}
                    onChange={handleKbFormChange}
                    disabled={kbAdding}
                  >
                    {KB_RELATION_TYPE_CHOICES.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </Select>
                </Field>

                <Field label="Relevance">
                  <Select
                    name="relevance"
                    value={kbForm.relevance}
                    onChange={handleKbFormChange}
                    disabled={kbAdding}
                  >
                    {KB_RELEVANCE_CHOICES.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </Select>
                </Field>
              </div>

              <Field label="Note">
                <Textarea
                  name="note"
                  value={kbForm.note}
                  onChange={handleKbFormChange}
                  rows={2}
                  disabled={kbAdding}
                />
              </Field>

              <div>
                <Button type="submit" disabled={kbAdding || !kbForm.article}>
                  {kbAdding ? 'Linking...' : 'Link KB article'}
                </Button>
              </div>
            </form>
          )}

          {kbMessage && <p className="success">{kbMessage}</p>}
          {kbError && <p className="error-summary" role="alert">{kbError}</p>}

          {sections.kbs?.ok === false ? (
            <p className="muted">Unable to load linked KB articles.</p>
          ) : kbLinks.length === 0 ? (
            <p className="muted">No KB articles linked.</p>
          ) : (
            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {kbLinks.map((link) => {
                const articleId = link.article ?? link.article_id;
                return (
                  <li key={link.id} style={{ padding: '0.75rem 0', borderBottom: '1px solid rgba(128,128,128,0.2)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'flex-start' }}>
                      <div>
                        <div>
                          {articleId ? (
                            <a href={kbArticleHref(articleId)}>{link.article_title || `Article #${articleId}`}</a>
                          ) : (
                            <span>{link.article_title || 'KB article'}</span>
                          )}
                          {link.article_status && <span className="muted"> ({link.article_status})</span>}
                        </div>
                        <div className="muted">
                          Relation: {toLabel(link.relation_type)} | Relevance: {toLabel(link.relevance)}
                        </div>
                        {link.note && <div className="muted">Note: {link.note}</div>}
                      </div>
                      {isStaff && (
                        <Button
                          type="button"
                          className="btn btn-ghost"
                          onClick={() => handleRemoveKbLink(link.id)}
                          disabled={kbRemoving.has(link.id)}
                          aria-label={`Remove KB link ${link.article_title || link.id}`}
                        >
                          {kbRemoving.has(link.id) ? 'Removing...' : 'Remove'}
                        </Button>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </Section>

      <Section title="Permissions">
        <p>Problem management actions follow your role permissions.</p>
      </Section>
    </div>
  );
}