// Login screen. Handles loading/error states and delegates the actual
// JWT-vs-Basic detection to auth-service.login().

import { login } from '../services/auth-service.js';
import { navigate } from '../router.js';
import { ApiError } from '../api/client.js';

export function render(container) {
  container.replaceChildren();

  const wrapper = document.createElement('div');
  wrapper.className = 'login-page';

  const card = document.createElement('form');
  card.className = 'login-card';
  card.noValidate = true;

  const title = document.createElement('h1');
  title.className = 'login-card__title';
  title.textContent = 'IRIS Command Center';

  const subtitle = document.createElement('p');
  subtitle.className = 'login-card__subtitle';
  subtitle.textContent = 'Sign in with your InterSystems IRIS credentials.';

  const errorBanner = document.createElement('div');
  errorBanner.className = 'form-error';
  errorBanner.hidden = true;
  errorBanner.setAttribute('role', 'alert');

  const usernameField = buildField('username', 'Username', 'text', 'username');
  const passwordField = buildField('password', 'Password', 'password', 'current-password');

  const submitButton = document.createElement('button');
  submitButton.type = 'submit';
  submitButton.className = 'button button--primary login-card__submit';

  const spinner = document.createElement('span');
  spinner.className = 'spinner';
  spinner.hidden = true;

  const submitLabel = document.createElement('span');
  submitLabel.textContent = 'Sign in';

  submitButton.append(spinner, submitLabel);

  card.append(title, subtitle, errorBanner, usernameField.wrapper, passwordField.wrapper, submitButton);
  wrapper.append(card);
  container.append(wrapper);

  function setLoading(isLoading) {
    submitButton.disabled = isLoading;
    spinner.hidden = !isLoading;
    submitLabel.textContent = isLoading ? 'Signing in…' : 'Sign in';
  }

  function showError(message) {
    errorBanner.textContent = message;
    errorBanner.hidden = false;
  }

  function clearError() {
    errorBanner.hidden = true;
    errorBanner.textContent = '';
  }

  card.addEventListener('submit', async (event) => {
    event.preventDefault();
    clearError();

    const username = usernameField.input.value.trim();
    const password = passwordField.input.value;
    if (!username || !password) {
      showError('Enter both a username and password.');
      return;
    }

    setLoading(true);
    try {
      await login(username, password);
      navigate('/dashboard');
    } catch (err) {
      if (err instanceof ApiError) {
        showError(
          err.status === 0
            ? 'Could not reach the IRIS server. Check the connection and try again.'
            : err.message || 'Sign-in failed.'
        );
      } else {
        showError(err.message || 'Invalid username or password.');
      }
    } finally {
      setLoading(false);
    }
  });

  usernameField.input.focus();
}

function buildField(id, labelText, type, autocomplete) {
  const wrapper = document.createElement('div');
  wrapper.className = 'form-field';

  const label = document.createElement('label');
  label.setAttribute('for', id);
  label.textContent = labelText;

  const input = document.createElement('input');
  input.id = id;
  input.name = id;
  input.type = type;
  input.autocomplete = autocomplete;
  input.required = true;
  input.className = 'text-input';

  wrapper.append(label, input);
  return { wrapper, input };
}
