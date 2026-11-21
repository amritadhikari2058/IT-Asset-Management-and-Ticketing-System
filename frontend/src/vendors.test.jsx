import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';

const { mockGet, mockPost, mockPatch, mockDelete, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPatch: vi.fn(),
  mockDelete: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('./api', () => ({
  default: {
    get: (...a) => mockGet(...a),
    post: (...a) => mockPost(...a),
    patch: (...a) => mockPatch(...a),
    delete: (...a) => mockDelete(...a),
  },
}));
vi.mock('./auth', () => ({ useAuth: (...a) => mockAuth(...a) }));

import { VendorsPage, VendorForm, VendorDetail } from './vendors';

function makeAuth() {
  return { isStaff: true, isAdmin: true, canManageVendors: true };
}

const VENDORS = [
  {
    id: 1,
    name: 'Acme Corp',
    code: 'ACME',
    contact_person: 'Dana Reed',
    email: 'dana@acme.io',
    phone: '555-0100',
    website: 'https://acme.io',
    address: '1 Main St',
    tax_registration: 'TAX-1',
    notes: 'Preferred supplier',
    is_active: true,
    asset_count: 2,
    stock_item_count: 1,
    updated_at: '2026-02-01T00:00:00Z',
  },
  {
    id: 2,
    name: 'Beta LLC',
    code: 'BETA',
    contact_person: '',
    email: '',
    phone: '',
    is_active: false,
    asset_count: 0,
    stock_item_count: 0,
    updated_at: '2026-01-01T00:00:00Z',
  },
];

const ASSETS = [
  { id: 10, asset_tag: 'AST-001', name: 'Laptop 1', status: 'in_use', purchase_cost: '1200.00' },
  { id: 11, asset_tag: 'AST-002', name: 'Laptop 2', status: 'in_stock', purchase_cost: null },
];

const PAGE_1 = {
  results: VENDORS,
  count: 45,
  next: 'http://testserver/api/assets/vendors/?page=2',
  previous: null,
};

const PAGE_2 = {
  results: [
    {
      id: 3, name: 'Gamma Inc', code: 'GAMMA', contact_person: '', email: '',
      phone: '', is_active: true, asset_count: 0, stock_item_count: 0,
      updated_at: '2026-01-01T00:00:00Z',
    },
  ],
  count: 45,
  next: null,
  previous: 'http://testserver/api/assets/vendors/?page=1',
};

/** Default API mock: vendor list, vendor detail, related assets, stock items. */
function installDefaultGet() {
  mockGet.mockImplementation(async (url) => {
    const u = String(url);
    if (u === '/assets/vendors/1/') return { data: VENDORS[0] };
    if (u.startsWith('/assets/vendors/')) {
      return { data: { results: VENDORS, count: VENDORS.length, next: null, previous: null } };
    }
    if (u.startsWith('/assets/?vendor=1')) {
      return { data: { results: ASSETS, count: ASSETS.length, next: null, previous: null } };
    }
    if (u.startsWith('/inventory/stock-items/')) return { data: { results: [], count: 0 } };
    return { data: { results: [], count: 0, next: null, previous: null } };
  });
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  mockAuth.mockImplementation(() => makeAuth());
  mockPost.mockResolvedValue({ data: {} });
  mockPatch.mockResolvedValue({ data: {} });
  installDefaultGet();
});

afterEach(() => cleanup());

describe('Vendors page - table rendering', () => {
  it('renders a non-empty vendor list with row keys derived from each vendor', async () => {
    render(<VendorsPage />);

    await screen.findByText('Acme Corp');
    expect(screen.getByText('Beta LLC')).toBeTruthy();
    expect(screen.getByText('ACME')).toBeTruthy();
    expect(screen.getByText('Dana Reed')).toBeTruthy();
    expect(screen.getByText('dana@acme.io')).toBeTruthy();
    expect(screen.getByText('Acme Corp').closest('a').getAttribute('href')).toBe('#/vendors/1');
    expect(screen.getByText('Beta LLC').closest('a').getAttribute('href')).toBe('#/vendors/2');
  });

  it('renders the vendor detail related-assets table with non-empty data', async () => {
    render(<VendorDetail id={1} />);

    await screen.findByRole('heading', { name: 'Acme Corp' });
    const heading = await screen.findByRole('heading', { name: /Related Assets/ });
    expect(heading.textContent).toContain('Related Assets (2)');
    expect(screen.getByText('AST-001')).toBeTruthy();
    expect(screen.getByText('AST-002')).toBeTruthy();
    expect(screen.getByText('Laptop 1')).toBeTruthy();
  });
});

describe('Vendors page - pagination', () => {
  function installPagedGet() {
    mockGet.mockImplementation(async (url) => {
      const u = String(url);
      if (u.includes('page=2')) return { data: PAGE_2 };
      if (u.includes('q=')) {
        return { data: { ...PAGE_1, results: [VENDORS[0]] } };
      }
      return { data: PAGE_1 };
    });
  }

  it('renders pager metadata and next/previous controls', async () => {
    installPagedGet();
    render(<VendorsPage />);

    await screen.findByText('Acme Corp');
    expect(document.body.textContent).toContain('45 items');
    expect(document.body.textContent).toContain('Page 1');
    const prev = screen.getByRole('button', { name: /Prev/ });
    const next = screen.getByRole('button', { name: /Next/ });
    expect(prev.disabled).toBe(true);
    expect(next.disabled).toBe(false);
  });

  it('requests the next page URL and updates controls and rows', async () => {
    installPagedGet();
    render(<VendorsPage />);
    await screen.findByText('Acme Corp');

    fireEvent.click(screen.getByRole('button', { name: /Next/ }));

    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledWith(PAGE_1.next);
    });
    await screen.findByText('Gamma Inc');
    expect(document.body.textContent).toContain('Page 2');
    expect(screen.getByRole('button', { name: /Next/ }).disabled).toBe(true);
    expect(screen.getByRole('button', { name: /Prev/ }).disabled).toBe(false);
  });

  it('returns to the previous page without rebuilding the URL', async () => {
    installPagedGet();
    render(<VendorsPage />);
    await screen.findByText('Acme Corp');
    fireEvent.click(screen.getByRole('button', { name: /Next/ }));
    await screen.findByText('Gamma Inc');

    fireEvent.click(screen.getByRole('button', { name: /Prev/ }));

    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledWith(PAGE_2.previous);
    });
    await screen.findByText('Acme Corp');
    expect(document.body.textContent).toContain('Page 1');
  });

  it('disables paging controls when the list response has no next/previous links', async () => {
    mockGet.mockResolvedValue({ data: VENDORS });
    render(<VendorsPage />);

    await screen.findByText('Acme Corp');
    expect(screen.getByRole('button', { name: /Next/ }).disabled).toBe(true);
    expect(screen.getByRole('button', { name: /Prev/ }).disabled).toBe(true);
  });

  it('returns to page 1 when the search filter changes', async () => {
    installPagedGet();
    render(<VendorsPage />);
    await screen.findByText('Acme Corp');
    fireEvent.click(screen.getByRole('button', { name: /Next/ }));
    await screen.findByText('Gamma Inc');
    expect(document.body.textContent).toContain('Page 2');

    fireEvent.change(screen.getByLabelText('Search'), { target: { value: 'acme' } });

    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledWith('/assets/vendors/?q=acme&page_size=20');
    }, { timeout: 2000 });
    await screen.findByText('Acme Corp');
    expect(document.body.textContent).toContain('Page 1');
  });
});

describe('Vendors page - loading and empty states', () => {
  it('shows a loading skeleton while the list request is pending', async () => {
    let resolveList;
    mockGet.mockImplementation(() => new Promise((res) => { resolveList = res; }));
    render(<VendorsPage />);

    await screen.findByRole('status', { name: 'Loading' });
    resolveList({ data: { results: [], count: 0, next: null, previous: null } });

    await screen.findByText('No vendors found');
    expect(screen.queryByRole('status', { name: 'Loading' })).toBeNull();
  });

  it('shows the empty state when no vendors are returned', async () => {
    mockGet.mockResolvedValue({ data: { results: [], count: 0, next: null, previous: null } });
    render(<VendorsPage />);

    await screen.findByText('No vendors found');
  });
});

describe('VendorForm - create and edit rendering', () => {
  it('renders every field, the create action and cancel behaviour', async () => {
    const onClose = vi.fn();
    render(<VendorForm onSave={vi.fn()} onClose={onClose} />);

    expect(screen.getByRole('heading', { name: 'New Vendor' })).toBeTruthy();
    expect(screen.getByLabelText(/^Name/)).toBeTruthy();
    expect(screen.getByLabelText(/^Code/)).toBeTruthy();
    expect(screen.getByLabelText(/^Contact Person/)).toBeTruthy();
    expect(screen.getByLabelText(/^Email/)).toBeTruthy();
    expect(screen.getByLabelText(/^Phone/)).toBeTruthy();
    expect(screen.getByLabelText(/^Website/)).toBeTruthy();
    expect(screen.getByLabelText(/^Address/)).toBeTruthy();
    expect(screen.getByLabelText(/^Tax\/Registration/)).toBeTruthy();
    expect(screen.getByLabelText(/^Notes/)).toBeTruthy();
    expect(screen.getByLabelText(/^Active/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Create' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('submits the existing form payload on create', async () => {
    const onSave = vi.fn();
    render(<VendorForm onSave={onSave} onClose={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: 'New Co' } });
    fireEvent.change(screen.getByLabelText(/^Code/), { target: { value: 'NEW' } });
    fireEvent.change(screen.getByLabelText(/^Email/), { target: { value: 'ops@new.co' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/assets/vendors/', expect.objectContaining({
        name: 'New Co',
        code: 'NEW',
        email: 'ops@new.co',
        contact_person: '',
        phone: '',
        website: '',
        address: '',
        tax_registration: '',
        notes: '',
        is_active: true,
      }));
    });
    await waitFor(() => expect(onSave).toHaveBeenCalled());
  });

  it('shows backend validation errors and re-enables submission', async () => {
    mockPost.mockRejectedValueOnce({
      response: { status: 400, data: { name: ['This field is required.'] } },
    });
    render(<VendorForm onSave={vi.fn()} onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Create' }));

    await screen.findByText(/name: This field is required\./);
    expect(screen.getByRole('button', { name: 'Create' }).disabled).toBe(false);
  });

  it('disables the submit button and prevents duplicate create requests', async () => {
    let resolvePost;
    mockPost.mockImplementationOnce(() => new Promise((res) => { resolvePost = res; }));
    render(<VendorForm onSave={vi.fn()} onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Create' }));
    const pending = await screen.findByRole('button', { name: 'Saving…' });
    expect(pending.disabled).toBe(true);
    fireEvent.click(pending);
    expect(mockPost).toHaveBeenCalledTimes(1);

    resolvePost({ data: {} });
    await screen.findByRole('button', { name: 'Create' });
    expect(mockPost).toHaveBeenCalledTimes(1);
  });

  it('loads existing values and patches them in edit mode', async () => {
    const onSave = vi.fn();
    render(<VendorForm vendorId={1} onSave={onSave} onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByLabelText(/^Name/).value).toBe('Acme Corp');
    });
    expect(screen.getByRole('heading', { name: 'Edit Vendor' })).toBeTruthy();
    expect(screen.getByLabelText(/^Code/).value).toBe('ACME');
    expect(screen.getByLabelText(/^Email/).value).toBe('dana@acme.io');
    expect(screen.getByLabelText(/^Address/).value).toBe('1 Main St');
    expect(screen.getByLabelText(/^Notes/).value).toBe('Preferred supplier');
    expect(screen.getByLabelText(/^Active/).checked).toBe(true);

    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: 'Acme Corp Ltd' } });
    fireEvent.click(screen.getByRole('button', { name: 'Update' }));

    await waitFor(() => {
      expect(mockPatch).toHaveBeenCalledWith('/assets/vendors/1/', expect.objectContaining({
        name: 'Acme Corp Ltd',
        code: 'ACME',
      }));
    });
    await waitFor(() => expect(onSave).toHaveBeenCalled());
  });

  it('shows a loading state while edit data is fetched', async () => {
    let resolveVendor;
    mockGet.mockImplementationOnce(() => new Promise((res) => { resolveVendor = res; }));
    render(<VendorForm vendorId={1} onSave={vi.fn()} onClose={vi.fn()} />);

    expect(screen.getByRole('status', { name: 'Loading' })).toBeTruthy();
    resolveVendor({ data: VENDORS[0] });

    await waitFor(() => {
      expect(screen.getByLabelText(/^Name/).value).toBe('Acme Corp');
    });
  });

  it('shows a load error when edit data cannot be fetched', async () => {
    mockGet.mockRejectedValueOnce({ response: { status: 404, data: { detail: 'Not found.' } } });
    render(<VendorForm vendorId={1} onSave={vi.fn()} onClose={vi.fn()} />);

    await screen.findByText(/Could not load vendor data\. Not found\./);
  });
});
