// Entry point. Builds the app shell, wires the router, and boots.

import { mountAppShell } from './components/app-shell.js';
import { mountToastContainer } from './components/toast.js';
import { setOutletProvider, startRouter } from './router.js';
import './services/auth-service.js'; // registers auth header/401 handlers with the API client

const root = document.getElementById('app');
const { loginContainer, shellContainer, contentContainer } = mountAppShell(root);

setOutletProvider(() => ({ loginContainer, shellContainer, contentContainer }));
mountToastContainer();
startRouter();
