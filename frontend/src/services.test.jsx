import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';

const { mockGet, mockPost, mockPatch, mockDelete, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPatch: vi.fn(),
  mockDelete: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('./api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: (...args) => mockPost(...args),
    patch: (...args) => mockPatch(...args),
    delete: (...args) => mockDelete(...args),
  },
}));

vi.mock('./auth', () => ({
  useAuth: (...args) => mockAuth(...args),
}));

import { ServicesCatalogue, MyServiceRequests, ServiceRequestDetail } from './services';

function staff() {
  mockAuth.mockReturnValue({
    isStaff: true, isAdmin: true,
    user: { id: 1, employee_id: 'E1', role: 'system_admin', email: 'admin@x' },
  });
}

function employee() {
  mockAuth.mockReturnValue({
    isStaff: false, isAdmin: false,
    user: { id: 3, employee_id: 'E3', role: 'employee', email: 'emp@x' },
  });
}

const CATALOGUE = [
  {
    id: 1, name: 'Laptop request', description: 'Request a laptop', category: 'hardware',
    is_active: true, requires_approval: true, creates_ticket: false,
    estimated_fulfilment_hours: 24, instructions: 'Bring ID.',
    form_fields: [
      { key: 'asset_need', label: 'Asset need', type: 'text', required: true },
      { key: 'reason', label: 'Reason', type: 'textarea', required: false },
    ],
  },
  {
    id: 2, name: 'Old service', description: '', category: 'other',
    is_active: false, requires_approval: false, creates_ticket: false, form_fields: [],
  },
];

const REQUESTS_PAGE = {
  data: { results: [
    { id: 10, request_number: 'SR-20261104-0001', catalogue_item_name: 'Laptop request', status: 'pending_approval', priority: 'medium', requester: 3, requester_name: 'emp@x', submitted_at: '2026-11-04T10:00:00Z' },
    { id: 11, request_number: 'SR-20261104-0002', catalogue_item_name: 'Laptop request', status: 'approved', priority: 'low', requester: 3, requester_name: 'emp@x', submitted_at: '2026-11-03T10:00:00Z' },
  ], count: 2, next: null, previous: null },
};

const DETAIL = {
  id: 10, request_number: 'SR-20261104-0001', catalogue_item_name: 'Laptop request',
  status: 'pending_approval', priority: 'medium', requester: 3, requester_name: 'emp@x',
  department: 2, assigned_to: null, assigned_to_name: null,
  approval_required: true, approver: null, approval_decision: '', approval_reason: '',
  approved_at: null, fulfilment_ticket: null, fulfilment_details: '',
  description: 'Need a laptop', answers: { asset_need: 'ThinkPad' },
  submitted_at: '2026-11-04T10:00:00Z', updated_at: '2026-11-04T10:00:00Z',
  comments: [
    { id: 1, author: 3, author_name: 'emp@x', body: 'First', is_internal: false, created_at: '2026-11-04T11:00:00Z' },
    { id: 2, author: 1, author_name: 'admin@x', body: 'Internal note', is_internal: true, created_at: '2026-11-04T11:30:00Z' },
  ],
  history: [
    { id: 1, event: 'created', detail: 'Request submitted', actor: 3, actor_name: 'emp@x', created_at: '2026-11-04T10:00:00Z' },
  ],
  attachments: [],
};

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
});

afterEach(() => cleanup());

describe('Services catalogue', () => {
  it('lists active services for employees only', async () => {
    employee();
    mockGet.mockResolvedValueOnce({ data: { results: CATALOGUE, count: 2, next: null, previous: null } });
    render(<ServicesCatalogue />);
    await screen.findByText('Laptop request');
    expect(screen.queryByText('Old service')).toBeNull(); // inactive hidden from non-staff
    expect(screen.getByText('Approval required')).toBeTruthy();
  });

  it('shows inactive services to staff with edit/activate/delete', async () => {
    staff();
    mockGet.mockResolvedValueOnce({ data: { results: CATALOGUE, count: 2, next: null, previous: null } });
    render(<ServicesCatalogue />);
    await screen.findByText('Old service');
    expect(screen.getByText('+ New service')).toBeTruthy();
    expect(screen.queryByText('Activate')).toBeTruthy(); // inactive row offers Activate
  });

  it('submits a form-field-driven request', async () => {
    employee();
    mockGet.mockResolvedValueOnce({ data: { results: [CATALOGUE[0]], count: 1, next: null, previous: null } });
    mockPost.mockResolvedValueOnce({ data: { id: 10, request_number: 'SR-20261104-0003' } });
    render(<ServicesCatalogue />);
    await screen.findByText('Laptop request');
    const requestBtns = screen.getAllByRole('button', { name: 'Request' });
    fireEvent.click(requestBtns[0]);
    expect(screen.getByLabelText('Asset need')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Asset need'), { target: { value: 'ThinkPad' } });
    fireEvent.change(screen.getByLabelText('Description'), { target: { value: 'Need one' } });
    fireEvent.click(screen.getByRole('button', { name: 'Submit request' }));
    await screen.findByText('Submitted SR-20261104-0003.');
    expect(mockPost).toHaveBeenCalledWith('/services/requests/', {
      catalogue_item: 1, description: 'Need one', priority: 'medium',
      answers: { asset_need: 'ThinkPad' },
    });
  });

  it('staff create a catalogue item', async () => {
    staff();
    mockGet.mockResolvedValueOnce({ data: { results: [], count: 0, next: null, previous: null } });
    mockPost.mockResolvedValueOnce({ data: { id: 3 } });
    mockGet.mockResolvedValueOnce({ data: { results: [], count: 0, next: null, previous: null } });
    render(<ServicesCatalogue />);
    await screen.findByText('No services available.');
    fireEvent.click(screen.getByText('+ New service'));
    fireEvent.change(screen.getByLabelText(/Name/), { target: { value: 'VPN access' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create service' }));
    await screen.findByText('Service created.');
    expect(mockPost).toHaveBeenCalledWith('/services/catalogue/', expect.objectContaining({ name: 'VPN access' }));
  });
});

describe('My service requests', () => {
  it('renders the request table', async () => {
    employee();
    mockGet.mockResolvedValueOnce(REQUESTS_PAGE);
    render(<MyServiceRequests />);
    await screen.findByText('SR-20261104-0001');
    expect(screen.getByText('SR-20261104-0002')).toBeTruthy();
    expect(screen.getAllByText('Laptop request').length).toBeGreaterThanOrEqual(1);
  });
});

describe('Service request detail', () => {
  it('hides internal comments from employees', async () => {
    employee();
    mockGet.mockResolvedValueOnce({ data: DETAIL });
    render(<ServiceRequestDetail id="10" />);
    await screen.findByText('SR-20261104-0001');
    expect(screen.getByText('First')).toBeTruthy();
    expect(screen.queryByText('Internal note')).toBeNull();
    expect(screen.getByRole('button', { name: 'Cancel request' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Approve…' })).toBeNull();
  });

  it('shows internal comments + approve/reject/assign to staff', async () => {
    staff();
    mockGet.mockResolvedValueOnce({ data: DETAIL });
    render(<ServiceRequestDetail id="10" />);
    await screen.findByText('SR-20261104-0001');
    expect(screen.getByText('Internal note')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Approve…' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Reject…' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Assign…' })).toBeTruthy();
  });

  it('approves a pending request', async () => {
    staff();
    mockGet.mockResolvedValueOnce({ data: DETAIL });
    mockPost.mockResolvedValueOnce({ data: { ...DETAIL, status: 'approved' } });
    mockGet.mockResolvedValueOnce({ data: { ...DETAIL, status: 'approved' } });
    render(<ServiceRequestDetail id="10" />);
    await screen.findByText('SR-20261104-0001');
    fireEvent.click(screen.getByRole('button', { name: 'Approve…' }));
    fireEvent.click(screen.getByRole('button', { name: 'Approve request' }));
    await screen.findByText('Request SR-20261104-0001 approved.');
    expect(mockPost).toHaveBeenCalledWith('/services/requests/10/approve/', { reason: '' });
  });

  it('rejects a pending request', async () => {
    staff();
    mockGet.mockResolvedValueOnce({ data: DETAIL });
    mockPost.mockResolvedValueOnce({ data: { ...DETAIL, status: 'rejected' } });
    mockGet.mockResolvedValueOnce({ data: { ...DETAIL, status: 'rejected' } });
    render(<ServiceRequestDetail id="10" />);
    await screen.findByText('SR-20261104-0001');
    fireEvent.click(screen.getByRole('button', { name: 'Reject…' }));
    fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: 'Incomplete' } });
    fireEvent.click(screen.getByRole('button', { name: 'Reject request' }));
    await screen.findByText('Request SR-20261104-0001 rejected.');
    expect(mockPost).toHaveBeenCalledWith('/services/requests/10/reject/', { reason: 'Incomplete' });
  });

  it('posts a comment', async () => {
    employee();
    mockGet.mockResolvedValueOnce({ data: DETAIL });
    mockPost.mockResolvedValueOnce({ data: {} });
    mockGet.mockResolvedValueOnce({ data: DETAIL });
    render(<ServiceRequestDetail id="10" />);
    await screen.findByText('SR-20261104-0001');
    fireEvent.change(screen.getByLabelText('Add a comment'), { target: { value: 'Thanks!' } });
    fireEvent.click(screen.getByRole('button', { name: 'Post comment' }));
    expect(mockPost).toHaveBeenCalledWith('/services/requests/10/comment/', { body: 'Thanks!', is_internal: false });
  });

  it('cancels an open request', async () => {
    employee();
    mockGet.mockResolvedValueOnce({ data: DETAIL });
    mockPost.mockResolvedValueOnce({ data: { ...DETAIL, status: 'cancelled' } });
    mockGet.mockResolvedValueOnce({ data: { ...DETAIL, status: 'cancelled' } });
    render(<ServiceRequestDetail id="10" />);
    await screen.findByText('SR-20261104-0001');
    fireEvent.click(screen.getByRole('button', { name: 'Cancel request' }));
    await screen.findByText('Request SR-20261104-0001 cancelled.');
    expect(mockPost).toHaveBeenCalledWith('/services/requests/10/cancel/', {});
  });
});
