import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';

describe('minimal', () => {
  it('renders button', () => {
    render(<button>Click</button>);
    expect(screen.getByRole('button')).toBeTruthy();
  });
});