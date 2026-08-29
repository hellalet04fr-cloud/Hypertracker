import '@testing-library/jest-dom/vitest'

// jsdom ne fournit ni matchMedia ni ResizeObserver ni le contexte 2D. Les
// stubber ici plutot que dans chaque test evite que le manque se transforme en
// « composant non testable » — un composant qu'on ne teste pas est un composant
// dont on ignore les etats.
if (!window.matchMedia) {
  window.matchMedia = (q: string) =>
    ({
      matches: false,
      media: q,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList
}

if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
}
