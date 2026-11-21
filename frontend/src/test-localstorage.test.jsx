import { describe, it, expect } from 'vitest';

describe('localStorage test', () => {
  it('should have localStorage mock', () => {
    // This test just verifies the setup is working
    expect(window.localStorage).toBeDefined();
    expect(window.localStorage.getItem).toBeDefined();
  });
});
