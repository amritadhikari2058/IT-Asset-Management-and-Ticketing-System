import { describe, test, expect, beforeEach, vi } from 'vitest';
import * as services from '../../services/problem-management';

const api = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}));

vi.mock('../../api', () => ({ default: api }));

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.get.mockResolvedValue({ data: {} });
  api.post.mockResolvedValue({ data: {} });
  api.patch.mockResolvedValue({ data: {} });
  api.delete.mockResolvedValue({ data: {} });
});

const call = (fn, ...args) => {
  Object.values(api).forEach((mock) => mock.mockClear());
  return Promise.resolve(fn(...args)).then(() => {
    const entry = Object.entries(api).find(([, mock]) => mock.mock.calls.length > 0);
    if (!entry) return { method: null, url: null, body: null };
    const [method, mock] = entry;
    const [url, body] = mock.mock.calls[0];
    return { method, url, body };
  });
};

describe('canonical API prefix', () => {
  test('problem routes use a single /problems prefix', async () => {
    expect((await call(services.problemDetail, 7)).url).toBe('/problems/7/');
    expect((await call(services.problemList)).url).toBe('/problems/');
    expect((await call(services.problemReadiness, 7)).url).toBe('/problems/7/readiness/');
  });

  test('no helper requests the duplicate /problems/problems prefix', async () => {
    const fns = Object.entries(services).filter(([, fn]) => typeof fn === 'function');
    for (const [, fn] of fns) {
      try {
        await fn(1, {});
      } catch {
        // a helper may reject its arguments; only the URL matters
      }
    }
    const urls = Object.values(api).flatMap((mock) => mock.mock.calls.map(([url]) => String(url)));
    expect(urls.length).toBeGreaterThan(0);
    urls.forEach((url) => {
      expect(url.startsWith('/')).toBe(true);
      expect(url).not.toContain('/problems/problems/');
      expect(url).not.toContain('//');
    });
  });
});

// Route table dumped from problem_management.urls (Django resolver). Every
// frontend path below must resolve against one of these patterns; there is
// deliberately no linked-changes and no unarchive pattern.
const BACKEND_ROUTES = [
  '^problems/$', '^problems/(?P<pk>\\d+)/$',
  '^root-cause-analyses/$', '^root-cause-analyses/(?P<pk>\\d+)/$',
  '^root-cause-whys/$', '^root-cause-whys/(?P<pk>\\d+)/$',
  '^root-cause-factors/$', '^root-cause-factors/(?P<pk>\\d+)/$',
  '^evidence/$', '^evidence/(?P<pk>\\d+)/$',
  '^actions/$', '^actions/(?P<pk>\\d+)/$',
  '^workarounds/$', '^workarounds/(?P<pk>\\d+)/$',
  '^validations/$', '^validations/(?P<pk>\\d+)/$',
  '^exceptions/$', '^exceptions/(?P<pk>\\d+)/$',
  '^(?P<resource>root-cause-analyses|evidence|actions|workarounds|validations|exceptions)/(?P<pk>\\d+)/(?P<transition>[a-z_-]+)/$',
  'problems/<int:problem_id>/root-cause-analysis/',
  'problems/<int:problem_id>/five-whys/',
  'problems/<int:problem_id>/root-cause-factors/',
  'problems/<int:problem_id>/evidence/',
  'problems/<int:problem_id>/timeline/',
  'problems/<int:problem_id>/actions/',
  'problems/<int:problem_id>/workarounds/',
  'problems/<int:problem_id>/validations/',
  'problems/<int:problem_id>/exceptions/',
  'problems/<int:problem_id>/readiness/',
  'problems/<int:problem_id>/linked-tickets/',
  'problems/<int:problem_id>/linked-cis/',
  'problems/<int:problem_id>/linked-assets/',
  'problems/<int:problem_id>/linked-services/',
  'problems/<int:problem_id>/linked-products/',
];

const RESOLVERS = BACKEND_ROUTES.map((pattern) => {
  const body = pattern
    .replace('<int:problem_id>', '\\d+')
    .replace(/\(\?P<[a-z_]+>/g, '(')
    .replace(/^\^/, '')
    .replace(/\$$/, '');
  return new RegExp(`^/${body}$`);
});

const resolves = (url) => url.replace(/^\/api/, '').split('?')[0];

const FRONTEND_PATHS = [
  '/problems/', '/problems/1/', '/problems/1/readiness/', '/problems/1/timeline/',
  '/problems/1/root-cause-analysis/', '/problems/1/five-whys/',
  '/problems/1/root-cause-factors/', '/problems/1/evidence/',
  '/problems/1/actions/', '/problems/1/workarounds/', '/problems/1/validations/',
  '/problems/1/exceptions/', '/problems/1/linked-tickets/', '/problems/1/linked-cis/',
  '/problems/1/linked-assets/', '/problems/1/linked-services/', '/problems/1/linked-products/',
  '/root-cause-analyses/', '/root-cause-analyses/2/', '/root-cause-analyses/2/approve/',
  '/root-cause-whys/', '/root-cause-whys/3/', '/root-cause-factors/', '/root-cause-factors/4/',
  '/evidence/9/archive/', '/actions/4/', '/actions/4/start/', '/actions/4/ineffective/',
  '/workarounds/6/', '/workarounds/6/publish/', '/validations/7/', '/validations/7/inconclusive/',
  '/exceptions/8/', '/exceptions/8/revoke/',
];

describe('backend route registry match', () => {
  test.each(FRONTEND_PATHS)('%s resolves to a registered backend route', (path) => {
    expect(RESOLVERS.some((re) => re.test(resolves(path)))).toBe(true);
  });

  test('no frontend path targets an unregistered relation', () => {
    FRONTEND_PATHS.forEach((path) => {
      expect(path).not.toContain('linked-changes');
      expect(path).not.toContain('unarchive');
    });
  });
});

describe('RCA contract', () => {
  test('create and retrieve hit the governed resource', async () => {
    expect(await call(services.createRCA, { problem: 1, title: 'x' }))
      .toMatchObject({ method: 'post', url: '/root-cause-analyses/' });
    expect(await call(services.getRCA, 2)).toMatchObject({ method: 'get', url: '/root-cause-analyses/2/' });
    expect(await call(services.problemRCA, 1))
      .toMatchObject({ method: 'get', url: '/problems/1/root-cause-analysis/' });
  });

  test('problem-scoped RCA options send the problem filter', async () => {
    const sent = await call(services.listRCAs, 1);
    expect(sent).toMatchObject({ method: 'get', url: '/root-cause-analyses/' });
    expect(sent.body).toEqual({ params: { problem: 1 } });
  });

  test('update sends the loaded version and no unsupported fields', async () => {
    const sent = await call(services.editRCA, 2, { title: 't', description: 'd' }, 4);
    expect(sent.url).toBe('/root-cause-analyses/2/');
    expect(sent.body).toEqual({ title: 't', description: 'd', expected_record_version: 4 });
    expect(sent.body).not.toHaveProperty('confidence');
    expect(sent.body).not.toHaveProperty('limitation');
  });

  test.each(['submit', 'approve', 'reject', 'supersede'])('transition %s uses its own endpoint', async (name) => {
    const fn = services[`${name}RCA`];
    const sent = await call(fn, 2, { expected_record_version: 1 });
    expect(sent).toMatchObject({ method: 'post', url: `/root-cause-analyses/2/${name}/` });
  });
});

describe('Five Whys and factors', () => {
  test('whys use question_number and never a version token', async () => {
    expect(await call(services.fiveWhys, 1)).toMatchObject({ method: 'get', url: '/problems/1/five-whys/' });
    const created = await call(services.createFiveWhy, {
      analysis: 2, question_number: 1, question_text: 'Why?', answer: 'Because',
    });
    expect(created.url).toBe('/root-cause-whys/');
    expect(created.body).not.toHaveProperty('expected_record_version');
    const patched = await call(services.editFiveWhy, 3, { answer: 'Because.' });
    expect(patched.url).toBe('/root-cause-whys/3/');
    expect(patched.body).toEqual({ answer: 'Because.' });
    expect((await call(services.deleteFiveWhy, 3)).method).toBe('delete');
  });

  test('factors use factor/contribution and delete without a version token', async () => {
    expect(await call(services.rootCauseFactors, 1))
      .toMatchObject({ method: 'get', url: '/problems/1/root-cause-factors/' });
    const created = await call(services.createFactor, { analysis: 2, category: 'method', factor: 'f' });
    expect(created.url).toBe('/root-cause-factors/');
    expect(created.body).toEqual({ analysis: 2, category: 'method', factor: 'f' });
    const patched = await call(services.editFactor, 5, { contribution: 'major' });
    expect(patched.body).toEqual({ contribution: 'major' });
    expect((await call(services.deleteFactor, 5)).method).toBe('delete');
  });
});

describe('Evidence contract', () => {
  test('upload is multipart and carries no version token', async () => {
    const file = new File(['x'], 'note.txt', { type: 'text/plain' });
    const sent = await call(services.uploadEvidence, 1, file, null);
    expect(sent.method).toBe('post');
    expect(sent.url).toBe('/problems/1/evidence/');
    expect(sent.body instanceof FormData).toBe(true);
    expect(sent.body.get('file')).toBeInstanceOf(File);
    expect(sent.body.has('expected_record_version')).toBe(false);
  });

  test('archive posts to the supported endpoint with no body fields', async () => {
    const sent = await call(services.archiveEvidence, 9);
    expect(sent).toMatchObject({ method: 'post', url: '/evidence/9/archive/' });
    expect(sent.body).toEqual({});
  });

  test('there is no unarchive service', () => {
    expect(Object.keys(services).some((name) => /unarchive/i.test(name))).toBe(false);
  });
});

describe('Timeline contract', () => {
  test('list and create use the problem-scoped collection', async () => {
    expect(await call(services.problemTimeline, 1))
      .toMatchObject({ method: 'get', url: '/problems/1/timeline/' });
    const created = await call(services.createTimelineEvent, 1, {
      event_type: 'milestone', title: 'Kickoff',
      description: 'start', occurred_at: '2026-01-01T09:00:00.000Z',
    });
    expect(created).toMatchObject({ method: 'post', url: '/problems/1/timeline/' });
    expect(created.body).toHaveProperty('occurred_at');
  });
});

describe('Action lifecycle', () => {
  test('creation is problem-scoped and uses real fields', async () => {
    const created = await call(services.createAction, 1, {
      title: 'Replace disk', action_type: 'corrective', due_at: null,
    });
    expect(created.url).toBe('/problems/1/actions/');
    expect(created.body).not.toHaveProperty('validation_status');
    expect(created.body).not.toHaveProperty('completed_by');
  });

  test('RCA links use PATCH with a version and accept null to clear', async () => {
    const linked = await call(services.editAction, 4, { root_cause_analysis: 2 }, 3);
    expect(linked).toMatchObject({ method: 'patch', url: '/actions/4/' });
    expect(linked.body).toEqual({
      root_cause_analysis: 2,
      expected_record_version: 3,
    });

    const cleared = await call(services.editAction, 4, { root_cause_analysis: null }, 4);
    expect(cleared.body).toEqual({
      root_cause_analysis: null,
      expected_record_version: 4,
    });
  });

  test.each([
    ['approveAction', 'approve'], ['startAction', 'start'], ['completeAction', 'complete'],
    ['validateAction', 'validate'], ['markActionIneffective', 'ineffective'], ['cancelAction', 'cancel'],
  ])('%s posts to /actions/<id>/%s/ with the version token', async (fnName, slug) => {
    const sent = await call(services[fnName], 4, { expected_record_version: 7 });
    expect(sent).toMatchObject({ method: 'post', url: `/actions/4/${slug}/` });
    expect(sent.body).toEqual({ expected_record_version: 7 });
  });
});

describe('Workaround, validation and exception transitions', () => {
  test.each([
    ['submitWorkaround', 'workarounds', 'submit'],
    ['approveWorkaround', 'workarounds', 'approve'],
    ['publishWorkaround', 'workarounds', 'publish'],
    ['expireWorkaround', 'workarounds', 'expire'],
    ['retireWorkaround', 'workarounds', 'retire'],
    ['startValidation', 'validations', 'start'],
    ['passValidation', 'validations', 'pass'],
    ['failValidation', 'validations', 'fail'],
    ['markValidationInconclusive', 'validations', 'inconclusive'],
    ['cancelValidation', 'validations', 'cancel'],
    ['submitException', 'exceptions', 'submit'],
    ['approveException', 'exceptions', 'approve'],
    ['rejectException', 'exceptions', 'reject'],
    ['revokeException', 'exceptions', 'revoke'],
    ['expireException', 'exceptions', 'expire'],
  ])('%s posts to /%s/<id>/%s/', async (fnName, resource, slug) => {
    const sent = await call(services[fnName], 6);
    expect(sent).toMatchObject({ method: 'post', url: `/${resource}/6/${slug}/` });
  });

  test.each([
    ['startValidation', 'start'],
    ['passValidation', 'pass'],
    ['failValidation', 'fail'],
    ['markValidationInconclusive', 'inconclusive'],
    ['cancelValidation', 'cancel'],
  ])('%s carries expected_record_version', async (fnName, slug) => {
    const sent = await call(services[fnName], 6, { expected_record_version: 4 });
    expect(sent).toMatchObject({ method: 'post', url: `/validations/6/${slug}/` });
    expect(sent.body).toEqual({ expected_record_version: 4 });
  });

  test('validation creation sends test_plan, not validation_status', async () => {
    const created = await call(services.createValidation, 1, { title: 'Failover', test_plan: 'kill node' });
    expect(created.url).toBe('/problems/1/validations/');
    expect(created.body).toEqual({ title: 'Failover', test_plan: 'kill node' });
    expect(created.body).not.toHaveProperty('validation_status');
  });

  test('exception creation sends exception_type and reason, not type/risk', async () => {
    const created = await call(services.createException, 1, {
      title: 'Accept', exception_type: 'operational', reason: 'r', conditions: 'c',
      expires_at: '2026-12-01T00:00:00Z',
    });
    expect(created.url).toBe('/problems/1/exceptions/');
    expect(created.body).not.toHaveProperty('type');
    expect(created.body).not.toHaveProperty('risk');
    expect(created.body.exception_type).toBe('operational');
  });
});

describe('linked records and readiness', () => {
  test.each([
    ['linkedTickets', 'linked-tickets'],
    ['linkedCIs', 'linked-cis'],
    ['linkedAssets', 'linked-assets'],
    ['linkedServices', 'linked-services'],
    ['linkedProducts', 'linked-products'],
  ])('%s reads /problems/<id>/%s/', async (fnName, slug) => {
    expect(await call(services[fnName], 2)).toMatchObject({
      method: 'get', url: `/problems/2/${slug}/`,
    });
  });

  test('no linked-changes helper exists', () => {
    expect(services.linkedChanges).toBeUndefined();
  });

  test('readiness is a single read-only GET', async () => {
    expect(await call(services.problemReadiness, 2))
      .toMatchObject({ method: 'get', url: '/problems/2/readiness/' });
    expect(api.post).not.toHaveBeenCalled();
  });
});
