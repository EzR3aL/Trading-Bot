import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './index.css'
import './i18n/config'
import { installGlobalErrorHandler } from './lib/globalErrorHandler'

// Attach top-level unhandledrejection + error listeners before React mounts
// so async failures during render (e.g. lazy chunk load) are still captured.
installGlobalErrorHandler()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
)
