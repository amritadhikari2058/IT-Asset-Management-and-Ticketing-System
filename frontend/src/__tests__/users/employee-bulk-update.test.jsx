import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';

const { mockPost } = vi.hoisted(() => ({
  mockPost: vi.fn(),
}));

vi.mock('../../api', () => ({
  default: {
    post: (...args) => mockPost(...args),
  },
}));

vi.mock('../../auth', () => ({
  useAuth: () => ({ isStaff: true, user: { role: 'it_support' } }),
}));

import { EmployeeBulkUpdateModal } from '../../pages/bulk/Bulk';

function makeCsvFile(content, name = 'employees.csv') {
  const file = new File([content], name, { type: 'text/csv' });

  // jsdom may not implement File.text(), so provide the browser-compatible method.
  Object.defineProperty(file, 'text', {
    configurable: true,
    value: async () => content,
  });

  return file;
}

const previewResponse = {
  data: {
    affected: 1,
    preview: [
      { employee_id: 'E001', exists: true, is_deleted: false },
    ],
  },
};

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.stubGlobal('confirm', vi.fn(() => true));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('EmployeeBulkUpdateModal', () => {
  it('parses CSV and sends the expected preview payload', async () => {
    const csv = [
      'employee_id,email,phone,home_department,is_active',
      'E001,user@example.com,999,IT,false',
    ].join('\n');

    mockPost.mockResolvedValueOnce(previewResponse);

    render(<EmployeeBulkUpdateModal onClose={() => {}} onUpdated={() => {}} />);

    fireEvent.change(screen.getByLabelText('Employee update CSV'), {
      target: { files: [makeCsvFile(csv)] },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Preview updates' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1));

    expect(mockPost).toHaveBeenCalledWith('/accounts/users/bulk_update/', {
      rows: [
        {
          employee_id: 'E001',
          email: 'user@example.com',
          phone: '999',
          home_department: 'IT',
          is_active: false,
        },
      ],
      preview: true,
    });

    expect(await screen.findByText(/existence check only/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: /Confirm 1 update/ })).toBeTruthy();
  });

  it('requires confirmation and submits the update payload', async () => {
    const csv = [
      'employee_id,job_title',
      'E001,IT Officer',
    ].join('\n');

    const onUpdated = vi.fn();

    mockPost
      .mockResolvedValueOnce(previewResponse)
      .mockResolvedValueOnce({
        data: {
          successful: ['E001'],
          skipped: [],
          failed: [],
        },
      });

    render(<EmployeeBulkUpdateModal onClose={() => {}} onUpdated={onUpdated} />);

    fireEvent.change(screen.getByLabelText('Employee update CSV'), {
      target: { files: [makeCsvFile(csv)] },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Preview updates' }));

    await screen.findByRole('button', { name: /Confirm 1 update/ });

    fireEvent.click(screen.getByRole('button', { name: /Confirm 1 update/ }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(2));

    expect(window.confirm).toHaveBeenCalledTimes(1);
    expect(mockPost).toHaveBeenLastCalledWith('/accounts/users/bulk_update/', {
      rows: [{ employee_id: 'E001', job_title: 'IT Officer' }],
      preview: false,
      confirm: true,
    });

    expect(await screen.findByText(/1 successful/)).toBeTruthy();
    expect(onUpdated).toHaveBeenCalledTimes(1);
  });

  it('rejects role and permission columns before calling the API', async () => {
    const csv = [
      'employee_id,role,can_create_tickets',
      'E001,system_admin,true',
    ].join('\n');

    render(<EmployeeBulkUpdateModal onClose={() => {}} />);

    fireEvent.change(screen.getByLabelText('Employee update CSV'), {
      target: { files: [makeCsvFile(csv)] },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Preview updates' }));

    expect((await screen.findByRole('alert')).textContent).toMatch(/unsupported column/i);
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('rejects invalid is_active values before calling the API', async () => {
    const csv = [
      'employee_id,is_active',
      'E001,yes',
    ].join('\n');

    render(<EmployeeBulkUpdateModal onClose={() => {}} />);

    fireEvent.change(screen.getByLabelText('Employee update CSV'), {
      target: { files: [makeCsvFile(csv)] },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Preview updates' }));

    expect((await screen.findByRole('alert')).textContent).toMatch(/is_active must be true or false/i);
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('rejects duplicate employee IDs in the CSV', async () => {
    const csv = [
      'employee_id,phone',
      'E001,111',
      'E001,222',
    ].join('\n');

    render(<EmployeeBulkUpdateModal onClose={() => {}} />);

    fireEvent.change(screen.getByLabelText('Employee update CSV'), {
      target: { files: [makeCsvFile(csv)] },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Preview updates' }));

    expect((await screen.findByRole('alert')).textContent).toMatch(/duplicate employee_id/i);
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('reports successful, skipped, and failed employee updates', async () => {
    const csv = [
      'employee_id,phone',
      'E001,111',
      'E002,222',
      'E003,333',
    ].join('\n');

    mockPost
      .mockResolvedValueOnce({
        data: {
          affected: 3,
          preview: [
            { employee_id: 'E001', exists: true, is_deleted: false },
            { employee_id: 'E002', exists: true, is_deleted: false },
            { employee_id: 'E003', exists: true, is_deleted: false },
          ],
        },
      })
      .mockResolvedValueOnce({
        data: {
          successful: ['E001'],
          skipped: [
            { employee_id: 'E002', reason: 'insufficient privilege' },
          ],
          failed: [
            { employee_id: 'E003', errors: 'Email already exists.' },
          ],
        },
      });

    render(<EmployeeBulkUpdateModal onClose={() => {}} />);

    fireEvent.change(screen.getByLabelText('Employee update CSV'), {
      target: { files: [makeCsvFile(csv)] },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Preview updates' }));

    await screen.findByRole('button', { name: /Confirm 3 update/ });

    fireEvent.click(screen.getByRole('button', { name: /Confirm 3 update/ }));

    expect(await screen.findByText(/1 successful/)).toBeTruthy();
    expect(screen.getByText(/1 skipped/)).toBeTruthy();
    expect(screen.getByText(/1 failed/)).toBeTruthy();

    expect(screen.getByText('E001')).toBeTruthy();
    expect(screen.getByText('E002')).toBeTruthy();
    expect(screen.getByText('E003')).toBeTruthy();
    expect(screen.getByText('insufficient privilege')).toBeTruthy();
    expect(screen.getByText('Email already exists.')).toBeTruthy();
  });
});