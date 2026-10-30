import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';
import reportWebVitals from './reportWebVitals';
import { BrowserRouter as Router } from 'react-router-dom';
import { AuthProvider } from './components/AuthContext';
import './pwa/installPrompt'; // catch the install prompt as early as possible

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <AuthProvider>
      <Router>
        <App /> {/* Render App to include routing */}
      </Router>
    </AuthProvider>
  </React.StrictMode>
);

reportWebVitals();

// Installable app (PWA): public/service-worker.js. Production only, so `npm start` never gets
// a worker in the way of hot reload.
if (process.env.NODE_ENV === 'production' && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/service-worker.js').catch(() => {});
  });
}

