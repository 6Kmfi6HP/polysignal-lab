/**
 * Input: '@testing-library/jest-dom/vitest', { cleanup } from '@testing-library/react', { afterEach, vi } from 'vitest', @testing-library/react, vitest
 * Output: ResizeObserverMock
 * Pos: Application code
 *
 * 🔄 Self-reference: When this file changes, update this header
 */







import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

afterEach(() => {
  cleanup()
})

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

Object.defineProperty(window, 'ResizeObserver', {
  writable: true,
  value: ResizeObserverMock,
})

window.HTMLElement.prototype.scrollIntoView = vi.fn()
