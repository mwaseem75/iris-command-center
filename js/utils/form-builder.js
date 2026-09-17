// Minimal reusable form renderer for create/edit dialogs. Deliberately simple —
// text/number/checkbox/select only, no validation framework. Used with
// perform-action.js: build the form, collect values on submit, then run the
// actual mutation through the normal confirm/preview/execute/record pipeline.

/**
 * @param {{key: string, label: string, type?: 'text'|'number'|'checkbox'|'select', options?: string[], required?: boolean, help?: string}[]} fields
 * @param {object} [initialValues]
 */
export function createForm(fields, initialValues = {}) {
  const element = document.createElement('div');
  element.className = 'entity-form';
  const inputs = {};

  for (const field of fields) {
    const wrapper = document.createElement('div');
    wrapper.className = field.type === 'checkbox' ? 'form-field form-field--checkbox' : 'form-field';

    const label = document.createElement('label');
    label.textContent = field.label;
    label.setAttribute('for', `field-${field.key}`);

    let input;
    if (field.type === 'select') {
      input = document.createElement('select');
      input.className = 'text-input';
      for (const opt of field.options || []) {
        const optionEl = document.createElement('option');
        optionEl.value = opt;
        optionEl.textContent = opt;
        input.appendChild(optionEl);
      }
    } else if (field.type === 'checkbox') {
      input = document.createElement('input');
      input.type = 'checkbox';
    } else {
      input = document.createElement('input');
      input.type = field.type === 'number' ? 'number' : field.type === 'password' ? 'password' : 'text';
      input.className = 'text-input';
      if (field.type === 'password') input.autocomplete = 'new-password';
    }
    input.id = `field-${field.key}`;
    input.name = field.key;
    if (field.required) input.required = true;

    const initial = initialValues[field.key];
    if (field.type === 'checkbox') input.checked = Boolean(initial);
    else if (initial !== undefined && initial !== null) input.value = initial;

    inputs[field.key] = { input, type: field.type };

    if (field.type === 'checkbox') {
      wrapper.append(input, label);
    } else {
      wrapper.append(label, input);
    }

    if (field.help) {
      const help = document.createElement('p');
      help.className = 'form-field__help';
      help.textContent = field.help;
      wrapper.appendChild(help);
    }

    element.appendChild(wrapper);
  }

  return {
    element,
    getValues() {
      const values = {};
      for (const [key, { input, type }] of Object.entries(inputs)) {
        if (type === 'checkbox') values[key] = input.checked;
        else if (type === 'number') values[key] = input.value === '' ? undefined : Number(input.value);
        // An empty text/select value is omitted (not sent as "") so the server applies
        // its own default rather than us overwriting it with an empty string — confirmed
        // necessary live: sending TempGlobals:"" on namespace create causes a server-side
        // <SUBSCRIPT> error instead of falling back to IRISTEMP.
        else values[key] = input.value === '' ? undefined : input.value;
      }
      return values;
    },
    focus() {
      const first = Object.values(inputs)[0];
      first?.input.focus();
    },
  };
}
