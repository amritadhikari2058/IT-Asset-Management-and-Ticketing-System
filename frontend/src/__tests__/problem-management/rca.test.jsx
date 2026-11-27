import { describe, test, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { RCA } from '../../components/problem-management/rca';
import {
  createFactor, createFiveWhy, createRCA, deleteFactor, deleteFiveWhy,
  editFactor, editFiveWhy, editRCA, fiveWhys, getRCA, rejectRCA,
  rootCauseFactors, submitRCA, supersedeRCA,
} from '../../services/problem-management';

afterEach(cleanup);

vi.mock('../../services/problem-management', () => ({
  approveRCA: vi.fn(),
  createFactor: vi.fn(),
  createFiveWhy: vi.fn(),
  createRCA: vi.fn(),
  deleteFactor: vi.fn(),
  deleteFiveWhy: vi.fn(),
  editFactor: vi.fn(),
  editFiveWhy: vi.fn(),
  editRCA: vi.fn(),
  fiveWhys: vi.fn(),
  getRCA: vi.fn(),
  problemDetail: vi.fn(),
  rejectRCA: vi.fn(),
  rootCauseFactors: vi.fn(),
  submitRCA: vi.fn(),
  supersedeRCA: vi.fn(),
}));

const auth = vi.hoisted(() => ({
  current: { isStaff: true, isManagerOrAdmin: true, user: { username: 'manager' } },
}));
vi.mock('../../auth', () => ({ useAuth: () => auth.current }));

const RCA_RECORD = {
  id: 1,
  problem: 1,
  title: 'Test RCA',
  description: 'Test description',
  analysis_method: 'five_whys',
  findings: 'Disk was full',
  concluded_at: '2026-01-02T03:04:05Z',
  status: 'draft',
  version: 3,
  created_by_username: 'author',
};

const WHY_ONE = {
  id: 11, analysis: 1, question_number: 1,
  question_text: 'Why did it fail?', answer: 'Disk was full',
};
const WHY_TWO = {
  id: 12, analysis: 1, question_number: 2,
  question_text: 'Why was the disk full?', answer: 'Alerting was missing',
};
const FACTOR_ONE = {
  id: 21, analysis: 1, category: 'machine',
  factor: 'Disk capacity', contribution: 'No capacity alerting',
};
const FACTOR_TWO = {
  id: 22, analysis: 1, category: 'method',
  factor: 'Capacity review', contribution: '',
};

const renderRca = (props = {}) => render(
  <MemoryRouter>
    <RCA problemId="1" {...props} />
  </MemoryRouter>,
);

describe('RCA', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    auth.current = { isStaff: true, isManagerOrAdmin: true, user: { username: 'manager' } };
    getRCA.mockResolvedValue(RCA_RECORD);
    editRCA.mockResolvedValue({ ...RCA_RECORD, version: 4 });
    fiveWhys.mockResolvedValue({ results: [] });
    rootCauseFactors.mockResolvedValue({ results: [] });
    window.confirm = vi.fn(() => true);
  });

  test('renders RCA create form', async () => {
    renderRca();
    expect((await screen.findAllByText('Create RCA')).length).toBeGreaterThan(0);
  });

  test('renders RCA edit form', async () => {
    renderRca({ rcaId: '1' });
    expect(await screen.findByText('Title: Test RCA')).toBeTruthy();
  });

  test('renders submit/approve/reject buttons for manager', async () => {
    renderRca({ rcaId: '1' });
    expect(await screen.findByText('Submit RCA')).toBeTruthy();
    expect(screen.getByText('Approve RCA')).toBeTruthy();
    expect(screen.getByText('Reject RCA')).toBeTruthy();
  });

  test('sends the loaded version when updating', async () => {
    renderRca({ rcaId: '1' });
    fireEvent.click(await screen.findByText('Update RCA'));
    await waitFor(() => expect(editRCA).toHaveBeenCalledWith(
      '1',
      expect.objectContaining({ title: 'Test RCA', description: 'Test description' }),
      3,
    ));
  });

  test('blocks self-approval', async () => {
    getRCA.mockResolvedValue({ ...RCA_RECORD, created_by_username: 'manager' });
    renderRca({ rcaId: '1' });
    expect(await screen.findByText('You cannot approve your own RCA.')).toBeTruthy();
    const approve = await screen.findByText('Approve RCA');
    expect(approve.disabled).toBe(true);
  });

  test('keeps a final state immutable', async () => {
    getRCA.mockResolvedValue({ ...RCA_RECORD, status: 'approved' });
    renderRca({ rcaId: '1' });
    expect(await screen.findByText(/can no longer be edited/)).toBeTruthy();
    expect(screen.queryByText('Update RCA')).toBeNull();
    expect(screen.queryByText('Approve RCA')).toBeNull();
    expect(screen.getByLabelText(/Analysis method/).disabled).toBe(true);
    expect(screen.getByLabelText('Findings').disabled).toBe(true);
    expect(screen.getByLabelText('Concluded at').disabled).toBe(true);
  });

  test('populates the saved analysis fields when editing', async () => {
    renderRca({ rcaId: '1' });

    expect((await screen.findByLabelText(/Analysis method/)).value).toBe('five_whys');
    expect(screen.getByLabelText('Findings').value).toBe('Disk was full');
    expect(screen.getByLabelText('Concluded at').value).toBe('2026-01-02T03:04:05');
  });

  test('includes analysis fields in updates and preserves untouched values', async () => {
    renderRca({ rcaId: '1' });

    fireEvent.change(await screen.findByLabelText(/Title/), {
      target: { value: 'Updated RCA' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Update RCA' }));

    await waitFor(() => expect(editRCA).toHaveBeenCalledWith('1', {
      title: 'Updated RCA',
      description: 'Test description',
      analysis_method: 'five_whys',
      findings: 'Disk was full',
      concluded_at: '2026-01-02T03:04:05Z',
    }, 3));
  });

  test('sends analysis_method on create without update-only fields', async () => {
    renderRca();

    fireEvent.change(await screen.findByLabelText(/Title/), {
      target: { value: 'Created RCA' },
    });
    fireEvent.change(screen.getByLabelText(/Analysis method/), {
      target: { value: 'fishbone' },
    });
    expect(screen.queryByLabelText('Findings')).toBeNull();
    expect(screen.queryByLabelText('Concluded at')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Create RCA' }));

    await waitFor(() => expect(createRCA).toHaveBeenCalledWith({
      problem: 1,
      title: 'Created RCA',
      description: '',
      analysis_method: 'fishbone',
    }));
  });

  test('blocks updates when the analysis method is empty', async () => {
    renderRca({ rcaId: '1' });

    fireEvent.change(await screen.findByLabelText(/Analysis method/), {
      target: { value: '' },
    });

    expect(screen.getByRole('button', { name: 'Update RCA' }).disabled).toBe(true);
    expect(editRCA).not.toHaveBeenCalled();
  });

  test('clears concluded_at with null on update', async () => {
    renderRca({ rcaId: '1' });

    fireEvent.change(await screen.findByLabelText('Concluded at'), {
      target: { value: '' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Update RCA' }));

    await waitFor(() => expect(editRCA).toHaveBeenCalledWith(
      '1',
      expect.objectContaining({ concluded_at: null }),
      3,
    ));
  });

  test('shows backend field validation errors for analysis fields', async () => {
    editRCA.mockRejectedValueOnce({
      response: {
        status: 400,
        data: { concluded_at: ['Datetime has wrong format.'] },
      },
    });

    renderRca({ rcaId: '1' });
    fireEvent.click(await screen.findByRole('button', { name: 'Update RCA' }));

    expect(await screen.findByText('Concluded at: Datetime has wrong format.')).toBeTruthy();
    expect(screen.queryByText('Update succeeded.')).toBeNull();
  });

  test('disables analysis saves while an update is in flight', async () => {
    let resolveUpdate;
    editRCA.mockImplementation(() => new Promise((resolve) => {
      resolveUpdate = resolve;
    }));

    renderRca({ rcaId: '1' });
    const update = await screen.findByRole('button', { name: 'Update RCA' });
    fireEvent.click(update);

    expect(editRCA).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Update RCA' }).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Update RCA' }));
    expect(editRCA).toHaveBeenCalledTimes(1);

    resolveUpdate({ ...RCA_RECORD, version: 4 });
    expect(await screen.findByText('Update succeeded.')).toBeTruthy();
  });

  test('switches to the created RCA and reloads it', async () => {
    const created = {
      id: 12, problem: 1, title: 'Created RCA', description: 'New cause',
      status: 'draft', version: 1,
    };
    createRCA.mockResolvedValue(created);
    getRCA.mockResolvedValue(created);

    renderRca();
    fireEvent.change(await screen.findByLabelText(/Title/), {
      target: { value: 'Created RCA' },
    });
    fireEvent.change(screen.getByLabelText('Description'), {
      target: { value: 'New cause' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create RCA' }));

    await waitFor(() => {
      expect(createRCA).toHaveBeenCalledWith({
        problem: 1,
        title: 'Created RCA',
        description: 'New cause',
        analysis_method: 'five_whys',
      });
    });
    expect(await screen.findByText('Title: Created RCA')).toBeTruthy();
    await waitFor(() => expect(getRCA).toHaveBeenCalledWith(12));
    expect(screen.getByRole('button', { name: 'Update RCA' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Add Why' })).toBeTruthy();
  });

  test('shows staff lifecycle controls without governance controls', async () => {
    auth.current = { isStaff: true, isManagerOrAdmin: false, user: { username: 'support' } };

    renderRca({ rcaId: '1' });

    expect(await screen.findByText('Title: Test RCA')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Update RCA' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Submit RCA' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Approve RCA' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Reject RCA' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Supersede' })).toBeNull();
  });

  test('hides all mutations from an account without Problem Management staff access', async () => {
    auth.current = { isStaff: false, isManagerOrAdmin: false, user: { username: 'viewer' } };

    renderRca({ rcaId: '1' });

    expect(await screen.findByText('Title: Test RCA')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Update RCA' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Submit RCA' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Approve RCA' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Add Why' })).toBeNull();
    expect(screen.getByLabelText(/Analysis method/).disabled).toBe(true);
    expect(screen.getByLabelText('Findings').disabled).toBe(true);
    expect(screen.getByLabelText('Concluded at').disabled).toBe(true);
    expect(screen.getByText(/Saved findings:/)).toBeTruthy();
  });

  test('requires a rejection reason and sends it with the loaded version', async () => {
    renderRca({ rcaId: '1' });

    fireEvent.click(await screen.findByRole('button', { name: 'Reject RCA' }));
    expect(await screen.findByText('A rejection reason is required.')).toBeTruthy();
    expect(rejectRCA).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/Rejection reason/), {
      target: { value: 'Weak evidence' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Reject RCA' }));

    await waitFor(() => {
      expect(rejectRCA).toHaveBeenCalledWith('1', {
        reason: 'Weak evidence',
        expected_record_version: 3,
      });
    });
  });

  test('sends submit and supersede through their own endpoints', async () => {
    renderRca({ rcaId: '1' });

    fireEvent.click(await screen.findByRole('button', { name: 'Submit RCA' }));
    await waitFor(() => {
      expect(submitRCA).toHaveBeenCalledWith('1', { expected_record_version: 3 });
    });

    fireEvent.click(screen.getByRole('button', { name: 'Supersede' }));
    await waitFor(() => {
      expect(supersedeRCA).toHaveBeenCalledWith('1', { expected_record_version: 3 });
    });
  });

  test('shows a backend load failure and keeps existing records intact', async () => {
    getRCA.mockRejectedValueOnce({
      response: { status: 500, data: { detail: 'RCA service unavailable.' } },
    });

    renderRca({ rcaId: '1' });

    expect(await screen.findByText('RCA service unavailable.')).toBeTruthy();
    expect(editRCA).not.toHaveBeenCalled();
  });

  test('lists only the active RCA whys in question-number order', async () => {
    fiveWhys.mockResolvedValue({
      results: [
        { ...WHY_TWO, analysis: 1 },
        { ...WHY_ONE, analysis: 1 },
        {
          id: 99, analysis: 2, question_number: 1,
          question_text: 'Why from another RCA?', answer: 'Other',
        },
      ],
    });

    renderRca({ rcaId: '1' });

    const first = await screen.findByText(/1\. Why did it fail\?/);
    const second = screen.getByText(/2\. Why was the disk full\?/);
    expect(
      first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.queryByText(/Why from another RCA/)).toBeNull();
    expect(fiveWhys).toHaveBeenCalledWith('1');
  });

  test('lists only the active RCA factors', async () => {
    rootCauseFactors.mockResolvedValue({
      results: [
        FACTOR_TWO,
        FACTOR_ONE,
        { id: 88, analysis: 2, category: 'people', factor: 'Other RCA factor' },
      ],
    });

    renderRca({ rcaId: '1' });

    expect(
      await screen.findByText('Machine: Disk capacity — No capacity alerting'),
    ).toBeTruthy();
    expect(screen.getByText('Method: Capacity review')).toBeTruthy();
    expect(screen.queryByText(/Other RCA factor/)).toBeNull();
    expect(rootCauseFactors).toHaveBeenCalledWith('1');
  });

  test('creates a Five Why with the required fields', async () => {
    renderRca({ rcaId: '1' });

    fireEvent.change(await screen.findByLabelText(/^Why question\s*\*$/), {
      target: { value: 'Why did the service stop?' },
    });
    fireEvent.change(screen.getByLabelText(/^Question number\s*\*$/), {
      target: { value: '3' },
    });
    fireEvent.change(screen.getByLabelText(/^Answer\s*\*$/), {
      target: { value: 'The database was unavailable.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add Why' }));

    await waitFor(() => expect(createFiveWhy).toHaveBeenCalledWith({
      analysis: 1,
      question_number: 3,
      question_text: 'Why did the service stop?',
      answer: 'The database was unavailable.',
    }));
    expect(await screen.findByText('Add Why succeeded.')).toBeTruthy();
  });

  test('requires a question and answer before adding a Five Why', async () => {
    renderRca({ rcaId: '1' });

    const add = await screen.findByRole('button', { name: 'Add Why' });
    expect(add.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText(/^Why question\s*\*$/), {
      target: { value: 'Why?' },
    });
    expect(add.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText(/^Answer\s*\*$/), {
      target: { value: 'Because.' },
    });
    expect(add.disabled).toBe(false);
  });

  test('edits a Five Why without changing its question number', async () => {
    fiveWhys.mockResolvedValue({ results: [WHY_ONE] });

    renderRca({ rcaId: '1' });
    fireEvent.click(await screen.findByRole('button', { name: 'Edit why 11' }));
    fireEvent.change(screen.getByLabelText(/^Edit why question #1\s*\*$/), {
      target: { value: 'Updated question' },
    });
    fireEvent.change(screen.getByLabelText(/^Edit why answer\s*\*$/), {
      target: { value: 'Updated answer' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save Why' }));

    await waitFor(() => expect(editFiveWhy).toHaveBeenCalledWith(11, {
      question_text: 'Updated question',
      answer: 'Updated answer',
    }));
    expect(await screen.findByText('Update Why succeeded.')).toBeTruthy();
  });

  test('deletes a Five Why only after confirmation', async () => {
    fiveWhys.mockResolvedValue({ results: [WHY_ONE] });

    renderRca({ rcaId: '1' });
    const remove = await screen.findByRole('button', { name: 'Delete why 11' });

    window.confirm.mockReturnValueOnce(false);
    fireEvent.click(remove);
    expect(window.confirm).toHaveBeenCalledWith('Delete Five Why #1?');
    expect(deleteFiveWhy).not.toHaveBeenCalled();

    fireEvent.click(remove);
    await waitFor(() => expect(deleteFiveWhy).toHaveBeenCalledWith(11));
    expect(await screen.findByText('Delete Why succeeded.')).toBeTruthy();
  });

  test('creates, edits, and deletes root-cause factors', async () => {
    rootCauseFactors.mockResolvedValue({ results: [FACTOR_ONE] });

    renderRca({ rcaId: '1' });

    fireEvent.change(await screen.findByLabelText(/^Factor category/), {
      target: { value: 'environment' },
    });
    fireEvent.change(screen.getByLabelText(/^Factor\s*\*$/), {
      target: { value: 'Power stability' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add Factor' }));

    await waitFor(() => expect(createFactor).toHaveBeenCalledWith({
      analysis: 1,
      category: 'environment',
      factor: 'Power stability',
    }));
    expect(await screen.findByText('Add Factor succeeded.')).toBeTruthy();

    fireEvent.click(await screen.findByRole('button', { name: 'Edit factor 21' }));
    fireEvent.change(screen.getByLabelText(/^Edit factor category/), {
      target: { value: 'method' },
    });
    fireEvent.change(screen.getByLabelText(/^Edit factor\s*\*$/), {
      target: { value: 'Disk capacity review' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save Factor' }));

    await waitFor(() => expect(editFactor).toHaveBeenCalledWith(21, {
      category: 'method',
      factor: 'Disk capacity review',
    }));
    expect(await screen.findByText('Update Factor succeeded.')).toBeTruthy();

    window.confirm.mockReturnValueOnce(true);
    fireEvent.click(await screen.findByRole('button', { name: 'Delete factor 21' }));
    expect(window.confirm).toHaveBeenCalledWith(
      'Delete root-cause factor "Disk capacity"?',
    );
    await waitFor(() => expect(deleteFactor).toHaveBeenCalledWith(21));
    expect(await screen.findByText('Delete Factor succeeded.')).toBeTruthy();
  });

  test('only offers backend-supported factor categories', async () => {
    renderRca({ rcaId: '1' });

    const select = await screen.findByLabelText(/^Factor category/);
    expect(Array.from(select.options).map((option) => option.value)).toEqual([
      'people', 'method', 'machine', 'material', 'environment', 'other',
    ]);
  });

  test('shows empty states for both sections', async () => {
    renderRca({ rcaId: '1' });

    expect(await screen.findByText('No Five Whys recorded.')).toBeTruthy();
    expect(screen.getByText('No root-cause factors recorded.')).toBeTruthy();
  });

  test('shows independent loading states for whys and factors', async () => {
    let resolveWhys;
    fiveWhys.mockImplementation(() => new Promise((resolve) => {
      resolveWhys = resolve;
    }));
    rootCauseFactors.mockResolvedValue({ results: [] });

    renderRca({ rcaId: '1' });

    expect(await screen.findByText('Loading Five Whys…')).toBeTruthy();
    expect(await screen.findByText('No root-cause factors recorded.')).toBeTruthy();

    resolveWhys({ results: [] });
    expect(await screen.findByText('No Five Whys recorded.')).toBeTruthy();
  });

  test('shows independent load errors for whys and factors', async () => {
    fiveWhys.mockRejectedValue({
      response: { status: 500, data: { detail: 'Whys unavailable.' } },
    });
    rootCauseFactors.mockResolvedValue({ results: [FACTOR_ONE] });

    renderRca({ rcaId: '1' });

    expect(await screen.findByText('Whys unavailable.')).toBeTruthy();
    expect(
      await screen.findByText('Machine: Disk capacity — No capacity alerting'),
    ).toBeTruthy();

    cleanup();
    fiveWhys.mockResolvedValue({ results: [WHY_ONE] });
    rootCauseFactors.mockRejectedValue({
      response: { status: 500, data: { detail: 'Factors unavailable.' } },
    });

    renderRca({ rcaId: '1' });

    expect(await screen.findByText('Factors unavailable.')).toBeTruthy();
    expect(await screen.findByText(/1\. Why did it fail\?/)).toBeTruthy();
  });

  test('shows why mutation failures inside the Five Whys section', async () => {
    fiveWhys.mockResolvedValue({ results: [WHY_ONE] });
    createFiveWhy.mockRejectedValueOnce({
      response: {
        status: 400,
        data: { analysis: ['Why with question_number 1 already exists.'] },
      },
    });
    editFiveWhy.mockRejectedValueOnce({
      response: { status: 400, data: { answer: ['This field may not be blank.'] } },
    });
    deleteFiveWhy.mockRejectedValueOnce({
      response: {
        status: 400,
        data: { analysis: ["Whys cannot be deleted when RCA is 'in_review'."] },
      },
    });

    renderRca({ rcaId: '1' });

    fireEvent.change(await screen.findByLabelText(/^Why question\s*\*$/), {
      target: { value: 'Duplicate?' },
    });
    fireEvent.change(screen.getByLabelText(/^Answer\s*\*$/), {
      target: { value: 'Because.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add Why' }));
    expect(
      await screen.findByText('RCA: Why with question_number 1 already exists.'),
    ).toBeTruthy();
    expect(screen.queryByText('Add Why succeeded.')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Edit why 11' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save Why' }));
    expect(await screen.findByText('Answer: This field may not be blank.')).toBeTruthy();
    expect(screen.queryByText('Update Why succeeded.')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete why 11' }));
    expect(
      await screen.findByText("RCA: Whys cannot be deleted when RCA is 'in_review'."),
    ).toBeTruthy();
    expect(screen.queryByText('Delete Why succeeded.')).toBeNull();
  });

  test('shows factor mutation failures inside the root-cause factors section', async () => {
    rootCauseFactors.mockResolvedValue({ results: [FACTOR_ONE] });
    createFactor.mockRejectedValueOnce({
      response: {
        status: 400,
        data: { analysis: ["A factor with category 'people' already exists."] },
      },
    });
    editFactor.mockRejectedValueOnce({
      response: { status: 400, data: { category: ['Invalid category.'] } },
    });
    deleteFactor.mockRejectedValueOnce({
      response: {
        status: 400,
        data: { analysis: ["Factors cannot be deleted when RCA is 'in_review'."] },
      },
    });

    renderRca({ rcaId: '1' });

    fireEvent.change(await screen.findByLabelText(/^Factor\s*\*$/), {
      target: { value: 'New factor' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add Factor' }));
    expect(
      await screen.findByText("RCA: A factor with category 'people' already exists."),
    ).toBeTruthy();
    expect(screen.queryByText('Add Factor succeeded.')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Edit factor 21' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save Factor' }));
    expect(await screen.findByText('Category: Invalid category.')).toBeTruthy();
    expect(screen.queryByText('Update Factor succeeded.')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete factor 21' }));
    expect(
      await screen.findByText("RCA: Factors cannot be deleted when RCA is 'in_review'."),
    ).toBeTruthy();
    expect(screen.queryByText('Delete Factor succeeded.')).toBeNull();
  });

  test('prevents duplicate why and factor submissions while a mutation is in flight', async () => {
    let resolveWhy;
    let resolveFactor;
    createFiveWhy.mockImplementation(() => new Promise((resolve) => {
      resolveWhy = resolve;
    }));
    createFactor.mockImplementation(() => new Promise((resolve) => {
      resolveFactor = resolve;
    }));

    renderRca({ rcaId: '1' });

    fireEvent.change(await screen.findByLabelText(/^Why question\s*\*$/), {
      target: { value: 'Why?' },
    });
    fireEvent.change(screen.getByLabelText(/^Answer\s*\*$/), {
      target: { value: 'Because.' },
    });
    const addWhy = screen.getByRole('button', { name: 'Add Why' });
    fireEvent.click(addWhy);
    expect(createFiveWhy).toHaveBeenCalledTimes(1);
    fireEvent.click(addWhy);
    expect(createFiveWhy).toHaveBeenCalledTimes(1);

    resolveWhy({ id: 31 });
    expect(await screen.findByText('Add Why succeeded.')).toBeTruthy();

    fireEvent.change(screen.getByLabelText(/^Factor\s*\*$/), {
      target: { value: 'Power stability' },
    });
    const addFactor = screen.getByRole('button', { name: 'Add Factor' });
    fireEvent.click(addFactor);
    expect(createFactor).toHaveBeenCalledTimes(1);
    fireEvent.click(addFactor);
    expect(createFactor).toHaveBeenCalledTimes(1);

    resolveFactor({ id: 32 });
    expect(await screen.findByText('Add Factor succeeded.')).toBeTruthy();
  });

  test('keeps Five Whys and factors read-only for non-staff users', async () => {
    auth.current = { isStaff: false, isManagerOrAdmin: false, user: { username: 'viewer' } };
    fiveWhys.mockResolvedValue({ results: [WHY_ONE] });
    rootCauseFactors.mockResolvedValue({ results: [FACTOR_ONE] });

    renderRca({ rcaId: '1' });

    expect(await screen.findByText(/1\. Why did it fail\?/)).toBeTruthy();
    expect(
      screen.getByText('Machine: Disk capacity — No capacity alerting'),
    ).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Add Why' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Edit why 11' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Delete why 11' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Add Factor' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Edit factor 21' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Delete factor 21' })).toBeNull();
  });

  test('keeps a final-state RCA whys and factors read-only', async () => {
    getRCA.mockResolvedValue({ ...RCA_RECORD, status: 'approved' });
    fiveWhys.mockResolvedValue({ results: [WHY_ONE] });
    rootCauseFactors.mockResolvedValue({ results: [FACTOR_ONE] });

    renderRca({ rcaId: '1' });

    expect(await screen.findByText(/1\. Why did it fail\?/)).toBeTruthy();
    expect(
      screen.getByText('Machine: Disk capacity — No capacity alerting'),
    ).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Add Why' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Edit why 11' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Delete why 11' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Add Factor' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Edit factor 21' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Delete factor 21' })).toBeNull();
  });

  test('allows edits in review but hides deletes until the RCA is draft', async () => {
    getRCA.mockResolvedValue({ ...RCA_RECORD, status: 'in_review' });
    fiveWhys.mockResolvedValue({ results: [WHY_ONE] });
    rootCauseFactors.mockResolvedValue({ results: [FACTOR_ONE] });

    renderRca({ rcaId: '1' });

    expect(await screen.findByRole('button', { name: 'Edit why 11' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Delete why 11' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Add Why' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Edit factor 21' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Delete factor 21' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Add Factor' })).toBeTruthy();
  });
});


