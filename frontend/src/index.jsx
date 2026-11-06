import React, { Suspense } from 'react';
import ReactDOM from 'react-dom/client';
import './design'; // design system: tokens, base styles, shared components (first)
import './i18n'; // translations: picks the language before the first render
import './index.css';
import App from './App';
import reportWebVitals from './reportWebVitals';
import { BrowserRouter as Router } from 'react-router-dom';
import { AuthProvider } from './components/AuthContext';
import './pwa/installPrompt'; // catch the install prompt as early as possible
import { startSpatialNavigation } from './tv/spatialNavigation';
import './tv/focus.css'; // one focus look for keyboard / TV remote
import { BrandLoader } from './design';

startSpatialNavigation(); // TV remote / keyboard: arrows, Enter, Back

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    {/* a language's texts are downloaded on first use: the brand loader shows meanwhile */}
    <Suspense fallback={<BrandLoader page />}>
      <AuthProvider>
        <Router>
          <App /> {/* Render App to include routing */}
        </Router>
      </AuthProvider>
    </Suspense>
  </React.StrictMode>
);

reportWebVitals();

// Installable app (PWA): public/service-worker.js. Production only, so `npm start` never gets
// a worker in the way of hot reload.
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/service-worker.js').catch(() => {});
  });
}

