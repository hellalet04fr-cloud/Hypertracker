import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import '@/design/jetons.css'
import { routeur } from '@/app/routes'

const racine = document.getElementById('racine')
if (!racine) throw new Error('#racine absent')

createRoot(racine).render(
  <StrictMode>
    <RouterProvider router={routeur} />
  </StrictMode>,
)
