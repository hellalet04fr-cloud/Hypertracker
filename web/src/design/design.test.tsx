import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { renderHook } from '@testing-library/react'
import { Mono, Stack, Surface, Text, VisuallyHidden } from './primitives'
import { RACCOURCIS, dansSaisie, useRaccourcis } from './keymap'
import { AA, composer, lireCouleur, ratio, seuilPour } from './contraste'

describe('primitives', () => {
  it('les chiffres sont toujours tabulaires', () => {
    render(<Mono>100.0</Mono>)
    const el = screen.getByText('100.0')
    expect(el.className).toContain('mono')
  })

  it('l’espacement ne peut prendre qu’une valeur du rythme', () => {
    // Le contrôle est dans le TYPE : `espace={9}` ne compile pas. Ici on vérifie
    // que la valeur autorisée est bien appliquée.
    const { container } = render(<Stack espace={12} />)
    expect((container.firstChild as HTMLElement).style.gap).toBe('12px')
  })

  it('Surface peint explicitement son niveau', () => {
    const { container } = render(<Surface niveau="panneau" filet="bas" fort />)
    const cls = (container.firstChild as HTMLElement).className
    expect(cls).toContain('panneau')
    expect(cls).toContain('filet_bas')
    expect(cls).toContain('fort')
  })

  it('VisuallyHidden reste dans l’arbre d’accessibilité', () => {
    render(<VisuallyHidden>contexte</VisuallyHidden>)
    expect(screen.getByText('contexte')).toBeInTheDocument()
  })

  it('Text coupe à N lignes sans tronquer le DOM', () => {
    render(<Text lignes={2}>une phrase longue</Text>)
    expect(screen.getByText('une phrase longue').className).toContain('coupe')
  })
})

describe('keymap', () => {
  it('pose UN SEUL écouteur', () => {
    const ajout = vi.spyOn(document, 'addEventListener')
    const retrait = vi.spyOn(document, 'removeEventListener')
    const { unmount } = renderHook(() => useRaccourcis({ suivant: () => {} }))
    expect(ajout.mock.calls.filter((c) => c[0] === 'keydown')).toHaveLength(1)
    unmount()
    expect(retrait.mock.calls.filter((c) => c[0] === 'keydown')).toHaveLength(1)
    ajout.mockRestore()
    retrait.mockRestore()
  })

  it('« j » dans un champ de saisie est un « j », pas un déplacement', () => {
    const suivant = vi.fn()
    renderHook(() => useRaccourcis({ suivant }))
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'j', bubbles: true }))
    expect(suivant).not.toHaveBeenCalled()
    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'j', bubbles: true }))
    expect(suivant).toHaveBeenCalledTimes(1)
    input.remove()
  })

  it('Échap traverse un champ de saisie — sortir doit toujours marcher', () => {
    const fermer = vi.fn()
    renderHook(() => useRaccourcis({ fermer }))
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(fermer).toHaveBeenCalled()
    input.remove()
  })

  it('laisse les combinaisons au navigateur', () => {
    const recherche = vi.fn()
    renderHook(() => useRaccourcis({ recherche }))
    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: '/', ctrlKey: true, bubbles: true }))
    expect(recherche).not.toHaveBeenCalled()
  })

  it('chaque raccourci porte un libellé — l’aide EST le registre', () => {
    for (const r of RACCOURCIS) {
      expect(r.libelle.length).toBeGreaterThan(3)
      expect(r.touches.length).toBeGreaterThan(0)
    }
  })

  it('reconnaît un champ de saisie', () => {
    const i = document.createElement('textarea')
    expect(dansSaisie(i)).toBe(true)
    expect(dansSaisie(document.createElement('div'))).toBe(false)
  })
})

describe('contraste', () => {
  const FOND = lireCouleur('#0a0d10')!.rgb

  it('mesure les jetons de texte au-dessus du plancher AA', () => {
    for (const c of ['#fbfcfd', '#e8edf1', '#93a7b4', '#7c93a3', '#f0a93b', '#e4695c']) {
      expect(ratio(lireCouleur(c)!.rgb, FOND)).toBeGreaterThanOrEqual(AA)
    }
  })

  it('confirme que le jeton banni échouait bien', () => {
    // #4C5D6B portait la moitié du texte de la version précédente, à 2,84:1.
    expect(ratio(lireCouleur('#4c5d6b')!.rgb, FOND)).toBeLessThan(AA)
  })

  it('lit les trois notations de couleur', () => {
    expect(lireCouleur('#fff')!.rgb).toEqual([255, 255, 255])
    expect(lireCouleur('rgb(10, 13, 16)')!.rgb).toEqual([10, 13, 16])
    expect(lireCouleur('rgba(10, 13, 16, 0.5)')!.alpha).toBe(0.5)
    expect(lireCouleur('nawak')).toBeNull()
  })

  it('compose un premier plan translucide avant de mesurer', () => {
    expect(composer([255, 255, 255], [0, 0, 0], 0.5)).toEqual([127.5, 127.5, 127.5])
  })

  it('applique le seuil grand texte au bon endroit', () => {
    expect(seuilPour(13, 400)).toBe(AA)
    expect(seuilPour(24, 400)).toBe(3)
    expect(seuilPour(19, 600)).toBe(3)
    expect(seuilPour(19, 400)).toBe(AA)
  })
})
